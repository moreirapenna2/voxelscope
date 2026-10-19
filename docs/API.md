# API and operational limits

The mod writes `connection.json` and `token.txt` in `INSTANCE/voxelscope/`. The port is selected automatically on each world/server startup. Read the connection file each time rather than caching its URL. Every route requires `Authorization: Bearer TOKEN`. Do not publish these files. The API binds only to `127.0.0.1` and rejects `Origin` headers and non-GET requests.

| Route | Query parameters |
| --- | --- |
| `/v1/status` | none |
| `/v1/players` | none |
| `/v1/block` | dimension, x, y, z, side, offset, limit |
| `/v1/me` | dimension, x, y, z, filter, offset, limit |
| `/v1/nearby` | dimension, x, y, z, radius, filter, limit |
| `/v1/chunk` | dimension, chunk_x, chunk_z, offset, limit |
| `/v1/entities` | dimension, x, y, z, radius, filter, limit |
| `/v1/entity` | dimension, uuid, side, offset, limit |
| `/v1/data` | target=block/entity, dimension, x/y/z or uuid, path, offset, limit |

Coordinates refer to loaded positions. Dimension defaults to `minecraft:overworld`; side defaults to unsided. Each successful response includes `world_id`, `session`, `game_tick`, and `observed_at`. Status retains the `bridge_version` field for API compatibility and identifies the product as VoxelScope. HTTP errors return a small `error` object. Typical responses include 400 invalid query, 401 authentication failure, 403 browser denied, 404 unknown route, 429 busy, 503 paused/unavailable game thread, and 500 inspection failure.

Limits include 32 KiB output, 2 KiB query strings, 50 entries per page, two HTTP workers and a bounded queue. Game-thread requests time out after three seconds of waiting. Broad readers cooperate with a 15 ms budget, but a single third-party capability/serialization callback cannot be preempted. Pausing singleplayer can cause timeouts. The API never deliberately loads or generates chunks.

`nearby` and machine indexing cover block entities, not all terrain or ordinary wires. Inspect an individual block for its state. The local scan visits at most 81 nearby chunks (default nine), skips unloaded chunks, and has a 30-second client budget. Incomplete scans retain old entries conservatively. A changing world makes pagination non-atomic; use filtered queries for precision.

## Generic saved-field discovery

```sh
python tools/bridge.py --instance "/path/to/instance" data --x 100 --y 64 --z -20
python tools/bridge.py --instance "/path/to/instance" data --x 100 --y 64 --z -20 --path /Items/0/id
python tools/bridge.py --instance "/path/to/instance" data --target entity --uuid UUID --path /Health
```

An empty path returns one level of names/types. Select a JSON Pointer path to read one scalar. Escape slash as `~1` and tilde as `~0`. Children are capped at 32, strings at 256 characters, paths at 512 characters/16 segments, and broad compounds at 4,096 keys. Entire nested compounds/lists are never dumped. Serialization happens on the game thread and calls the provider's saved-data reader; reserve it for selected targets. It never writes the snapshot back.

Numeric saved fields have unknown units until mapped. A byte is not automatically a boolean. Saved data can omit live multiblock state. There is no arbitrary reflected method invocation, ComputerCraft command execution, or write endpoint.

## Units, identity, and history

Reactor temperature is Kelvin. AE2 energy uses AE units; generic FE may clamp at signed 32-bit storage limits, while dedicated Mekanism readers preserve larger values. Energy deltas show net change rather than independent generation and consumption. Item components are not dumped; component-bearing variants remain separate.

World identity hashes the save path; it is not a world-content fingerprint. Moving a save changes identity, while replacing it at the same path can reuse identity. Rebuild external indexes when replacing a world. Labels check original block type, but replacing a block with the same type cannot be detected.

Monitoring preserves integers, separates real-time/game-time rates, and resets trend segments across runs, sessions, pauses, availability gaps, and contents changes. ETA assumes the sampled net rate continues. A full buffer cannot reveal surplus upstream production. Sample-based averages interpolate between observations and do not capture every intervening fluctuation.

Monitoring permits 1–16 profiles, 1–32 fields each, intervals 1–300 seconds, and finite duration up to 86,400 seconds. One collector per database is enforced with a lease. History is capped at seven days/200,000 samples and 10,000 events. Reports inspect at most 5,000 recent samples per field and 64 fields. Missing values are not zero. Local thresholds do not control machines or send notifications.


## Companion setup/state monitoring (0.4.0)

`bridge.py doctor` is a local diagnostic command, not a new HTTP route. It reads recognized installed mod metadata and queries `/v1/status`. The status response adds `mekanism_matrix_integration` so core Mekanism can be distinguished from its Generators module.

Legacy migration operates only on external SQLite databases. It preserves profile IDs/config revisions and sample precision; the monitor adds a `kind` column to older sample tables with `number` as the default. Existing numeric profile configurations keep their revision and history. New state metrics use `kind: state`; values are JSON-encoded to preserve type. Their optional `state_labels` keys are canonical JSON-encoded scalar values, e.g. `false` for a boolean and `0` for an integer. State metrics cannot use numeric capacities/thresholds.

State transitions are emitted only between continuous observations of the same profile revision, collector run, server session, and contents identity with increasing game ticks and bounded monotonic gaps. Reconnection establishes a baseline. State history uses the same retention/output/collector limits as numeric history. Reports describe sampled evidence rather than the exact time an in-game transition happened.
