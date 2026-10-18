import tempfile
import unittest
from pathlib import Path
from monitoring import MonitorStore, collect, discover


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = MonitorStore(Path(self.directory.name) / "monitor.sqlite3")
        self.profile = self.store.register("world", "tank", {"route": "block", "params": {}, "expected_id": "test:tank", "interval": 5,
            "metrics": [{"path": "/tank/amount_mb", "unit": "mB", "capacity_path": "/tank/capacity_mb", "below": 10, "above": 90}]})

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def sample(self, value, tick, second, session="one", contents="test:water", world="world", loaded=True):
        snapshot = {"id": "test:tank", "world_id": world, "session": session, "game_tick": tick,
                    "loaded": loaded, "observed_at": str(second), "tank": {"id": contents, "amount_mb": value, "capacity_mb": 100}}
        return self.store.record(self.profile, snapshot, "run", 5, second, second)

    def metric(self, now):
        return self.store.report("world", now=now)["profiles"][0]["metrics"][0]

    def test_rates_eta_and_lag_are_distinct(self):
        self.sample(20, 100, 100)
        self.sample(40, 150, 105)
        metric = self.metric(105)
        self.assertEqual(4, metric["change_per_real_second"])
        self.assertEqual(8, metric["change_per_game_second"])
        self.assertEqual(10, metric["observed_ticks_per_second"])
        self.assertEqual(7.5, metric["estimated_game_seconds_to_full"])
        self.assertEqual(30, metric["average"])

    def test_pauses_session_changes_and_unloaded_gaps_break_rates(self):
        self.sample(20, 100, 100)
        self.assertEqual("no_tick_progress", self.sample(20, 100, 105))
        self.sample(40, 150, 110)
        self.assertNotIn("delta", self.metric(110))
        self.sample(50, 250, 115)
        self.assertEqual(10, self.metric(115)["delta"])
        self.sample(60, 1, 120, session="two")
        self.assertNotIn("delta", self.metric(120))
        self.sample(0, 2, 125, session="two", loaded=False)
        self.sample(70, 100, 130, session="two")
        self.assertNotIn("delta", self.metric(130))

    def test_content_changes_and_large_gaps_break_rates(self):
        self.sample(20, 100, 100)
        self.sample(50, 200, 105, contents="test:lava")
        self.assertNotIn("delta", self.metric(105))
        self.sample(60, 1000, 150, contents="test:lava")
        self.assertNotIn("delta", self.metric(150))

    def test_thresholds_only_log_transitions_and_worlds_do_not_mix(self):
        self.sample(5, 100, 100)
        self.sample(4, 200, 105)
        self.sample(20, 300, 110)
        self.assertEqual(2, self.store.db.execute("SELECT count(*) FROM events WHERE kind='threshold'").fetchone()[0])
        self.assertEqual("world_changed", self.sample(90, 400, 115, world="other"))
        self.assertEqual(3, self.store.db.execute("SELECT count(*) FROM samples").fetchone()[0])

    def test_big_integer_deltas_remain_exact_and_staleness_is_marked(self):
        big = 2 ** 60
        self.sample(big, 100, 100)
        self.sample(big + 1, 200, 105)
        metric = self.metric(130)
        self.assertEqual(big + 1, metric["latest"])
        self.assertEqual(1, metric["delta"])
        self.assertTrue(metric["stale"])

    def test_discovery_escapes_keys_and_excludes_boolean_numbers(self):
        result = discover({"x": 1, "game_tick": 5, "active": True, "energy": {"stored_fe": 10, "capacity_fe": 20}, "a/b": {"~": 3}})
        fields = {f["path"]: f for f in result["fields"]}
        self.assertFalse(fields["/active"]["monitorable"])
        self.assertFalse(fields["/x"]["monitorable"])
        self.assertEqual("/energy/capacity_fe", fields["/energy/stored_fe"]["capacity_path"])
        self.assertIn("/a~1b/~0", fields)

    def test_collector_lease_prevents_duplicate_collectors_and_can_release(self):
        self.store.acquire("first", 60)
        with self.assertRaises(ValueError):
            self.store.acquire("second", 60)
        self.store.release("first")
        self.store.acquire("second", 60)
        self.store.release("second")

    def test_world_change_stops_collector_and_releases_lease(self):
        result = collect(self.store, [self.profile], lambda route, params: {
            "world_id": "another_world", "session": "two", "game_tick": 1}, duration=1, interval=1)
        self.assertEqual("world_changed", result["stopped"])
        self.assertEqual(0, self.store.db.execute("SELECT count(*) FROM samples").fetchone()[0])
        self.assertEqual(0, self.store.db.execute("SELECT count(*) FROM leases").fetchone()[0])
