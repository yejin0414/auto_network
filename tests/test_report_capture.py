"""A running check keeps its own reporting settings when the UI saves new ones."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from nc.config import ConfigStore
from nc.credentials import Credential, CredentialStore
from nc.demo import DemoWorld
from nc.engine import Engine
from nc.store import Store


class ReportSettingsCapture(unittest.TestCase):
    def test_settings_changed_during_collection_do_not_rewrite_run_or_autosave(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cfg = ConfigStore(root / "config.json")
            before = cfg.save({
                "site_name": "점검 시작 사업장",
                "devices": [{"id": "bb1", "name": "Demo BB", "role": "BB", "host": "192.0.2.1"}],
                "report": {"excel_auto": True, "notify": False},
                "schedule": {"enabled": False, "background": False},
            })
            creds = CredentialStore(persistent=False)
            creds.set("shared", Credential("demo", "demo"), remember=False)
            world = DemoWorld(speed=0)
            world.devices_provider = lambda: before["devices"]
            store = Store(root / "history.sqlite3")
            try:
                engine = Engine(cfg, store, creds, world, demo=True)
                engine.reports_dir = root / "reports"
                original_begin = world.begin_run

                def change_settings_after_capture(ts):
                    original_begin(ts)
                    changed = cfg.get()
                    changed["site_name"] = "점검 도중 변경 사업장"
                    changed["thresholds"].update(cpu_warn=1, cpu_crit=2, mem_warn=1, mem_crit=2)
                    cfg.save(changed)

                world.begin_run = change_settings_after_capture
                with patch("socket.create_connection", side_effect=AssertionError("Demo must not connect")):
                    run_id = engine.run_blocking()
                self.assertIsNotNone(run_id, engine.last_error)
                run = store.get_run(run_id)
                self.assertEqual(run["report_context"]["site_name"], before["site_name"])
                self.assertEqual(run["report_context"]["thresholds"], before["thresholds"])
                self.assertEqual(cfg.get()["thresholds"]["cpu_crit"], 2)
                cpu = next(c for c in run["devices"]["bb1"]["checks"] if c["key"] == "cpu")
                self.assertEqual(cpu["level"], "ok")
                with open(engine.last_report, "rb") as file:
                    workbook = load_workbook(file)
                    self.assertIn(before["site_name"], workbook["요약"]["A1"].value)
                    self.assertEqual(workbook["백본 CPU·메모리"]["K5"].value, "정상")
                    workbook.close()
            finally:
                store._db.close()


if __name__ == "__main__":
    unittest.main()
