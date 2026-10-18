import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bridge import indexed_query, query


class ClientTests(unittest.TestCase):
    def test_connection_must_stay_local(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "voxelscope"
            runtime.mkdir()
            for url in ("https://127.0.0.1:1234", "http://example.com", "http://user@127.0.0.1"):
                (runtime / "connection.json").write_text(json.dumps({"url": url}))
                with self.assertRaises(ValueError):
                    query(root, "status", {})

    def test_multiplayer_label_requires_selection_and_uses_selected_target(self):
        with tempfile.TemporaryDirectory() as directory:
            players = [{"name": name, "uuid": name + "-uuid", "dimension": "test:dim",
                        "target": {"id": "test:block", "x": x, "y": 64, "z": 0}}
                       for name, x in (("alex", 1), ("steve", 2))]
            def read(instance, route, args):
                return {"world_id": "world", "players": players} if route == "players" else {"world_id": "world"}
            with patch("bridge.query", read):
                result = indexed_query(directory, "label", {"name": "machine"})
                self.assertEqual("select_one_player", result["error"])
                result = indexed_query(directory, "label", {"name": "machine", "player": "steve"})
                self.assertEqual(2, result["block"]["x"])
