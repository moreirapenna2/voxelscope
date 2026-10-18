# Contributing

Use Java 21, Python 3.10+, and the Gradle wrapper. Follow `AGENTS.md` for observation-only design constraints.

Run the build, Python tests, base GameTests, and integrated GameTests before proposing a change. New adapters should use typed APIs, remain optional, label units explicitly, bound work/output, and avoid setters, transfers, crafting, chunk loading, or save persistence. Keep third-party classes behind presence checks and separate classes so missing optional modules cannot break core inspection.

Bug reports should include Minecraft/NeoForge/VoxelScope versions, relevant mod versions, a minimal query and redacted error, and whether the target chunk was loaded. Exclude tokens, connection files, databases, saves, and personal filesystem paths. Prefer a small reproduction over a full world upload.

Compatibility claims must distinguish a tested version from an accepted version range. Do not claim all-mod or all-loader support from a successful build.
