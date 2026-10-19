"""Copy legacy SQLite data safely; never copy credentials or touch world saves."""
from contextlib import ExitStack, closing as _closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

SCHEMAS = {
    "index.sqlite3": {"machines", "labels"},
    "monitor.sqlite3": {"profiles", "samples", "states", "events", "alert_states", "leases"},
}

REQUIRED_COLUMNS = {
    "machines": "world dimension x y z id observed_at session",
    "labels": "world name dimension x y z expected_id",
    "profiles": "id world name config revision enabled",
    "samples": "id profile revision metric observed received monotonic run session tick value context capacity",
    "states": "profile status received session tick detail",
    "events": "id profile received kind detail",
    "alert_states": "profile metric state",
    "leases": "name owner expires",
}


def open_source(path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Source database integrity check failed")
        schema = connection.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        tables = {name for kind, name in schema if kind == "table"}
        if tables != SCHEMAS[path.name] or any(kind not in ("table", "index") for kind, _ in schema):
            raise ValueError("Unsupported source database schema")
        for table in tables:
            columns = {row[1] for row in connection.execute('PRAGMA table_info("' + table + '")')}
            if not set(REQUIRED_COLUMNS[table].split()) <= columns:
                raise ValueError("Unsupported source database columns")
        if path.name == "monitor.sqlite3" and connection.execute("SELECT 1 FROM leases WHERE expires>? LIMIT 1", (time.time(),)).fetchone():
            raise ValueError("Stop the source collector and wait for its lease to clear before migration")
        return connection
    except Exception:
        connection.close()
        raise


def migrate(source, destination, dry_run=False):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or not source.is_dir():
        raise ValueError("Choose an existing legacy data directory and a different destination")
    paths = [source / name for name in SCHEMAS if (source / name).is_file()]
    if not paths:
        raise ValueError("No legacy index.sqlite3 or monitor.sqlite3 found")
    for path in paths:
        if path.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("Source database exceeds the 256 MiB migration limit")
    for name in (*SCHEMAS, "migration-report.json"):
        if (destination / name).exists():
            raise ValueError("Destination already contains data; migration never overwrites or merges databases")
    with ExitStack() as stack:
        # SQLite may create WAL/SHM sidecars even for mode=ro. Read private copies so the legacy directory stays byte-for-byte intact.
        snapshot = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="voxelscope-legacy-")))
        for path in paths:
            inputs = [path] + ([Path(str(path) + "-wal")] if Path(str(path) + "-wal").exists() else [])
            if any(item.stat().st_size > 256 * 1024 * 1024 for item in inputs):
                raise ValueError("Source database or WAL exceeds the 256 MiB migration limit")
            before = [(item, item.stat().st_size, item.stat().st_mtime_ns) for item in inputs]
            for item in inputs:
                shutil.copyfile(item, snapshot / item.name)
            if any(not item.exists() or (item.stat().st_size, item.stat().st_mtime_ns) != (size, modified) for item, size, modified in before):
                raise ValueError("Source changed during migration; stop all source collectors/clients and retry")
        connections = {path.name: stack.enter_context(_closing(open_source(snapshot / path.name))) for path in paths}
        counts = {name: {table: db.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0]
                         for table in sorted(SCHEMAS[name]) if table != "leases"} for name, db in connections.items()}
        result = {"status": "dry_run" if dry_run else "migrated", "databases": counts,
                  "source_preserved": True, "credentials_copied": False,
                  "note": "History retains its original world identity; no collector was started."}
        if dry_run:
            return result
        destination.mkdir(parents=True, exist_ok=True)
        lock = destination / ".migration-lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ValueError("Another migration is in progress; do not run migrations concurrently") from None
        os.close(descriptor)
        created = []
        try:
            with tempfile.TemporaryDirectory(prefix=".migration-", dir=destination) as staging:
                staging = Path(staging)
                for name, db in connections.items():
                    with _closing(sqlite3.connect(staging / name)) as backup:
                        db.backup(backup)
                        if name == "monitor.sqlite3":
                            backup.execute("DELETE FROM leases")
                            backup.commit()
                        if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise ValueError("Migrated database integrity check failed")
                report = dict(result, migrated_at=datetime.now(timezone.utc).isoformat())
                (staging / "migration-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                for path in staging.iterdir():
                    target = destination / path.name
                    # Exclusive creation prevents accidental overwrite even if another tool creates data mid-migration.
                    with target.open("xb") as output:
                        created.append(target)
                        with path.open("rb") as input_file:
                            shutil.copyfileobj(input_file, output)
                        output.flush()
                        os.fsync(output.fileno())
            return result
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        finally:
            lock.unlink(missing_ok=True)

