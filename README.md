# VoxelScope

A local, read-only API for inspecting Minecraft worlds, machines, storage networks, and trends. Built for players, troubleshooting tools, dashboards, and AI assistants that need selected observations instead of enormous world dumps.

**Preview 0.4.0 · Minecraft 1.21.1 · NeoForge 21.1.233+ (21.1.x) · Java 21**

VoxelScope started as a helper for a StoneBlock 4 world. It has no dependency on that modpack. Other Minecraft versions and Fabric/Forge are not supported by this build.

## Features

- Read block IDs/states, player locations/targets, and loaded entities.
- Inspect exposed inventories, fluids, and Forge Energy using shared capability readers.
- Browse one level of saved block/entity fields, then request a selected scalar.
- Search AE2 item storage and read basic network/channel/power statistics when AE2 is installed.
- Read Mekanism chemicals, large energy stores, Induction Matrices, and fission reactors when the relevant modules are installed.
- Index loaded machines locally; search them and assign reusable names.
- Collect selected numeric values into bounded SQLite history, with rates, trends, thresholds, and conditional fill/empty estimates.

The API uses localhost, bearer authentication, GET-only routes, bounded responses, and no browser access. It adds no blocks, items, recipes, world generation, machine controls, or save attachments.

## Install

1. Download `voxelscope-0.4.0.jar` from [GitHub Releases](https://github.com/moreirapenna2/voxelscope/releases). While no release is published, build from source below.
2. Close Minecraft and place the JAR in the instance's `mods` directory. For a dedicated server, install on the server; clients do not need VoxelScope.
3. Start the game/server and open a world. Connection metadata is created in `INSTANCE/voxelscope/`.
4. Download/extract the companion bundle, or clone this repository. Install Python 3.10+; no Python packages are required.

Run from the repository or companion directory, replacing the example with your instance/server directory:

```sh
python tools/bridge.py --instance "/path/to/instance" status
python tools/bridge.py --instance "/path/to/instance" players
python tools/bridge.py --instance "/path/to/instance" block 100 64 -20 --side north
```

`--instance` defaults to `VOXELSCOPE_INSTANCE` if set, otherwise the current directory. The directory is the one containing `mods/`, not the world save or launcher installation directory. Put global options before the command. For a dedicated server, run the client on that same host; no remote listener is provided.

To uninstall, close the game/server and remove the JAR. External index/history files can be retained or removed separately. VoxelScope registers no gameplay content that needs conversion on removal. Back up worlds before testing preview mods.

**Upgrading from the private StoneBridge builds:** remove the old JAR before installing VoxelScope. The new runtime directory is `voxelscope/`; use the migration command below to import old external labels/history. The game save format is unchanged. Do not install both bridge mods together.

## Connection checks and migration

```sh
python tools/bridge.py --instance "/path/to/instance" doctor
python tools/bridge.py --instance "/path/to/instance" migrate --source "/path/to/legacy-data" --dry-run
python tools/bridge.py --instance "/path/to/instance" migrate --source "/path/to/legacy-data"
```

`doctor` reports recognized installed JARs, legacy/duplicate installations, connection/authentication failures, a paused/unresponsive world, API compatibility, and available integrations. It never prints credentials or creates runtime files. No connection while Minecraft is closed or at the main menu is expected; an unavailable API alone cannot distinguish those states from a startup failure.

Migration copies `index.sqlite3` and/or `monitor.sqlite3`, including labels, profiles, and numeric history. It uses private snapshots and SQLite backups, handles committed WAL data, checks integrity, clears copied collector leases, and leaves the original directory intact. Credentials, connection files, screenshots, and scan dumps are excluded. Stop source collectors/clients first. Migration refuses an active collector, unknown database schemas, and any destination that already has database data; it never overwrites or merges histories. A dry run validates and reports counts without creating the destination. Choose the old instance's `stonebridge/` directory or a custom external data directory you previously selected.

The default destination is `INSTANCE/voxelscope/`; `--index-dir DIR` selects another destination. World identities remain unchanged, so moving/replacing the world still requires refreshing labels/indexes. If a migration is interrupted by a crash, inspect its `.migration-lock` and any partial destination before retrying; do not remove a lock while a migration is running.

## Use with an assistant

Give the assistant access to the companion tools and your instance directory. Start with `status` and `players`, then request a specific block, filtered network search, or selected field. No AI account, API key, or model is built into the mod. It does not upload observations anywhere; your chosen assistant/tool determines what leaves your computer.

Prefer a short filtered query or local summary over repeatedly dumping inventories or scanning the entire base. A machine index records last-seen locations, not a live copy of the world.

```sh
python tools/bridge.py --instance "/path/to/instance" label "main reactor"
python tools/bridge.py --instance "/path/to/instance" inspect "main reactor"
python tools/bridge.py --instance "/path/to/instance" scan --chunk-radius 1
python tools/bridge.py --instance "/path/to/instance" find centrifuge
python tools/bridge.py --instance "/path/to/instance" me 100 64 -20 --filter minecraft:iron_ingot
```

Look at a block within six blocks before creating a label. With multiple players, use `label NAME --player PLAYER` or `scan --player PLAYER`. Add `--dimension NAMESPACE:ID` for block/network/entity queries outside the overworld. ME queries target an AE2 grid-connected block rather than a handheld terminal.

## Monitoring

Labels and monitoring share `INSTANCE/voxelscope/` by default. Custom storage must be selected consistently with `bridge.py --index-dir DIR` and `monitor.py --data-dir DIR`.

```sh
python tools/monitor.py --instance "/path/to/instance" discover "main reactor"
python tools/monitor.py --instance "/path/to/instance" add "reactor fuel" --label "main reactor" --field /mekanism_fission/fuel/amount_mb
python tools/monitor.py --instance "/path/to/instance" run --name "reactor fuel" --duration 120 --interval 5
python tools/monitor.py --instance "/path/to/instance" report --name "reactor fuel" --minutes 60
```

Collectors run for a finite duration and stop on Ctrl+C. Nothing installs an unattended service. Reports and profile lists work offline; use `--world` if the history contains multiple worlds. Thresholds create local events, not external notifications. Collection is observational and is not a reactor safety controller.

### State changes

Boolean fields such as a reactor's `active` flag are discovered automatically as states. Select a field explicitly to assign human-readable event labels:

```sh
python tools/monitor.py --instance "/path/to/instance" add "reactor state" --label "main reactor" --field /mekanism_fission/active --state-label "true=Reactor started" --state-label "false=Reactor stopped"
python tools/monitor.py --instance "/path/to/instance" run --name "reactor state" --duration 120 --interval 5
python tools/monitor.py --instance "/path/to/instance" report --name "reactor state"
```

Use `--kind state` for a selected integer signal or enum. State values support booleans, strings up to 128 characters, and signed 64-bit integers. State labels use `VALUE=TEXT`: VALUE is parsed as JSON when valid, otherwise as a string. Boolean `false`, integer `0`, and string `"false"` are distinct values. Generic block-state properties are strings; reactor activity fields are booleans. For a selected numeric saved-data signal, monitor `/value` with `--kind state` and label its actual values explicitly; the tool does not guess what zero/one means.

Reports retain the latest sampled state and count observed transitions; they do not calculate numeric rates or averages for states. The first reading establishes a baseline. Runs, restarts, gaps, pauses, missing values, and target/content changes establish new baselines instead of inventing transition events. Sampling can miss short pulses or changes that occur between polls. Events are local history only; no unattended monitoring or notifications are installed.

## Compatibility

| Component | Support |
| --- | --- |
| Minecraft / loader | 1.21.1 / NeoForge 21.1.233+, below 21.2 |
| Required third-party mods | None |
| AE2 | Optional, compiled/tested against 19.2.17; supported metadata range 19.2.17–19.x |
| Mekanism | Optional, compiled/tested against 10.7.19.85; metadata range 10.7.19–10.7.x |
| Mekanism Generators | Optional, same version range; needed only for reactor statistics |
| Other mods | Shared inventory/fluid/FE readers work when the provider exposes those capabilities |
| Other loaders / game versions | Not supported in this release |

Only the exact integration versions above have been tested. Modpack-specific changes and newer versions in the accepted ranges still need validation. Saved data cannot automatically explain every mod's internal fields or units. See [API and limits](docs/API.md).

## Develop

Set `JAVA_HOME` to a Java 21 JDK and use the wrapper. Dependencies come from Maven Central and ModMaven; no installed modpack is needed and no third-party mod JARs are bundled.

```sh
./gradlew build
python -m unittest discover -s tools -p 'test_*.py'
./gradlew runGameTestServer
./gradlew runGameTestServer -PpackIntegrations=true
./gradlew runGameTestServer -PpackIntegrations=true -PwithoutBridge=true
python tools/package_release.py
```

On Windows use `gradlew.bat` or `build-local.ps1`. Integrated tests run in the separate development `run/` directory. Run the removal test after integrated tests so it can reopen their fixture save. CI exercises base/integrated configurations. Build output is under `build/libs/`; packaging defaults to ignored `dist/`, or pass `--output DIR`.

Java changes require a Minecraft restart; `/reload` does not reload mod classes. Python changes can be used immediately. Use the small development instance for iteration.

See [contributing](CONTRIBUTING.md), [security](SECURITY.md), and [release notes](CHANGELOG.md). MIT licensed; the original NeoForge template license is retained in `TEMPLATE_LICENSE.txt`.
