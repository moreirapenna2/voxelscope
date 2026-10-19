import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
import zipfile
from unittest.mock import patch
from diagnostics import diagnose
from local_index import Index
from migration import migrate
from monitoring import MonitorStore


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "old"
        self.source.mkdir()
        self.destination = self.root / "new"

    def tearDown(self):
        self.temp.cleanup()

    def fixtures(self):
        index = Index(self.source / "index.sqlite3")
        index.label("world", "reactor", {"dimension": "test:room", "x": 1, "y": 2, "z": 3, "id": "test:reactor"})
        index.close()
        store = MonitorStore(self.source / "monitor.sqlite3")
        profile = store.register("world", "fuel", {"route": "block", "params": {}, "metrics": [{"path": "/fuel"}]})
        store.record(profile, {"world_id": "world", "session": "one", "game_tick": 100, "fuel": 2 ** 60 + 1}, "oldrun", 5, 100, 100)
        store.close()
        (self.source / "token.txt").write_text("must-never-be-copied")
        (self.source / "connection.json").write_text("must-never-be-copied")

    def test_migration_preserves_labels_integer_history_and_source_bytes(self):
        self.fixtures()
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.source.iterdir()}
        plan = migrate(self.source, self.destination, dry_run=True)
        self.assertFalse(self.destination.exists())
        self.assertEqual(1, plan["databases"]["index.sqlite3"]["labels"])
        migrate(self.source, self.destination)
        self.assertFalse((self.destination / "token.txt").exists())
        self.assertFalse((self.destination / "connection.json").exists())
        index = Index(self.destination / "index.sqlite3")
        self.assertEqual(1, index.lookup("world", "reactor")["x"])
        index.close()
        store = MonitorStore(self.destination / "monitor.sqlite3")
        self.assertEqual(2 ** 60 + 1, store.report("world", now=100)["profiles"][0]["metrics"][0]["latest"])
        store.close()
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.source.iterdir()})
        with self.assertRaises(ValueError):
            migrate(self.source, self.destination)

    def test_migration_rejects_active_collector_corrupt_and_foreign_database(self):
        self.fixtures()
        store = MonitorStore(self.source / "monitor.sqlite3")
        store.acquire("busy", 60)
        with self.assertRaises(ValueError):
            migrate(self.source, self.destination)
        store.release("busy")
        store.close()
        with sqlite3.connect(self.source / "index.sqlite3") as db:
            db.execute("CREATE TABLE unexpected(secret TEXT)")
        with self.assertRaises(ValueError):
            migrate(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_doctor_offline_does_not_create_files_or_print_errors(self):
        def unavailable(route, params):
            raise FileNotFoundError("sensitive-path")
        result = diagnose(self.root, unavailable)
        self.assertEqual("no_runtime_files", result["api_connection"])
        self.assertNotIn("sensitive-path", json.dumps(result))
        self.assertEqual([self.source], list(self.root.iterdir()))

    def test_doctor_distinguishes_auth_pauses_invalid_and_unreachable(self):
        for error, expected in ((HTTPError("", 401, "secret", {}, None), "authentication_failed"),
                                (HTTPError("", 503, "secret", {}, None), "game_thread_unavailable_or_paused"),
                                (URLError("secret"), "unreachable"), (ValueError("secret"), "invalid_runtime_files")):
            def failed(route, params):
                raise error
            result = diagnose(self.root, failed)
            self.assertEqual(expected, result["api_connection"])
            self.assertNotIn("secret", json.dumps(result))

    def test_doctor_reads_jar_metadata_and_rejects_duplicate_installation(self):
        mods = self.root / "mods"
        mods.mkdir()
        def jar(name, mod):
            with zipfile.ZipFile(mods / name, "w") as archive:
                archive.writestr("META-INF/neoforge.mods.toml", '[[mods]]\nmodId="' + mod + '"\nversion="0.4.0"\n')
        jar("voxelscope-0.4.0.jar", "voxelscope")
        live = lambda route, params: {"name": "VoxelScope", "api_version": 1, "read_only": True, "bridge_version": "0.4.0"}
        self.assertEqual("ready", diagnose(self.root, live)["status"])
        jar("stoneblock-bridge-0.2.0.jar", "stonebridge")
        result = diagnose(self.root, live)
        self.assertEqual("needs_attention", result["status"])
        self.assertEqual("legacy_or_multiple_bridges", result["installation_issue"])

    def test_migration_copies_committed_wal_and_rolls_back_publish_failures(self):
        self.fixtures()
        writer = MonitorStore(self.source / "monitor.sqlite3")
        writer.register("second_world", "extra", {"route": "block", "params": {}, "metrics": [{"path": "/fuel"}]})
        self.assertTrue(Path(str(self.source / "monitor.sqlite3") + "-wal").exists())
        try:
            with patch("migration.shutil.copyfileobj", side_effect=OSError("test failure")):
                with self.assertRaises(OSError):
                    migrate(self.source, self.destination)
            self.assertEqual([], list(self.destination.iterdir()))
            migrate(self.source, self.destination)
            result = MonitorStore(self.destination / "monitor.sqlite3")
            self.assertIn("second_world", result.worlds())
            result.close()
        finally:
            writer.close()

    def test_corrupt_source_fails_without_creating_destination(self):
        (self.source / "index.sqlite3").write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            migrate(self.source, self.destination)
        self.assertFalse(self.destination.exists())
