# Changelog

## 0.4.0 — Setup and state monitoring

- Add credential-safe installation/connection diagnostics with `bridge.py doctor`.
- Add offline legacy database migration with dry runs, integrity/schema checks, WAL-aware backups, no overwrite, and no credential copying.
- Monitor boolean/string states and explicitly selected integer signals, with named local change events and baseline resets across availability gaps.
- Preserve existing numeric history and rates with an additive sample-kind schema upgrade.
- Advertise Matrix integration separately from the Generators module.

## 0.3.0 — VoxelScope public preview

- Provide a pack-independent Minecraft 1.21.1 NeoForge observation API.
- Use the VoxelScope namespace for the mod, artifacts, and runtime files.
- Resolve optional integrations from public Maven repositories instead of local modpack JARs.
- Support explicit instance paths and VOXELSCOPE_INSTANCE.
- Share default label/history storage and support selecting a player for labels/scans.
- Separate Mekanism Matrix inspection from the Generators module.
- Retain authenticated read-only API v1, generic discovery, local indexing, and bounded trend collection.
- Add public build/test workflow, installation/API/contribution/security documentation, and release packaging.

