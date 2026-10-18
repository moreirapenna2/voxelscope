"""Bounded, read-only time series. No machine-specific collectors or background services."""
from decimal import Decimal
import hashlib
import json
import math
import sqlite3
import time
import uuid


def pointer_get(value, path):
    if path == "":
        return value
    if not path.startswith("/") or len(path) > 512:
        raise ValueError("Use a JSON pointer such as /energy/stored_fe")
    for segment in path[1:].split("/"):
        key = segment.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(value, list):
                if not key.isdigit():
                    return None
                value = value[int(key)]
            elif isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        except (IndexError, ValueError):
            return None
    return value


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (
        not isinstance(value, float) or math.isfinite(value))


def metric_context(snapshot, path):
    """Reset trends if a tank changes chemical or a list index refers to another item/slot."""
    contexts = []
    parts = path.split("/")
    for end in range(1, len(parts)):
        parent = pointer_get(snapshot, "/".join(parts[:end]))
        if isinstance(parent, dict):
            identity = {k: parent[k] for k in ("id", "uuid", "slot", "tank")
                        if k in parent and isinstance(parent[k], (str, int)) and not isinstance(parent[k], bool)}
            if identity:
                contexts.append(identity)
    return json.dumps(contexts, sort_keys=True, separators=(",", ":"))


def inferred_unit(path):
    # Only interpret unit labels defined by this bridge. Raw NBT remains explicitly unknown.
    if path.startswith("/value") or path.startswith("/saved"):
        return "unknown"
    key = path.rsplit("/", 1)[-1]
    if key in ("health", "max_health"):
        return "HP"
    for suffix, unit in (("_mb_per_tick", "mB/t"), ("_fe_per_tick", "FE/t"),
                         ("_ae_per_tick", "AE/t"), ("_mb", "mB"), ("_fe", "FE"),
                         ("_ae", "AE"), ("_kelvin", "K"), ("_percent", "%")):
        if key.endswith(suffix):
            return unit
    return "count" if key in ("count", "slots", "network_nodes") else "unknown"


def capacity_path(path):
    parent, _, key = path.rpartition("/")
    counterpart = {"amount_mb": "capacity_mb", "stored_fe": "capacity_fe", "stored_ae": "capacity_ae", "health": "max_health"}.get(key)
    return parent + "/" + counterpart if counterpart else None


def discover(snapshot, limit=128):
    fields, visited = [], 0

    def walk(value, path, depth):
        nonlocal visited
        visited += 1
        if depth > 12 or visited > 2048 or len(fields) >= limit:
            return
        if isinstance(value, dict):
            for key in sorted(value):
                escaped = key.replace("~", "~0").replace("/", "~1")
                walk(value[key], path + "/" + escaped, depth + 1)
        elif isinstance(value, list):
            for i, item in enumerate(value[:50]):
                walk(item, path + "/" + str(i), depth + 1)
        elif isinstance(value, (str, int, float, bool)):
            row = {"path": path, "type": "boolean" if isinstance(value, bool) else "number" if numeric(value) else "string",
                   "monitorable": numeric(value) and path not in ("/x", "/y", "/z", "/game_tick"),
                   "unit": inferred_unit(path)}
            if numeric(value) or isinstance(value, bool):
                row["current"] = value
            cap = capacity_path(path)
            if cap and numeric(pointer_get(snapshot, cap)):
                row["capacity_path"] = cap
            fields.append(row)
    walk(snapshot, "", 0)
    return {"fields": fields, "truncated": len(fields) >= limit or visited > 2048,
            "note": "Only fields exposed by this snapshot; array indices may refer to changing contents."}


def as_number(value):
    if value is None:
        return None
    number = Decimal(str(value))
    return int(number) if number == number.to_integral_value() else float(number)


class MonitorStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY, world TEXT NOT NULL, name TEXT NOT NULL,
                config TEXT NOT NULL, revision TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                UNIQUE(world,name));
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY, profile INTEGER NOT NULL REFERENCES profiles(id),
                revision TEXT NOT NULL, metric TEXT NOT NULL, observed TEXT NOT NULL,
                received REAL NOT NULL, monotonic REAL NOT NULL, run TEXT NOT NULL,
                session TEXT NOT NULL, tick INTEGER NOT NULL, value TEXT NOT NULL,
                context TEXT NOT NULL, capacity TEXT, interval REAL NOT NULL DEFAULT 5);
            CREATE INDEX IF NOT EXISTS sample_lookup ON samples(profile,revision,metric,received DESC,id DESC);
            CREATE TABLE IF NOT EXISTS states (
                profile INTEGER PRIMARY KEY REFERENCES profiles(id), status TEXT NOT NULL,
                received REAL NOT NULL, session TEXT, tick INTEGER, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, profile INTEGER NOT NULL REFERENCES profiles(id),
                received REAL NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS event_lookup ON events(profile,received DESC);
            CREATE TABLE IF NOT EXISTS alert_states (
                profile INTEGER, metric TEXT, state TEXT NOT NULL, PRIMARY KEY(profile,metric));
            CREATE TABLE IF NOT EXISTS leases (name TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
        """)
        if "interval" not in {row[1] for row in self.db.execute("PRAGMA table_info(samples)")}:
            self.db.execute("ALTER TABLE samples ADD COLUMN interval REAL NOT NULL DEFAULT 5")
            self.db.commit()

    def close(self):
        self.db.close()

    def acquire(self, owner, ttl):
        now = time.time()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            lease = self.db.execute("SELECT * FROM leases WHERE name='collector'").fetchone()
            if lease and lease["expires"] > now and lease["owner"] != owner:
                raise ValueError("A collector is already running for this database")
            self.db.execute("INSERT OR REPLACE INTO leases VALUES ('collector',?,?)", (owner, now + ttl))

    def release(self, owner):
        with self.db:
            self.db.execute("DELETE FROM leases WHERE name='collector' AND owner=?", (owner,))

    def register(self, world, name, config):
        if not world or not name.strip() or len(name) > 80:
            raise ValueError("Invalid world or profile name")
        if config["route"] not in ("block", "me", "entity", "data"):
            raise ValueError("Unsupported read-only source")
        if not 1 <= len(config["metrics"]) <= 32:
            raise ValueError("Select between 1 and 32 numeric fields")
        paths = [metric["path"] for metric in config["metrics"]]
        if len(set(paths)) != len(paths):
            raise ValueError("Duplicate field")
        for metric in config["metrics"]:
            pointer_get({}, metric["path"])
            if metric.get("capacity_path"):
                pointer_get({}, metric["capacity_path"])
            below, above = metric.get("below"), metric.get("above")
            if any(v is not None and not numeric(v) for v in (below, above)):
                raise ValueError("Thresholds must be finite numbers")
            if below is not None and above is not None and below >= above:
                raise ValueError("Lower threshold must be below upper threshold")
        encoded = json.dumps(config, sort_keys=True, separators=(",", ":"))
        revision = hashlib.sha256(encoded.encode()).hexdigest()[:16]
        with self.db:
            old = self.db.execute("SELECT * FROM profiles WHERE world=? AND name=?", (world, name)).fetchone()
            self.db.execute("""INSERT INTO profiles(world,name,config,revision) VALUES (?,?,?,?)
                ON CONFLICT(world,name) DO UPDATE SET config=excluded.config,revision=excluded.revision,enabled=1""",
                            (world, name, encoded, revision))
            if old and old["revision"] != revision:
                self.db.execute("DELETE FROM states WHERE profile=?", (old["id"],))
                self.db.execute("DELETE FROM alert_states WHERE profile=?", (old["id"],))
        return self.profiles(world, [name])[0]

    def profiles(self, world, names=None):
        rows = self.db.execute("SELECT * FROM profiles WHERE world=? AND enabled=1 ORDER BY name", (world,)).fetchall()
        result = []
        for row in rows:
            if names and row["name"] not in names:
                continue
            profile = dict(row)
            profile["config"] = json.loads(profile["config"])
            result.append(profile)
        if names and set(names) != {r["name"] for r in result}:
            raise ValueError("Some profiles do not exist in this world")
        return result

    def worlds(self):
        return [r[0] for r in self.db.execute("SELECT DISTINCT world FROM profiles WHERE enabled=1")]

    def status(self, profile, status, received, session=None, tick=None, detail=""):
        previous = self.db.execute("SELECT status FROM states WHERE profile=?", (profile["id"],)).fetchone()
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO states VALUES (?,?,?,?,?,?)",
                            (profile["id"], status, received, session, tick, detail))
            if previous is None or previous[0] != status:
                self.db.execute("INSERT INTO events(profile,received,kind,detail) VALUES (?,?,?,?)",
                                (profile["id"], received, "status", status))

    def record(self, profile, snapshot, run_id, interval, received=None, monotonic=None):
        received = time.time() if received is None else received
        monotonic = time.monotonic() if monotonic is None else monotonic
        session, tick = snapshot.get("session"), snapshot.get("game_tick")
        status = "ok"
        if snapshot.get("world_id") != profile["world"]:
            status = "world_changed"
        elif snapshot.get("loaded") is False:
            status = "unloaded"
        elif snapshot.get("error"):
            status = "query_failed"
        elif profile["config"].get("expected_id") and snapshot.get("id") != profile["config"]["expected_id"]:
            status = "target_changed"
        elif not isinstance(session, str) or not isinstance(tick, int):
            status = "invalid_observation"
        previous = self.db.execute("SELECT * FROM states WHERE profile=?", (profile["id"],)).fetchone()
        if status == "ok" and previous and previous["session"] == session and previous["tick"] == tick:
            status = "no_tick_progress"
        if status != "ok":
            self.status(profile, status, received, session, tick)
            return status
        missing = []
        with self.db:
            for metric in profile["config"]["metrics"]:
                value = pointer_get(snapshot, metric["path"])
                if not numeric(value):
                    missing.append(metric["path"])
                    continue
                cap = pointer_get(snapshot, metric.get("capacity_path", "")) if metric.get("capacity_path") else None
                self.db.execute("""INSERT INTO samples(profile,revision,metric,observed,received,monotonic,
                    run,session,tick,value,context,capacity,interval) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (profile["id"], profile["revision"], metric["path"], snapshot.get("observed_at", ""),
                     received, monotonic, run_id, session, tick, str(value), metric_context(snapshot, metric["path"]),
                     str(cap) if numeric(cap) else None, interval))
                alert = "below" if metric.get("below") is not None and value < metric["below"] else (
                    "above" if metric.get("above") is not None and value > metric["above"] else "normal")
                old = self.db.execute("SELECT state FROM alert_states WHERE profile=? AND metric=?",
                                      (profile["id"], metric["path"])).fetchone()
                if (old is None and alert != "normal") or (old is not None and old[0] != alert):
                    self.db.execute("INSERT INTO events(profile,received,kind,detail) VALUES (?,?,?,?)",
                                    (profile["id"], received, "threshold", json.dumps({"path": metric["path"], "state": alert, "value": value})))
                self.db.execute("INSERT OR REPLACE INTO alert_states VALUES (?,?,?)", (profile["id"], metric["path"], alert))
        status = "fields_missing" if missing else "ok"
        self.status(profile, status, received, session, tick, json.dumps(missing))
        return status

    def report(self, world, names=None, minutes=60, now=None):
        now = time.time() if now is None else now
        results, remaining = [], 64
        for profile in self.profiles(world, names):
            if remaining == 0:
                break
            state = self.db.execute("SELECT * FROM states WHERE profile=?", (profile["id"],)).fetchone()
            out = {"name": profile["name"], "status": state["status"] if state else "not_sampled", "metrics": []}
            if state:
                out["seconds_since_attempt"] = round(max(0, now - state["received"]), 2)
            boundary = self.db.execute("""SELECT MAX(received) FROM events
                WHERE profile=? AND kind='status' AND detail!='ok'""", (profile["id"],)).fetchone()[0]
            interval = profile["config"].get("interval", 5)
            for metric in profile["config"]["metrics"]:
                if remaining == 0:
                    break
                rows = self.db.execute("""SELECT * FROM samples WHERE profile=? AND revision=? AND metric=? AND received>=?
                    ORDER BY received DESC,id DESC LIMIT 5001""", (profile["id"], profile["revision"], metric["path"], now - minutes * 60)).fetchall()
                row = summarize(rows[:5000], metric, interval, now, boundary)
                row["source_available_at_last_attempt"] = state is not None and state["status"] == "ok"
                if state is not None and state["status"] != "ok":
                    row["stale"] = True
                row["history_truncated"] = len(rows) > 5000
                out["metrics"].append(row)
                remaining -= 1
            out["recent_events"] = [dict(r) for r in self.db.execute("""SELECT received,kind,detail FROM events
                WHERE profile=? AND received>=? ORDER BY id DESC LIMIT 5""", (profile["id"], now - minutes * 60))]
            results.append(out)
        return {"world_id": world, "window_minutes": minutes, "profiles": results, "truncated": remaining == 0,
                "rate_note": "Changes in stored amounts are net balance, not separate production and consumption. Per-game-second rates assume 20 ticks."}

    def prune(self, now=None):
        now = time.time() if now is None else now
        with self.db:
            self.db.execute("DELETE FROM samples WHERE received<?", (now - 7 * 86400,))
            self.db.execute("DELETE FROM events WHERE received<?", (now - 7 * 86400,))
            self.db.execute("DELETE FROM samples WHERE id < COALESCE((SELECT id FROM samples ORDER BY id DESC LIMIT 1 OFFSET 199999),0)")
            self.db.execute("DELETE FROM events WHERE id < COALESCE((SELECT id FROM events ORDER BY id DESC LIMIT 1 OFFSET 9999),0)")


def summarize(rows, metric, interval, now, boundary=None):
    out = {"path": metric["path"], "unit": metric.get("unit", "unknown"), "samples_in_window": len(rows)}
    if not rows:
        return out
    latest = rows[0]
    interval = latest["interval"]
    out.update(latest=as_number(latest["value"]), observed_at=latest["observed"],
               age_seconds=round(max(0, now - latest["received"]), 2),
               stale=now - latest["received"] > max(15, interval * 2.5))
    # Never calculate a trend through restarts, pauses, missing data, identity changes or large gaps.
    segment = [latest] if boundary is None or latest["received"] > boundary else []
    for older in rows[1:]:
        if not segment:
            break
        newer = segment[-1]
        if (older["run"], older["session"], older["context"]) != (latest["run"], latest["session"], latest["context"]):
            break
        if (older["tick"] >= newer["tick"] or older["monotonic"] >= newer["monotonic"]
                or newer["monotonic"] - older["monotonic"] > max(15, interval * 2.5)
                or (boundary is not None and older["received"] <= boundary)):
            break
        segment.append(older)
    values = [Decimal(r["value"]) for r in segment]
    out["continuous_samples"] = len(segment)
    if values:
        out.update(minimum=as_number(min(values)), maximum=as_number(max(values)))
    cap = Decimal(latest["capacity"]) if latest["capacity"] is not None else None
    if cap is not None and cap > 0:
        out["capacity"] = as_number(cap)
        out["fill_percent"] = round(float(Decimal(latest["value"]) / cap * 100), 3)
    if len(segment) < 2:
        out["trend"] = "insufficient_continuous_data"
        return out
    oldest = segment[-1]
    delta = Decimal(latest["value"]) - Decimal(oldest["value"])
    ticks = latest["tick"] - oldest["tick"]
    elapsed = latest["monotonic"] - oldest["monotonic"]
    weighted = sum((Decimal(newer["value"]) + Decimal(older["value"])) / 2 * (newer["tick"] - older["tick"])
                   for newer, older in zip(segment, segment[1:]))
    tolerance = Decimal(str(metric.get("tolerance", 0.01 if metric.get("unit") == "K" else 0)))
    out.update(delta=as_number(delta), elapsed_game_ticks=ticks, elapsed_seconds=round(elapsed, 3),
               average=as_number(weighted / ticks), average_method="trapezoid_between_samples_by_game_ticks",
               change_per_tick=as_number(delta / ticks), change_per_game_second=as_number(delta * 20 / ticks),
               change_per_real_second=as_number(delta / Decimal(str(elapsed))),
               observed_ticks_per_second=round(ticks / elapsed, 3),
               trend="steady" if abs(delta) <= tolerance else "rising" if delta > 0 else "falling")
    if tolerance:
        out["trend_tolerance"] = as_number(tolerance)
    if cap is not None and delta > tolerance and Decimal(latest["value"]) < cap:
        out["estimated_game_seconds_to_full"] = as_number((cap - Decimal(latest["value"])) / (delta * 20 / ticks))
    elif cap is not None and delta < -tolerance and Decimal(latest["value"]) > 0:
        out["estimated_game_seconds_to_empty"] = as_number(Decimal(latest["value"]) / (-delta * 20 / ticks))
    if out.get("stale"):
        out["estimate_note"] = "Historical trend; latest observation is stale."
    elif "estimated_game_seconds_to_full" in out or "estimated_game_seconds_to_empty" in out:
        out["estimate_note"] = "Assumes this net trend continues; empty/full buffers can hide supply headroom."
    return out


def collect(store, profiles, query_fn, duration=60, interval=5):
    if not 1 <= duration <= 86400 or not 1 <= interval <= 300 or not 1 <= len(profiles) <= 16:
        raise ValueError("Use 1-16 profiles, duration 1-86400 seconds, interval 1-300 seconds")
    run_id = uuid.uuid4().hex
    ttl = max(120, interval + 120)
    store.acquire(run_id, ttl)
    try:
        return _collect(store, profiles, query_fn, duration, interval, run_id, ttl)
    finally:
        store.release(run_id)


def _collect(store, profiles, query_fn, duration, interval, run_id, ttl):
    deadline = time.monotonic() + duration
    attempts = successes = 0
    stopped = "duration_complete"
    try:
        while True:
            cycle = time.monotonic()
            for profile in profiles:
                store.acquire(run_id, ttl)
                config = profile["config"]
                attempts += 1
                try:
                    snapshot = query_fn(config["route"], config["params"])
                    status = store.record(profile, snapshot, run_id, interval)
                    successes += status == "ok"
                    if status == "world_changed":
                        return {"run_id": run_id, "attempts": attempts, "successful_observations": successes, "stopped": status}
                except (OSError, ValueError, TimeoutError):
                    store.status(profile, "query_unavailable", time.time())
            store.prune()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(remaining, max(0.05, interval - (time.monotonic() - cycle))))
            if time.monotonic() >= deadline:
                break
    except KeyboardInterrupt:
        stopped = "interrupted"
    return {"run_id": run_id, "attempts": attempts, "successful_observations": successes, "stopped": stopped}
