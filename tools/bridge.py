"""Read-only VoxelScope client. Standard library only; never prints credentials."""
import argparse
import json
import os
import sqlite3
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, ProxyHandler, build_opener
from local_index import Index

DEFAULT_INSTANCE = Path(os.environ.get("VOXELSCOPE_INSTANCE", ".")).expanduser()


def query(instance, route, params):
    directory = Path(instance) / "voxelscope"
    connection = json.loads((directory / "connection.json").read_text(encoding="utf-8"))
    base = connection["url"]
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password:
        raise ValueError("Connection must point to the local bridge")
    token = (directory / "token.txt").read_text(encoding="utf-8").strip()
    suffix = "?" + urlencode(params) if params else ""
    request = Request(base + "/v1/" + route + suffix, headers={"Authorization": "Bearer " + token})
    # Local traffic must not go through system proxies.
    with build_opener(ProxyHandler({})).open(request, timeout=6) as response:
        raw = response.read(32769)
        if len(raw) > 32768:
            raise ValueError("Response exceeded budget")
        return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, default=DEFAULT_INSTANCE, help="Minecraft instance/server directory (default: VOXELSCOPE_INSTANCE or current directory)")
    parser.add_argument("--index-dir", type=Path, help="Store the local index outside the instance folder")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check installation and connection without printing credentials")
    migration = commands.add_parser("migrate", help="Import legacy labels/history without overwriting existing data")
    migration.add_argument("--source", type=Path, required=True)
    migration.add_argument("--dry-run", action="store_true")
    commands.add_parser("status")
    commands.add_parser("players")
    entity = commands.add_parser("entity", help="Inspect one loaded entity by UUID (mod 0.3.0+)")
    entity.add_argument("uuid")
    entity.add_argument("--dimension", default="minecraft:overworld")
    entity.add_argument("--side", choices=("up", "down", "north", "south", "east", "west"))
    entity.add_argument("--limit", type=int, default=20)
    entity.add_argument("--offset", type=int, default=0)
    data = commands.add_parser("data", help="Browse saved-data fields or read one scalar (mod 0.3.0+)")
    data.add_argument("--target", choices=("block", "entity"), default="block")
    for axis in ("x", "y", "z"):
        data.add_argument("--" + axis, type=int)
    data.add_argument("--uuid")
    data.add_argument("--dimension", default="minecraft:overworld")
    data.add_argument("--path", default="")
    data.add_argument("--limit", type=int, default=16)
    data.add_argument("--offset", type=int, default=0)
    scan = commands.add_parser("scan", help="Index machines in loaded chunks around the player")
    scan.add_argument("--player", help="Player name or UUID when more than one player is online")
    scan.add_argument("--chunk-radius", type=int, choices=range(0, 5), default=1)
    find = commands.add_parser("find", help="Search last-seen machine locations in this world's local index")
    find.add_argument("filter")
    find.add_argument("--limit", type=int, choices=range(1, 51), default=20)
    label = commands.add_parser("label", help="Name the block the player is looking at")
    label.add_argument("name")
    label.add_argument("--player", help="Player name or UUID when more than one player is online")
    inspect = commands.add_parser("inspect", help="Read a previously named block")
    inspect.add_argument("name")
    for name in ("block", "nearby", "me", "entities"):
        sub = commands.add_parser(name)
        for axis in ("x", "y", "z"):
            sub.add_argument(axis, type=int)
        sub.add_argument("--dimension", default="minecraft:overworld")
        sub.add_argument("--limit", type=int, default=20)
        if name in ("nearby", "entities"):
            sub.add_argument("--radius", type=int, default=8 if name == "nearby" else 16)
            sub.add_argument("--filter", default="")
        elif name == "block":
            sub.add_argument("--side", choices=("up", "down", "north", "south", "east", "west"))
            sub.add_argument("--offset", type=int, default=0)
        else:
            sub.add_argument("--filter", default="")
            sub.add_argument("--offset", type=int, default=0)
    args = vars(parser.parse_args())
    instance = args.pop("instance")
    index_dir = args.pop("index_dir")
    command = args.pop("command")
    try:
        if command == "doctor":
            from diagnostics import diagnose
            result = diagnose(instance, lambda route, params: query(instance, route, params))
        elif command == "migrate":
            from migration import migrate
            result = migrate(args["source"], index_dir or instance / "voxelscope", args["dry_run"])
        elif command in ("scan", "find", "label", "inspect"):
            result = indexed_query(instance, command, args, index_dir)
        else:
            result = query(instance, command, {key: value for key, value in args.items() if value is not None})
    except sqlite3.Error:
        result = {"error": "migration_database_invalid", "hint": "Check the legacy databases; no existing destination data was replaced."}
    except FileNotFoundError:
        result = {"error": "bridge_not_running", "hint": "Install the bridge and open a world, or select the correct instance."}
    except HTTPError as error:
        try:
            result = json.loads(error.read(32768))
        except ValueError:
            result = {"error": "http_error", "status": error.code}
    except (URLError, TimeoutError):
        result = {"error": "bridge_unreachable", "hint": "The world may be closed, paused, or still starting."}
    except (ValueError, OSError, KeyError, TypeError) as error:
        if command == "migrate" and isinstance(error, ValueError):
            result = {"error": "migration_rejected", "reason": str(error)[:256]}
        else:
            result = {"error": "invalid_connection_or_response"}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 1 if "error" in result or command == "doctor" and result.get("status") != "ready" else 0


