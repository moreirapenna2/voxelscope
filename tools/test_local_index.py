import tempfile
from pathlib import Path
import unittest
from local_index import Index


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.index = Index(Path(self.directory.name) / "index.sqlite3")

    def tearDown(self):
        self.index.close()
        self.directory.cleanup()

    def test_world_separation_and_complete_chunk_replacement(self):
        rows = [{"x": -1, "y": 64, "z": 0, "id": "test:machine"}]
        self.index.record_chunk("world_a", "minecraft:overworld", -1, 0, rows, "now", "session", True)
        self.index.record_chunk("world_b", "minecraft:overworld", -1, 0, rows, "now", "session", True)
        self.index.record_chunk("world_a", "minecraft:overworld", -1, 0, [], "later", "session", False)
        self.assertEqual(1, len(self.index.find("world_a", "machine")["matches"]))
        self.index.record_chunk("world_a", "minecraft:overworld", -1, 0, [], "later", "session", True)
        self.assertEqual([], self.index.find("world_a", "machine")["matches"])
        self.assertEqual(1, len(self.index.find("world_b", "machine")["matches"]))

    def test_bad_chunk_rolls_back_and_labels_are_per_world(self):
        row = {"x": 1, "y": 64, "z": 0, "id": "test:machine"}
        self.index.record_chunk("a", "minecraft:overworld", 0, 0, [row], "now", "s", True)
        with self.assertRaises(ValueError):
            self.index.record_chunk("a", "minecraft:overworld", 0, 0, [dict(row, x=100)], "later", "s", True)
        self.assertEqual(1, len(self.index.find("a", "machine")["matches"]))
        self.index.label("a", "main reactor", dict(row, dimension="minecraft:overworld"))
        self.assertEqual(1, self.index.lookup("a", "main reactor")["x"])
        with self.assertRaises(ValueError):
            self.index.lookup("b", "main reactor")


if __name__ == "__main__":
    unittest.main()
