"""자동 점검: 프로그램 안 스케줄러, 멈춘 점검 처리, 창을 닫아도 점검(작업 스케줄러용 --auto-check)."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import nc.engine as E
from nc.config import ConfigStore
from nc.credentials import Credential, CredentialStore
from nc.demo import DEMO_CONFIG, DemoWorld
from nc.store import Store
from nc.wintask import build_xml

ROOT = Path(__file__).resolve().parent.parent
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def make_engine(tmp: Path, schedule: dict, speed: float = 0.0):
    cfg_d = json.loads(json.dumps(DEMO_CONFIG))
    cfg_d["schedule"] = schedule
    (tmp / "config.json").write_text(json.dumps(cfg_d, ensure_ascii=False), encoding="utf-8")
    cfg = ConfigStore(tmp / "config.json")
    creds = CredentialStore(persistent=False)
    creds.set("shared", Credential("u", "p"), remember=False)
    drv = DemoWorld(speed=speed)
    drv.devices_provider = lambda: cfg.get()["devices"]
    eng = E.Engine(cfg, Store(tmp / "db.sqlite3"), creds, drv, demo=True)
    eng.demo_quiet = True
    return eng


class Scheduler(unittest.TestCase):
    def test_runs_repeatedly(self):
        orig = E.next_slot
        E.next_slot = lambda now, i, a, last: (now + 1) if last is None else last + 2
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
                eng = make_engine(Path(t), {"enabled": True, "interval_minutes": 5, "align_to_clock": False})
                eng.start_scheduler()
                time.sleep(8)
                eng.stop()
                runs = eng.store.list_runs(50)
                self.assertGreaterEqual(len(runs), 3)
                self.assertTrue(all(r["trigger"] == "auto" for r in runs))
        finally:
            E.next_slot = orig

    def test_stuck_run_does_not_block_next(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            eng = make_engine(Path(t), {"enabled": True, "interval_minutes": 5, "align_to_clock": False})
            gate = threading.Event()
            real = eng.driver.open

            def slow_open(*a, **k):
                gate.wait(20)
                return real(*a, **k)

            eng.driver.open = slow_open
            self.assertTrue(eng.start_check("auto"))
            time.sleep(0.3)
            self.assertFalse(eng.start_check("auto"))      # 진행 중이면 건너뜀
            self.assertFalse(eng.abandon_stuck_run())       # 아직 기준 시간 전
            eng.max_run_seconds = 0
            self.assertTrue(eng.abandon_stuck_run())        # 멈춘 점검으로 처리
            self.assertIn("중단 처리", eng.last_error)
            eng.driver.open = real
            rid = eng.run_blocking("auto")                  # 다음 점검은 정상 진행
            self.assertIsNotNone(rid)
            gate.set()
            time.sleep(1.5)
            self.assertEqual(len(eng.store.list_runs(50)), 1)  # 멈췄던 점검 결과는 버림
            self.assertFalse(eng.running)

    def test_next_slot_aligned(self):
        now = datetime(2026, 10, 22, 15, 36, 10).timestamp()
        self.assertEqual(datetime.fromtimestamp(E.next_slot(now, 60, True, None)), datetime(2026, 10, 22, 16, 0))
        self.assertEqual(datetime.fromtimestamp(E.next_slot(now, 30, True, None)), datetime(2026, 10, 22, 16, 0))


class TaskXml(unittest.TestCase):
    def test_xml(self):
        x = build_xml(60, True, r"C:\도구\NetcheckCenter\NetcheckCenter.exe", "--auto-check", r"C:\도구\NetcheckCenter",
                      now=datetime(2026, 10, 22, 15, 36))
        root = ET.fromstring(x.replace('encoding="UTF-16"', ""))
        g = lambda p: root.find(p, NS).text
        self.assertEqual(g(".//t:Repetition/t:Interval"), "PT60M")
        self.assertEqual(g(".//t:StartBoundary"), "2026-10-22T00:00:00")
        self.assertEqual(g(".//t:Exec/t:Command"), r"C:\도구\NetcheckCenter\NetcheckCenter.exe")
        self.assertEqual(g(".//t:Exec/t:Arguments"), "--auto-check")
        self.assertEqual(g(".//t:StartWhenAvailable"), "true")
        self.assertEqual(g(".//t:MultipleInstancesPolicy"), "IgnoreNew")
        self.assertEqual(g(".//t:LogonType"), "InteractiveToken")

    def test_xml_not_aligned(self):
        x = build_xml(30, False, "a.exe", '"b c" --auto-check', "d", now=datetime(2026, 10, 22, 15, 36))
        root = ET.fromstring(x.replace('encoding="UTF-16"', ""))
        self.assertEqual(root.find(".//t:StartBoundary", NS).text, "2026-10-22T16:06:00")
        self.assertEqual(root.find(".//t:Exec/t:Arguments", NS).text, '"b c" --auto-check')


class AutoCheckMode(unittest.TestCase):
    """작업 스케줄러가 실행하는 --auto-check: 창이 없으면 점검하고, 창이 켜져 있으면 바로 끝냄."""

    def _env(self, t):
        env = dict(os.environ, LOCALAPPDATA=str(Path(t) / "lad"), NC_NO_DIALOG="1", NC_ASSUME_YES="1", PYTHONUTF8="1")
        return env

    def test_runs_when_window_closed_and_skips_when_open(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            work = Path(t) / "app"
            import shutil
            shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "data", "data-demo", "dist", "build",
                                                                     "보고서", "보고서-demo", "release", "__pycache__", ".venv", ".pytest_cache"))
            env = self._env(t)
            db = work / "data-demo" / "netcheck.sqlite3"
            db.parent.mkdir()
            config = json.loads(json.dumps(DEMO_CONFIG))
            config["schedule"].update(enabled=True, background=True)
            config.setdefault("report", {})["notify"] = False
            (db.parent / "config.json").write_text(json.dumps(config), encoding="utf-8")
            # 1) 창 없음 → 점검 1회
            r = subprocess.run([sys.executable, str(work / "app.py"), "--demo", "--auto-check"], env=env,
                               capture_output=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-2000:])
            st = Store(db)
            n1 = len(st.list_runs(500))
            self.assertEqual(st.list_runs(1)[0]["trigger"], "auto")
            # 2) 프로그램 창(화면 서버)이 켜져 있으면 → 점검하지 않고 끝냄
            port = 18966
            gui = subprocess.Popen([sys.executable, str(work / "app.py"), "--demo", "--no-browser", "--port", str(port)],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                inst = Path(env["LOCALAPPDATA"]) / "AutoNetwork.NetcheckCenter" / "demo-instance.json"
                for _ in range(100):
                    if inst.exists():
                        break
                    time.sleep(0.2)
                time.sleep(1)
                n_before = len(Store(db).list_runs(500))
                r = subprocess.run([sys.executable, str(work / "app.py"), "--demo", "--auto-check"], env=env,
                                   capture_output=True, timeout=120)
                self.assertEqual(r.returncode, 0)
                self.assertEqual(len(Store(db).list_runs(500)), n_before)
                log = (work / "data-demo" / "netcheck.log").read_text(encoding="utf-8")
                self.assertIn("그쪽 자동 점검에 맡깁니다", log)
            finally:
                gui.terminate()
                gui.wait(10)
            self.assertGreater(n1, 0)


if __name__ == "__main__":
    unittest.main()


class WebMode(unittest.TestCase):
    """웹 버전(--web): 브라우저로 열고, 화면 신호가 없어도 계속 실행, ‘프로그램 끄기’로 종료."""

    def test_web_mode_keeps_running_and_quits(self):
        import shutil
        import urllib.request
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            work = Path(t) / "app"
            shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "data", "data-demo", "dist", "build",
                                                                     "보고서", "보고서-demo", "release", "__pycache__", ".venv", ".pytest_cache"))
            env = dict(os.environ, LOCALAPPDATA=str(Path(t) / "lad"), NC_NO_DIALOG="1", BROWSER="true", PYTHONUTF8="1")
            port = 18967
            p = subprocess.Popen([sys.executable, str(work / "app.py"), "--demo", "--web", "--port", str(port)], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                inst = Path(env["LOCALAPPDATA"]) / "AutoNetwork.NetcheckCenter" / "demo-instance.json"
                for _ in range(150):
                    if inst.exists():
                        break
                    time.sleep(0.2)
                tok = json.loads(inst.read_text(encoding="utf-8"))["token"]

                def call(path, body=None):
                    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                                 data=json.dumps(body).encode() if body is not None else None,
                                                 headers={"X-NC-Token": tok, "Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        return json.loads(r.read())

                self.assertTrue(call("/api/state")["web_mode"])
                time.sleep(3)
                self.assertIsNone(p.poll())          # 화면 신호 없어도 계속 실행
                call("/api/quit", {})
                p.wait(20)
                self.assertIsNotNone(p.poll())
            finally:
                if p.poll() is None:
                    p.kill()
                    p.wait(10)
