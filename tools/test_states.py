import json
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest
from monitoring import MonitorStore


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MonitorStore(Path(self.temp.name) / "monitor.sqlite3")
        self.profile = self.store.register("world", "reactor", {"route": "block", "params": {},
            "metrics": [{"path": "/active", "kind": "state", "state_labels": {"false": "Reactor stopped", "true": "Reactor started"}}]})

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def record(self, value, tick, second, session="one", run="run", **extra):
        return self.store.record(self.profile, {"world_id": "world", "session": session, "game_tick": tick,
            "observed_at": str(second), "active": value, **extra}, run, 5, second, second)

    def events(self):
        return [json.loads(r[0]) for r in self.store.db.execute("SELECT detail FROM events WHERE kind='state_change' ORDER BY id")]

    def test_initial_state_is_baseline_and_only_changes_emit_events(self):
        self.record(True, 100, 100)
        self.record(True, 200, 105)
        self.assertEqual([], self.events())
        self.record(False, 300, 110)
        self.record(False, 400, 115)
        self.assertEqual([{"path": "/active", "previous": True, "value": False, "label": "Reactor stopped"}], self.events())
        report = self.store.report("world", now=115)["profiles"][0]["metrics"][0]
        self.assertIs(report["latest"], False)
        self.assertEqual(1, report["observed_transitions"])
        self.assertEqual(100, report["same_state_observed_for_game_ticks"])
        self.assertEqual("Reactor stopped", report["label"])
        for key in ("average", "delta", "change_per_tick", "fill_percent"):
            self.assertNotIn(key, report)

    def test_missing_pause_unload_session_run_and_sampling_gaps_reset_baselines(self):
        self.record(True, 100, 100)
        self.record(None, 200, 105)
        self.record(False, 300, 110)
        self.record(True, 300, 115)  # no tick progress
        self.record(True, 400, 120)
        self.record(False, 500, 125, loaded=False)
        self.record(False, 600, 130)
        self.record(True, 1, 135, session="two")
        self.record(False, 101, 140, session="two", run="other")
        self.record(True, 1001, 190, session="two", run="other")
        self.assertEqual([], self.events())

    def test_short_string_and_explicit_integer_states_keep_types(self):
        self.record("running", 100, 100)
        self.record("stopped", 200, 105)
        self.record(0, 300, 110)
        self.assertEqual("stopped", self.events()[0]["value"])
        self.assertEqual(0, self.events()[1]["value"])
        self.assertEqual("fields_missing", self.record("x" * 129, 400, 115))

    def test_state_fields_reject_thresholds_and_configuration_change_resets(self):
        with self.assertRaises(ValueError):
            self.store.register("world", "bad", {"route": "block", "params": {},
                "metrics": [{"path": "/active", "kind": "state", "above": 0}]})
        self.record(True, 100, 100)
        config = self.profile["config"]
        config["metrics"][0]["state_labels"] = {"false": "Changed label"}
        self.profile = self.store.register("world", "reactor", config)
        self.record(False, 200, 105)
        self.assertEqual([], self.events())

    def test_cli_configures_boolean_state_and_explicit_integer_signal(self):
        import monitor
        data = str(Path(self.temp.name) / "cli")
        observation = {"world_id": "world", "session": "one", "game_tick": 1, "active": False, "value": 0}
        cases = [(["--field", "/active", "--state-label", "false=Reactor stopped"], "state"),
                 (["--field", "/value", "--kind", "state", "--state-label", "0=Alarm cleared"], "state")]
        for extra, kind in cases:
            output = io.StringIO()
            args = ["monitor.py", "--data-dir", data, "add", "test", "--params", "{}", *extra]
            with patch("sys.argv", args), patch("monitor.query", return_value=observation), redirect_stdout(output):
                self.assertEqual(0, monitor.main())
            self.assertEqual(kind, json.loads(output.getvalue())["fields"][0]["kind"])
