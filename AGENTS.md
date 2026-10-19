# VoxelScope

Local read-only Minecraft observation API and companion tools.

- Never register gameplay content, persist data in saves, or mutate game state.
- Never force-load or generate chunks; check loaded status before inspection.
- Access game objects only on the server thread. Return detached JSON snapshots.
- Bound query work and output. No arbitrary reflection, commands, or full NBT dumps over HTTP.
- Bind to 127.0.0.1 only; authenticate all endpoints. Never log or commit tokens.
- Keep development/testing separate from real modpack instances and saves.
- Use Java 21 and the Gradle wrapper. Python tools require Python 3.10+, standard library only.
- Optional integrations must stay optional; verify with and without third-party mods.
- Do not commit runtime databases, worlds, personal paths, connection files, or credentials.
- Public PRs, releases, issues, commits, and documentation must describe product behavior, reproducible tests, and compatibility. Never include private user data, local installation/migration outcomes, personal world details, or session-specific development/verification status.
