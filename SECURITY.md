# Security

VoxelScope is a localhost observation interface, not a remote administration service. It requires a bearer token, rejects browser origins, bounds queries, and has no game mutation endpoints. Anyone who can read the instance token and reach the same machine's listener can inspect exposed world information. Keep the instance directory private and do not forward the port or publish credentials.

The mod itself sends nothing to external services. Companion clients and assistants can read world/player information; choose and configure those tools accordingly. Never attach token.txt, connection.json, history databases, or world saves to public issues.

For security reports, use GitHub's private vulnerability reporting if enabled. Otherwise open a minimal issue asking for a private reporting channel without posting an exploit or credentials. No security audit is claimed.