def indexed_query(instance, command, args, index_dir=None):
    status = query(instance, "status", {})
    world = status["world_id"]
    directory = Path(index_dir) if index_dir is not None else Path(instance) / "voxelscope"
    directory.mkdir(parents=True, exist_ok=True)
    index = Index(directory / "index.sqlite3")
    try:
        if command == "find":
            return index.find(world, args["filter"], args["limit"])
        if command == "inspect":
            label = index.lookup(world, args["name"])
            result = query(instance, "block", {key: label[key] for key in ("dimension", "x", "y", "z")})
            if result["world_id"] != world:
                raise ValueError("World changed during query")
            result["label"] = args["name"]
            result["label_matches_original_block"] = result.get("id") == label["expected_id"] if result["loaded"] else None
            return result
        players = query(instance, "players", {})
        if players["world_id"] != world:
            raise ValueError("World changed during query")
        candidates = players["players"]
        selected = args.get("player")
        if selected:
            candidates = [p for p in candidates if selected in (p["name"], p["uuid"])]
        if len(candidates) != 1:
            return {"error": "select_one_player", "hint": "Use --player NAME or UUID for scan/label when multiple players are online."}
        player = candidates[0]
        if command == "label":
            if "target" not in player:
                return {"error": "no_target_block", "hint": "Look at a block within six blocks."}
            target = dict(player["target"], dimension=player["dimension"])
            index.label(world, args["name"], target)
            return {"label": args["name"], "block": target, "world_id": world}
        position = player["position"]
        cx, cz = position["x"] // 16, position["z"] // 16
        radius = args["chunk_radius"]
        loaded = unloaded = saved = incomplete = 0
        deadline = time.monotonic() + 30
        for x in range(cx - radius, cx + radius + 1):
            for z in range(cz - radius, cz + radius + 1):
                rows, offset, complete = [], 0, False
                chunk = None
                for _ in range(64):
                    if time.monotonic() >= deadline:
                        break
                    chunk = query(instance, "chunk", {"dimension": player["dimension"],
                                                      "chunk_x": x, "chunk_z": z, "offset": offset, "limit": 50})
                    if chunk["world_id"] != world or chunk["session"] != status["session"]:
                        raise ValueError("World session changed during scan")
                    if not chunk["loaded"]:
                        break
                    rows.extend(chunk["machines"])
                    if not chunk["truncated"]:
                        complete = True
                        break
                    next_offset = chunk.get("next_offset", offset)
                    if next_offset <= offset:
                        break
                    offset = next_offset
                if chunk is None:
                    incomplete += 1
                elif not chunk["loaded"]:
                    unloaded += 1
                else:
                    loaded += 1
                    incomplete += not complete
                    # Multiple pages aren't an atomic snapshot. Keep old rows if paginated to avoid false deletions.
                    index.record_chunk(world, player["dimension"], x, z, rows,
                                       chunk["observed_at"], chunk["session"], complete and offset == 0)
                    saved += len(rows)
        return {"loaded_chunks_observed": loaded, "unloaded_chunks_skipped": unloaded,
                "incomplete_chunks": incomplete, "machine_observations_saved": saved,
                "world_id": world, "note": "Only loaded chunks were inspected; index entries are last-seen observations."}
    finally:
        index.close()


if __name__ == "__main__":
    sys.exit(main())
