"""Machine locations and labels live here, outside Minecraft world saves."""
import sqlite3


class Index:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS machines (
                world TEXT, dimension TEXT, x INTEGER, y INTEGER, z INTEGER,
                id TEXT NOT NULL, observed_at TEXT NOT NULL, session TEXT NOT NULL,
                PRIMARY KEY(world,dimension,x,y,z));
            CREATE INDEX IF NOT EXISTS machine_type ON machines(world,id);
            CREATE TABLE IF NOT EXISTS labels (
                world TEXT, name TEXT, dimension TEXT, x INTEGER, y INTEGER, z INTEGER,
                expected_id TEXT NOT NULL, PRIMARY KEY(world,name));
        """)

    def close(self):
        self.db.close()

    def record_chunk(self, world, dimension, cx, cz, machines, observed_at, session, complete):
        with self.db:
            if complete:
                self.db.execute("DELETE FROM machines WHERE world=? AND dimension=? AND x>=? AND x<? AND z>=? AND z<?",
                                (world, dimension, cx * 16, cx * 16 + 16, cz * 16, cz * 16 + 16))
            for row in machines:
                # Validate remote coordinates before letting a chunk snapshot replace index rows.
                if row["x"] // 16 != cx or row["z"] // 16 != cz:
                    raise ValueError("Machine outside requested chunk")
                self.db.execute("INSERT OR REPLACE INTO machines VALUES (?,?,?,?,?,?,?,?)",
                                (world, dimension, row["x"], row["y"], row["z"], row["id"], observed_at, session))

    def find(self, world, text, limit=20):
        # instr treats wildcard characters literally.
        cursor = self.db.execute("""SELECT dimension,x,y,z,id,observed_at,session FROM machines
            WHERE world=? AND instr(id,?)>0 ORDER BY dimension,x,y,z LIMIT ?""", (world, text, limit + 1))
        rows = [dict(row) for row in cursor]
        return {"matches": rows[:limit], "truncated": len(rows) > limit,
                "freshness": "last_seen; re-inspect for live state", "world_id": world}

    def label(self, world, name, block):
        if not name.strip() or len(name) > 80:
            raise ValueError("Label must contain 1-80 characters")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?,?)",
                            (world, name, block["dimension"], block["x"], block["y"], block["z"], block["id"]))

    def lookup(self, world, name):
        row = self.db.execute("SELECT * FROM labels WHERE world=? AND name=?", (world, name)).fetchone()
        if row is None:
            raise ValueError("Unknown label in this world")
        return dict(row)
