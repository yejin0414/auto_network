"""HTTP input boundaries preserve existing responses and accepted input forms.

Real Handler methods run without sockets or a server. Storage is mocked except
for temporary SQLite fixtures; window callbacks and timers are mocked. The
successful report test reads only in-memory bytes.
"""
from __future__ import annotations

import copy
import io
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import quote, urlencode

from openpyxl import load_workbook

from nc.config import DEFAULTS
from nc.server import App, STORAGE_READ_ERROR, make_handler
from nc.store import Store


REPORT_ROUTES = ("/report", "/report.xlsx")
EXCEL_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SESSION_ERROR = {"error": "화면을 새로고침하세요(세션 만료)."}


class HttpInputSafety(unittest.TestCase):
    def setUp(self):
        self.cfg = Mock(spec=["get"])
        self.cfg.get.return_value = copy.deepcopy(DEFAULTS)
        self.cfg.get.return_value["site_name"] = "Synthetic HTTP Campus"
        self.run = {
            "id": 7, "started": 1700000000, "finished": 1700000010, "trigger": "manual",
            "summary": {"overall": "ok", "counts": {"ok": 0}, "total_devices": 0},
            "devices": {}, "report_context": None,
        }
        self.raw = Mock(return_value=None)
        self.store = Mock(spec=["get_run", "get_report_snapshot"])
        self.reset_reads()
        self.app = App(SimpleNamespace(cfg=self.cfg, store=self.store, demo=True), Path(__file__).parent)
        self.app.token = "synthetic-token_only-ASCII-123"
        self.watch = Mock(spec=["heartbeat", "bye"])
        self.app.watch = self.watch
        self.app.on_quit = Mock()
        self.handler_type = make_handler(self.app)
        timer_patch = patch("nc.server.threading.Timer")
        self.timer = timer_patch.start()
        self.addCleanup(timer_patch.stop)

    def reset_reads(self):
        self.store.reset_mock()
        self.store.get_run.side_effect = None
        self.store.get_run.return_value = self.run
        self.store.get_report_snapshot.side_effect = None
        self.store.get_report_snapshot.return_value = (self.run, self.raw)
        self.cfg.reset_mock()
        self.raw.reset_mock()

    def handler(self, route, query=None, *, token=None, host="localhost:8875"):
        handler = object.__new__(self.handler_type)
        handler.path = route + ("?" + urlencode(query) if query else "")
        handler.headers = {"Host": host, "Content-Length": "2"}
        if token is not None:
            handler.headers["X-NC-Token"] = token
        handler.rfile = Mock(spec=["read"])
        handler.rfile.read.return_value = b"{}"
        handler._send = Mock()
        return handler

    def request(self, method, route, query=None, **options):
        handler = self.handler(route, query, **options)
        getattr(handler, "do_" + method)()
        handler._send.assert_called_once()
        return handler._send.call_args.args, handler

    def assert_no_dispatch(self, handler):
        handler.rfile.read.assert_not_called()
        self.assertEqual(self.store.mock_calls, [])
        self.cfg.get.assert_not_called()
        self.assertEqual(self.watch.mock_calls, [])
        self.app.on_quit.assert_not_called()
        self.timer.assert_not_called()

    def assert_bad_report_id(self, value):
        # The existing API route is the response oracle, including Python's
        # version-specific ValueError wording; no new report error text is set.
        self.reset_reads()
        expected, _ = self.request("GET", "/api/run", {"id": value}, token=self.app.token)
        self.assertEqual(expected[0], 400)
        self.assertTrue(expected[1]["error"].startswith("요청 값 오류: "))
        with patch("nc.server.render") as html, patch("nc.excel.build_workbook") as excel:
            for route in REPORT_ROUTES:
                with self.subTest(route=route):
                    response, _ = self.request("GET", route, {"t": self.app.token, "id": value})
                    self.assertEqual(response[:2], expected[:2])
            html.assert_not_called()
            excel.assert_not_called()
        self.assertEqual(self.store.mock_calls, [])
        self.cfg.get.assert_not_called()

    def test_malformed_report_ids_match_existing_api_400(self):
        for value in ("not-a-number", "1.5", "1e2", "   "):
            with self.subTest(value=value):
                self.assert_bad_report_id(value)

    def test_report_integer_digit_limit_matches_existing_api_400(self):
        limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
        if not limit:
            self.skipTest("This Python runtime has no active integer string digit limit")
        self.assert_bad_report_id("9" * (limit + 1))

    def test_api_run_ids_keep_existing_int_compatibility(self):
        cases = ((None, None), ("", None), ("0", 0), ("-1", -1), ("+7", 7),
                 (" \t7\r\n", 7), ("００７", 7), ("٧", 7), ("1_0", 10), ("0007", 7))
        for text, expected in cases:
            with self.subTest(value=text):
                self.reset_reads()
                query = {} if text is None else {"id": text}
                response, _ = self.request("GET", "/api/run", query, token=self.app.token)
                self.assertEqual(response[:2], (200, self.run))
                self.store.get_run.assert_called_once_with(expected)
                self.store.get_report_snapshot.assert_not_called()

    def test_api_run_out_of_range_ids_return_400_before_storage(self):
        for value in (-(2 ** 63) - 1, 2 ** 63, -(10 ** 100), 10 ** 100):
            with self.subTest(value=value):
                self.reset_reads()
                response, handler = self.request("GET", "/api/run", {"id": str(value)}, token=self.app.token)
                self.assertEqual(response[0], 400)
                self.assertEqual(set(response[1]), {"error"})
                self.assertTrue(response[1]["error"].startswith("요청 값 오류: "))
                self.assert_no_dispatch(handler)
        for token in (None, "wrong-token", "한글"):
            with self.subTest(token=token):
                self.reset_reads()
                response, handler = self.request("GET", "/api/run", {"id": str(2 ** 63)}, token=token)
                self.assertEqual(response[:2], (403, SESSION_ERROR))
                self.assert_no_dispatch(handler)

    def test_api_run_not_found_and_storage_errors_remain_404_and_503(self):
        outcomes = ((None, 404, {"error": "점검 기록이 없습니다."}),
                    (sqlite3.DatabaseError("sensitive synthetic detail"), 503, {"error": STORAGE_READ_ERROR}),
                    (OSError("sensitive synthetic detail"), 503, {"error": STORAGE_READ_ERROR}))
        for error, status, payload in outcomes:
            with self.subTest(outcome=type(error).__name__):
                self.reset_reads()
                if error is None:
                    self.store.get_run.return_value = None
                else:
                    self.store.get_run.side_effect = error
                response, _ = self.request("GET", "/api/run", {"id": "7"}, token=self.app.token)
                self.assertEqual(response[:2], (status, payload))
                self.store.get_run.assert_called_once_with(7)
                self.cfg.get.assert_not_called()

    def test_api_run_internal_overflow_is_not_reclassified_as_bad_id(self):
        error = OverflowError("synthetic internal failure")
        self.store.get_run.side_effect = error
        handler = self.handler("/api/run", {"id": "7"}, token=self.app.token)
        with self.assertRaises(OverflowError) as raised:
            handler.do_GET()
        self.assertIs(raised.exception, error)
        self.store.get_run.assert_called_once_with(7)
        handler._send.assert_not_called()

    def test_api_run_sqlite_boundaries_leave_data_and_subsequent_reads_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "synthetic.sqlite3")
            try:
                rid = store.save_run(self.run["started"], self.run["finished"], "manual", self.run, {}, None)
                expected_run = store.get_run(rid)
                before = tuple(store._db.iterdump())
                changes = store._db.total_changes
                cases = ((-(2 ** 63), 404), (2 ** 63 - 1, 404),
                         (-(2 ** 63) - 1, 400), (2 ** 63, 400),
                         (-(10 ** 100), 400), (10 ** 100, 400))
                with patch.object(self.app.engine, "store", store):
                    for value, status in cases:
                        with self.subTest(value=value):
                            response, _ = self.request("GET", "/api/run", {"id": str(value)}, token=self.app.token)
                            self.assertEqual(response[0], status)
                            if status == 404:
                                self.assertEqual(response[1], {"error": "점검 기록이 없습니다."})
                            else:
                                self.assertEqual(set(response[1]), {"error"})
                                self.assertTrue(response[1]["error"].startswith("요청 값 오류: "))
                            self.assertFalse(store._db.in_transaction)
                            response, _ = self.request("GET", "/api/run", {"id": str(rid)}, token=self.app.token)
                            self.assertEqual(response[:2], (200, expected_run))
                    for query in ({}, {"id": ""}, {"id": "0"}):
                        response, _ = self.request("GET", "/api/run", query, token=self.app.token)
                        self.assertEqual(response[:2], (200, expected_run))
                    self.assertFalse(store._db.in_transaction)
                    self.assertEqual(store._db.total_changes, changes)
                    self.assertEqual(tuple(store._db.iterdump()), before)
            finally:
                store._db.close()

    def test_report_ids_keep_existing_int_compatibility(self):
        cases = ((None, None), ("", None), ("0", 0), ("-1", -1), ("+7", 7),
                 (" \t7\r\n", 7), ("００７", 7), ("٧", 7), ("1_0", 10), ("0007", 7))
        with patch("nc.server.render", return_value="synthetic HTML"), \
                patch("nc.excel.build_workbook", return_value=b"synthetic XLSX"):
            for route in REPORT_ROUTES:
                for text, expected in cases:
                    with self.subTest(route=route, value=text):
                        self.reset_reads()
                        query = {"t": self.app.token}
                        if text is not None:
                            query["id"] = text
                        response, _ = self.request("GET", route, query)
                        self.assertEqual(response[0], 200)
                        reader = self.store.get_report_snapshot if route.endswith("xlsx") else self.store.get_run
                        other = self.store.get_run if route.endswith("xlsx") else self.store.get_report_snapshot
                        # In particular, 0 is passed unchanged: Store owns its
                        # existing latest-run fallback for that value.
                        reader.assert_called_once_with(expected)
                        other.assert_not_called()

    def test_successful_html_and_excel_downloads_keep_payloads_and_headers(self):
        query = {"t": self.app.token, "id": "7"}
        stamp = time.localtime(self.run["started"])
        html_name = time.strftime("netcheck_report_%Y%m%d_%H%M.html", stamp)
        for download in (False, True):
            with self.subTest(download=download):
                html_query = dict(query)
                if download:
                    html_query["download"] = "1"
                response, _ = self.request("GET", "/report", html_query)
                self.assertEqual(response[0], 200)
                self.assertIsInstance(response[1], str)
                self.assertIn("Synthetic HTTP Campus 무선망 점검 보고서", response[1])
                self.assertIn("회차 #7", response[1])
                self.assertEqual(response[2], "text/html; charset=utf-8")
                expected = {"Content-Disposition": f'attachment; filename="{html_name}"'} if download else {}
                self.assertEqual(response[3], expected)
        response, _ = self.request("GET", "/report.xlsx", query)
        self.assertEqual(response[0], 200)
        self.assertIsInstance(response[1], bytes)
        self.assertEqual(response[2], EXCEL_TYPE)
        excel_name = time.strftime("무선망점검_%Y%m%d_%H%M%S", stamp) + "_run7.xlsx"
        self.assertEqual(response[3], {
            "Content-Disposition": f'attachment; filename="netcheck.xlsx"; filename*=UTF-8\'\'{quote(excel_name)}',
        })
        workbook = load_workbook(io.BytesIO(response[1]), data_only=False)
        try:
            self.assertEqual(workbook["요약"]["A1"].value, "Synthetic HTTP Campus 무선망 점검 보고서")
            self.assertIn("회차 #7", workbook["요약"]["A2"].value)
        finally:
            workbook.close()

    def test_report_not_found_and_storage_errors_remain_404_and_503(self):
        outcomes = ((None, 404, {"error": "점검 기록이 없습니다."}),
                    (sqlite3.DatabaseError("sensitive synthetic detail"), 503, {"error": STORAGE_READ_ERROR}),
                    (OSError("sensitive synthetic detail"), 503, {"error": STORAGE_READ_ERROR}))
        with patch("nc.server.render") as html, patch("nc.excel.build_workbook") as excel:
            for route in REPORT_ROUTES:
                for error, status, payload in outcomes:
                    with self.subTest(route=route, outcome=type(error).__name__):
                        self.reset_reads()
                        reader = self.store.get_report_snapshot if route.endswith("xlsx") else self.store.get_run
                        if error is None:
                            reader.return_value = (None, self.raw) if route.endswith("xlsx") else None
                        else:
                            reader.side_effect = error
                        response, _ = self.request("GET", route, {"t": self.app.token, "id": "7"})
                        self.assertEqual(response[:2], (status, payload))
                        self.cfg.get.assert_not_called()
            html.assert_not_called()
            excel.assert_not_called()

    def test_report_internal_errors_are_not_reclassified_as_bad_ids(self):
        for route, renderer in (("/report", "nc.server.render"),
                                ("/report.xlsx", "nc.excel.build_workbook")):
            for stage, error_type in (("storage", ValueError), ("renderer", ValueError),
                                      ("renderer", OverflowError)):
                with self.subTest(route=route, stage=stage, error=error_type.__name__):
                    error = error_type("synthetic internal failure")
                    handler = self.handler(route, {"t": self.app.token, "id": "7"})
                    reader = "get_report_snapshot" if route.endswith("xlsx") else "get_run"
                    failure = (patch.object(self.store, reader, side_effect=error) if stage == "storage"
                               else patch(renderer, side_effect=error))
                    with failure, self.assertRaises(error_type) as raised:
                        handler.do_GET()
                    self.assertIs(raised.exception, error)
                    handler._send.assert_not_called()

    def test_sqlite_id_boundaries_keep_404_400_and_release_read_transactions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "synthetic.sqlite3")
            try:
                rid = store.save_run(self.run["started"], self.run["finished"], "manual", self.run, {}, None)
                changes = store._db.total_changes
                cases = ((-(2 ** 63), 404), (2 ** 63 - 1, 404),
                         (-(2 ** 63) - 1, 400), (2 ** 63, 400))
                with patch.object(self.app.engine, "store", store), \
                        patch("nc.server.render", return_value="synthetic HTML") as html, \
                        patch("nc.excel.build_workbook", return_value=b"synthetic XLSX") as excel:
                    for route in REPORT_ROUTES:
                        for value, expected in cases:
                            with self.subTest(route=route, value=value):
                                response, _ = self.request("GET", route, {"t": self.app.token, "id": str(value)})
                                self.assertEqual(response[0], expected)
                                if expected == 404:
                                    self.assertEqual(response[1], {"error": "점검 기록이 없습니다."})
                                else:
                                    self.assertEqual(set(response[1]), {"error"})
                                    self.assertTrue(response[1]["error"].startswith("요청 값 오류: "))
                                self.assertFalse(store._db.in_transaction)
                        renderer = excel if route.endswith("xlsx") else html
                        renderer.assert_not_called()
                        # The real Store preserves its pre-existing 0 -> latest
                        # behavior after both successful and failed ID lookups.
                        response, _ = self.request("GET", route, {"t": self.app.token, "id": "0"})
                        self.assertEqual(response[0], 200)
                        self.assertEqual(renderer.call_args.args[0]["id"], rid)
                        self.assertFalse(store._db.in_transaction)
                    self.assertEqual(store._db.total_changes, changes)
                    self.assertEqual(store._db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
            finally:
                store._db.close()

    def test_bad_header_tokens_return_403_before_dispatch_or_body_read(self):
        for token in ("é", "한글", self.app.token + "é", "wrong-token", "", None):
            for method, route in (("GET", "/api/run"), ("POST", "/api/heartbeat"), ("POST", "/api/quit")):
                with self.subTest(token=token, method=method, route=route):
                    # A valid query token does not replace the API header token.
                    response, handler = self.request(method, route, {"t": self.app.token, "id": "7"}, token=token)
                    self.assertEqual(response[:2], (403, SESSION_ERROR))
                    self.assert_no_dispatch(handler)

    def test_bad_report_query_tokens_return_403_before_storage(self):
        for token in ("é", "한글", self.app.token + "é", "wrong-token", "", None):
            for route in REPORT_ROUTES:
                with self.subTest(token=token, route=route):
                    query = {"id": "7"}
                    if token is not None:
                        query["t"] = token
                    # A valid API header does not replace a report query token.
                    response, handler = self.request("GET", route, query, token=self.app.token)
                    self.assertEqual(response[:2], (403, {"error": "권한 없음"}))
                    self.assert_no_dispatch(handler)

    def test_bad_bye_tokens_are_ignored_with_204_and_no_side_effects(self):
        cases = [(token, "localhost:8875") for token in ("é", "한글", self.app.token + "é", "wrong-token", "", None)]
        cases.append((self.app.token, "example.invalid:8875"))
        for token, host in cases:
            with self.subTest(token=token, host=host):
                query = {} if token is None else {"t": token}
                response, handler = self.request("POST", "/api/bye", query, token=self.app.token, host=host)
                self.assertEqual(response, (204, b"", "text/plain"))
                self.assert_no_dispatch(handler)

    def test_ascii_tokens_keep_api_and_bye_lifecycle_contracts(self):
        response, _ = self.request("GET", "/api/run", {"id": "7"}, token=self.app.token)
        self.assertEqual(response[:2], (200, self.run))
        self.store.get_run.assert_called_once_with(7)
        response, _ = self.request("POST", "/api/heartbeat", token=self.app.token)
        self.assertEqual(response[:2], (200, {"ok": True}))
        self.watch.heartbeat.assert_called_once_with()
        self.watch.bye.assert_not_called()
        self.watch.reset_mock()
        response, handler = self.request("POST", "/api/bye", {"t": self.app.token})
        self.assertEqual(response, (204, b"", "text/plain"))
        handler.rfile.read.assert_not_called()
        self.watch.bye.assert_called_once_with()
        self.watch.heartbeat.assert_not_called()
        self.app.on_quit.assert_not_called()
        self.timer.assert_not_called()
        self.watch.reset_mock()
        with patch.object(self.app, "watch", None):
            response, handler = self.request("POST", "/api/bye", {"t": self.app.token})
            self.assertEqual(response, (204, b"", "text/plain"))
            handler.rfile.read.assert_not_called()
        self.assertEqual(self.watch.mock_calls, [])
        response, _ = self.request("POST", "/api/quit", token=self.app.token)
        self.assertEqual(response[:2], (200, {"ok": True}))
        self.timer.assert_called_once_with(0.3, self.app.on_quit)
        self.timer.return_value.start.assert_called_once_with()
        self.app.on_quit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
