"""Configure, collect, and summarize local VoxelScope readings. No packages required."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
from urllib.error import HTTPError
from bridge import DEFAULT_INSTANCE, query
from local_index import Index
from monitoring import MonitorStore, collect, discover, inferred_unit, numeric, pointer_get, capacity_path, state_value, state_key




def source(instance, data, world, label, route, params):
    if params is not None:
        args = json.loads(params)
        if not isinstance(args, dict) or len(args) > 16:
            raise ValueError("Parameters must be a small JSON object")
        return args, None
    index = Index(data / "index.sqlite3")
    try:
        target = index.lookup(world, label)
    finally:
        index.close()
    args = {key: target[key] for key in ("dimension", "x", "y", "z")}
    return args, target["expected_id"] if route in ("block", "data") else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, default=DEFAULT_INSTANCE)
    parser.add_argument("--data-dir", type=Path, help="Local index/history directory (default: INSTANCE/voxelscope)")
    parser.add_argument("--world", help="Required to select among multiple offline worlds")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("discover", "add"):
        p = sub.add_parser(command)
        p.add_argument("name", help="Profile name; by default also the saved block label")
        p.add_argument("--label")
        p.add_argument("--route", choices=("block", "me", "entity", "data"), default="block")
        p.add_argument("--params", help="Explicit read-only query parameters as JSON, instead of a saved label")
        if command == "add":
            p.add_argument("--field", action="append", help="JSON pointer; repeat to select fields")
            p.add_argument("--kind", choices=("auto", "number", "state"), default="auto", help="auto uses states for booleans/strings and numbers otherwise")
            p.add_argument("--state-label", action="append", default=[], metavar="VALUE=TEXT", help="Name a state transition, for one selected field; e.g. false=Reactor stopped")
            p.add_argument("--unit", help="Explicit unit for a single field")
            p.add_argument("--capacity", help="Capacity JSON pointer for a single field")
            p.add_argument("--below", type=float, help="Record a local event when one field crosses below this")
            p.add_argument("--above", type=float, help="Record a local event when one field crosses above this")
    sub.add_parser("profiles")
    run = sub.add_parser("run")
    run.add_argument("--name", action="append")
    run.add_argument("--duration", type=float, default=60)
    run.add_argument("--interval", type=float, default=5)
    report = sub.add_parser("report")
    report.add_argument("--name", action="append")
    report.add_argument("--minutes", type=float, default=60)
    args = parser.parse_args()
    args.data_dir = args.data_dir or args.instance / "voxelscope"
    args.data_dir.mkdir(parents=True, exist_ok=True)
    store = MonitorStore(args.data_dir / "monitor.sqlite3")
    try:
        # Reports and profile listings can work with Minecraft closed; never silently choose between worlds.
        if args.command in ("report", "profiles"):
            worlds = store.worlds()
            world = args.world or (worlds[0] if len(worlds) == 1 else None)
            if world is None:
                raise ValueError("Select --world, or configure a profile first")
        else:
            status = query(args.instance, "status", {})
            world = status["world_id"]
            if args.world and args.world != world:
                raise ValueError("The open world does not match --world")
        if args.command in ("discover", "add"):
            params, expected_id = source(args.instance, args.data_dir, world,
                                         args.label or args.name, args.route, args.params)
            snapshot = query(args.instance, args.route, params)
            if snapshot.get("world_id") != world:
                raise ValueError("World changed during configuration")
            if snapshot.get("loaded") is False or snapshot.get("error"):
                raise ValueError("Target must be available while configuring")
            if expected_id and snapshot.get("id") != expected_id:
                raise ValueError("Named location no longer contains its original block type")
            found = discover(snapshot)
            if args.command == "discover":
                if args.route == "data":
                    result = dict(snapshot, monitor_value_path="/value" if numeric(snapshot.get("value")) or state_value(snapshot.get("value")) else None)
                else:
                    result = dict(found, world_id=world, source=args.route, label=args.label or args.name)
            else:
                if args.route == "data" and not (numeric(snapshot.get("value")) or state_value(snapshot.get("value"))):
                    raise ValueError("Select a scalar saved field using --params with its saved-data path first")
                paths = args.field or (["/value"] if args.route == "data" else [f["path"] for f in found["fields"] if f["monitorable"]])
                if len(paths) != 1 and any(v is not None for v in (args.unit, args.capacity, args.below, args.above)):
                    raise ValueError("Unit/capacity/threshold options require exactly one --field")
                if args.state_label and len(paths) != 1:
                    raise ValueError("State labels require exactly one selected field")
                labels = {}
                for item in args.state_label:
                    raw, separator, label = item.partition("=")
                    if not separator or not label or len(label) > 80:
                        raise ValueError("Use --state-label VALUE=TEXT, with text up to 80 characters")
                    try:
                        value = json.loads(raw)
                    except ValueError:
                        value = raw
                    if not state_value(value):
                        raise ValueError("State label values must be booleans, short strings, or integers")
                    labels[state_key(value)] = label
                metrics = []
                for path in paths:
                    value = pointer_get(snapshot, path)
                    kind = args.kind if args.kind != "auto" else "state" if isinstance(value, (bool, str)) else "number"
                    if not (state_value(value) if kind == "state" else numeric(value)):
                        raise ValueError("Selected field is not an available " + kind + ": " + path)
                    if kind == "state":
                        if any(v is not None for v in (args.unit, args.capacity, args.below, args.above)):
                            raise ValueError("State fields cannot use numeric units, capacities, or thresholds")
                        metrics.append({"path": path, "kind": "state", "state_labels": labels})
                        continue
                    if labels:
                        raise ValueError("State labels require a state field")
                    cap = args.capacity if len(paths) == 1 and args.capacity else capacity_path(path)
                    if cap and not numeric(pointer_get(snapshot, cap)):
                        if args.capacity:
                            raise ValueError("Capacity field is not numeric")
                        cap = None
                    metrics.append({"path": path, "unit": args.unit or inferred_unit(path),
                                    "capacity_path": cap, "below": args.below, "above": args.above})
                if expected_id is None and args.route in ("block", "entity", "data"):
                    expected_id = snapshot.get("id")
                config = {"route": args.route, "params": params, "expected_id": expected_id, "metrics": metrics, "interval": 5}
                profile = store.register(world, args.name, config)
                result = {"configured": profile["name"], "fields": metrics, "world_id": world,
                          "note": "Configured only; no background process was started."}
        elif args.command == "profiles":
            result = {"world_id": world, "profiles": [{"name": p["name"], "source": p["config"]["route"],
                        "fields": p["config"]["metrics"]} for p in store.profiles(world)]}
        elif args.command == "run":
            profiles = store.profiles(world, args.name)
            result = collect(store, profiles, lambda route, params: query(args.instance, route, params),
                             args.duration, args.interval)
            result["report"] = store.report(world, args.name, minutes=max(1, args.duration / 60 + 1))
        else:
            if not 0 < args.minutes <= 10080:
                raise ValueError("Report window must be between 0 and 10080 minutes")
            result = store.report(world, args.name, args.minutes)
    except HTTPError as error:
        result = {"error": "bridge_query_failed", "http_status": error.code}
        if error.code == 404:
            result["hint"] = "Check that the running mod supports the requested API route."
    except FileNotFoundError:
        result = {"error": "bridge_not_running"}
    except (ValueError, OSError, sqlite3.Error) as error:
        # Never include arbitrary HTTP response text or a token in diagnostics.
        result = {"error": str(error) if isinstance(error, ValueError) else "local_storage_or_connection_unavailable"}
    finally:
        store.close()
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(payload.encode("utf-8")) > 32768:
        result = {"error": "summary_too_large", "hint": "Select one --name or fewer fields."}
        payload = json.dumps(result)
    print(payload)
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
