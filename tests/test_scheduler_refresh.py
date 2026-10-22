"""In-process schedule changes use fresh settings after wake, without real waits."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nc.engine import Engine, next_slot


# Keep calendar alignment safely inside the Windows timestamp range in every timezone.
BASE = 1_700_000_000


class SchedulerRefresh(unittest.TestCase):
    def setUp(self):
        self.config = {
            "schedule": {"enabled": True, "interval_minutes": 60, "align_to_clock": False},
            "devices": [{"id": "synthetic", "enabled": True}],
        }
        self.engine = Engine(SimpleNamespace(get=lambda: copy.deepcopy(self.config)), Mock(), Mock(), Mock(), demo=True)
        self.engine._last_auto_start = BASE + 1000
        self.engine.start_check = Mock(return_value=True)

    def step(self, after_wait=None, now=BASE + 1100):
        with patch("nc.engine.time.time", return_value=now), \
                patch.object(self.engine._wake, "wait", side_effect=after_wait or (lambda _: False)), \
                patch("nc.engine.time.sleep"):
            self.engine._scheduler_step()

    def test_interval_saved_while_waiting_applies_on_next_step(self):
        def changed(_):
            self.config["schedule"]["interval_minutes"] = 30
            self.engine.reschedule()
        self.step(changed)
        self.step()
        self.assertEqual(self.engine.next_run, BASE + 2800)
        self.engine.start_check.assert_not_called()

    def test_alignment_saved_while_waiting_applies_on_next_step(self):
        def changed(_):
            self.config["schedule"].update(interval_minutes=30, align_to_clock=True)
            self.engine.reschedule()
        self.step(changed)
        self.step()
        self.assertEqual(self.engine.next_run, next_slot(BASE + 1100, 30, True, BASE + 1000))

    def test_disable_during_wait_prevents_due_check(self):
        def disabled(_):
            self.config["schedule"]["enabled"] = False
            self.engine.reschedule()
        self.step(disabled)
        self.step(now=BASE + 5000)
        self.assertIsNone(self.engine.next_run)
        self.engine.start_check.assert_not_called()

    def test_multiple_saves_during_wait_use_final_interval(self):
        def changed(_):
            for minutes in (15, 45, 10, 30):
                self.config["schedule"]["interval_minutes"] = minutes
                self.engine.reschedule()
        self.step(changed)
        self.step()
        self.assertEqual(self.engine.next_run, BASE + 2800)

    def test_change_while_wake_is_cleared_is_not_lost(self):
        self.engine.next_run = BASE + 4600
        self.engine._schedule_signature = (True, 60, False, True)
        clear = self.engine._wake.clear
        def change_and_clear():
            self.config["schedule"]["interval_minutes"] = 30
            self.engine.reschedule()
            clear()
        with patch.object(self.engine._wake, "clear", side_effect=change_and_clear):
            self.step()
        self.assertEqual(self.engine.next_run, BASE + 2800)

    def test_change_after_snapshot_defers_due_check(self):
        def clock():
            self.config["schedule"]["enabled"] = False
            self.engine.reschedule()
            return BASE + 5000
        with patch("nc.engine.time.time", side_effect=clock), patch("nc.engine.time.sleep"):
            self.engine._scheduler_step()
        self.engine.start_check.assert_not_called()
        self.step(now=BASE + 5000)
        self.assertIsNone(self.engine.next_run)

    def test_no_enabled_devices_does_not_start_empty_auto_run(self):
        self.config["devices"][0]["enabled"] = False
        self.step(now=BASE + 5000)
        self.assertIsNone(self.engine.next_run)
        self.engine.start_check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
