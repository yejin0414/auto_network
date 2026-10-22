"""Migration regressions: isolated state, safe configuration, and literal reports.

All devices and operating-system integrations are mocked. No scheduler starts.
"""
from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openpyxl import load_workbook

from nc import credentials, instance, wintask
from nc.config import ConfigError, ConfigStore, DEFAULTS, validate
from nc.credentials import Credential, CredentialStore
from nc.excel import build_workbook, report_filename, save_report
from nc.server import make_handler


class SafeConfiguration(unittest.TestCase):
    def test_new_install_requires_scheduling_opt_in(self):
        cfg = validate({})
        self.assertFalse(cfg['schedule']['enabled'])
        self.assertFalse(cfg['schedule']['background'])
        self.assertEqual(cfg['server']['port'], 8875)
        example = json.loads((Path(__file__).parents[1] / 'config/config.example.json').read_text(encoding='utf-8'))
        self.assertFalse(validate(example)['schedule']['enabled'])
        self.assertFalse(validate(example)['schedule']['background'])

    def test_nonfinite_out_of_range_and_fractional_thresholds_rejected(self):
        bad = [('cpu_warn', float('nan')), ('cpu_crit', float('inf')), ('mem_warn', -1),
               ('mem_crit', 101), ('client_ratio_pct', 101), ('client_min_total', -1),
               ('client_min_total', 1.5)]
        for key, value in bad:
            with self.subTest(key=key, value=value), self.assertRaises(ConfigError):
                validate({'thresholds': {key: value}})

    def test_additional_commands_validated_at_save(self):
        for command in ['reboot', 'show version\nreboot', 'display version; reboot']:
            with self.subTest(command=command), self.assertRaises(ConfigError):
                validate({'extra_commands': {'BB': [command]}})
        self.assertEqual(validate({'extra_commands': {'BB': [' display version ']}})
                         ['extra_commands']['BB'], ['display version'])

    def test_malformed_sections_rejected_without_internal_error(self):
        for cfg in [{'schedule': []}, {'thresholds': None}, {'devices': {}},
                    {'devices': [None]}, {'extra_commands': {'BB': 'show version'}}]:
            with self.subTest(cfg=cfg), self.assertRaises(ConfigError):
                validate(cfg)

    def test_string_false_cannot_enable_automatic_checks(self):
        for key in ('enabled', 'background', 'align_to_clock'):
            with self.subTest(key=key), self.assertRaises(ConfigError):
                validate({'schedule': {key: 'false'}})

    def test_failed_validation_preserves_configuration_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            cfg = ConfigStore(path)
            original = path.read_bytes()
            with self.assertRaises(ConfigError):
                cfg.save({'thresholds': {'cpu_warn': float('nan')}})
            self.assertEqual(path.read_bytes(), original)


class IsolatedCredentials(unittest.TestCase):
    def test_ephemeral_store_never_touches_os_keyring(self):
        with patch('nc.credentials._keyring', side_effect=AssertionError('OS keyring accessed')):
            store = CredentialStore(persistent=False)
            store.load_saved(['shared'])
            self.assertFalse(store.keyring_available)
            store.set('shared', Credential('demo', 'demo'), remember=False)
            self.assertEqual(store.get().username, 'demo')
            store.set('shared', Credential('demo', 'demo'), remember=True)
            store.forget_saved('shared')
            store.clear('shared')
            self.assertIsNone(store.get())

    def test_persistent_store_uses_only_independent_namespace(self):
        backend = Mock()
        backend.get_password.return_value = None
        with patch('nc.credentials._keyring', return_value=backend):
            store = CredentialStore()
            store.load_saved(['shared'])
            store.set('shared', Credential('synthetic', 'test-only'), remember=True)
            store.clear('shared')
        calls = backend.get_password.call_args_list + backend.set_password.call_args_list + backend.delete_password.call_args_list
        self.assertTrue(calls)
        self.assertTrue(all(c.args[0] == 'AutoNetwork.NetcheckCenter' for c in calls))


class IsolatedInstances(unittest.TestCase):
    def test_live_demo_and_upstream_state_paths_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA': tmp}):
            original = Path(tmp) / 'NetcheckCenter' / 'instance.json'
            original.parent.mkdir()
            original.write_text('upstream sentinel', encoding='utf-8')
            instance.write_instance(8875, 'live-test-token', 'test')
            instance.write_instance(8876, 'demo-test-token', 'test', demo=True)
            self.assertNotEqual(instance.instance_file(), instance.instance_file(True))
            self.assertTrue(instance.instance_file().exists())
            instance.clear_instance(demo=True)
            self.assertTrue(instance.instance_file().exists())
            self.assertFalse(instance.instance_file(True).exists())
            self.assertEqual(original.read_text(), 'upstream sentinel')
            instance.clear_instance()

    def test_upstream_instance_never_focused_or_terminated(self):
        ask = Mock()
        with patch('nc.instance._http', return_value={'app': 'netcheck', 'version': 'old'}) as http, \
                patch('nc.instance._read_instance') as read, patch('nc.instance.subprocess.run') as run:
            self.assertEqual(instance.take_over(8765, 'new', ask, Mock()), 'busy')
            self.assertEqual(http.call_count, 1)
            read.assert_not_called()
            run.assert_not_called()
            ask.assert_not_called()

    def test_demo_cannot_take_over_live_instance(self):
        with patch('nc.instance._http', return_value={'app': instance.APP_ID, 'demo': False, 'version': 'old'}), \
                patch('nc.instance._read_instance') as read:
            self.assertEqual(instance.take_over(8875, 'new', Mock(), Mock(), demo=True), 'busy')
            read.assert_not_called()

    def test_missing_token_never_forces_process_termination(self):
        with patch('nc.instance._http', return_value={'app': instance.APP_ID, 'version': 'old'}), \
                patch('nc.instance._read_instance', return_value={}), \
                patch('nc.instance.subprocess.run') as run:
            self.assertEqual(instance.take_over(8875, 'new', Mock(), Mock()), 'busy')
            run.assert_not_called()

    def test_authenticated_own_instance_can_be_replaced(self):
        with patch('nc.instance._http', side_effect=[{'app': instance.APP_ID, 'version': 'old'}, {'ok': True}]) as http, \
                patch('nc.instance._read_instance', return_value={'port': 8875, 'token': 'test-token'}), \
                patch('nc.instance.wait_port_free', return_value=True):
            self.assertEqual(instance.take_over(8875, 'new', lambda _: True, Mock()), 'ready')
            http.assert_any_call(8875, '/api/quit', 'test-token', {})

    def test_other_application_does_not_suppress_background_run(self):
        with patch('nc.instance._read_instance', return_value={'port': 8765}), \
                patch('nc.instance._http', return_value={'app': 'netcheck', 'version': 'old'}):
            self.assertIsNone(instance.running_instance())


class WindowsTaskErrors(unittest.TestCase):
    def test_task_deletion_failure_is_reported(self):
        query = subprocess.CompletedProcess([], 0, b'', b'')
        denied = subprocess.CompletedProcess([], 1, b'', b'access denied')
        with patch('nc.wintask.sys.platform', 'win32'), \
                patch('nc.wintask._schtasks', side_effect=[query, denied]) as task:
            result = wintask.sync({'enabled': False, 'background': False})
        self.assertFalse(result['ok'])
        self.assertTrue(result['registered'])
        self.assertIn('access denied', result['message'])
        self.assertTrue(all('AutoNetwork NetcheckCenter AutoCheck' in call.args for call in task.call_args_list))


class HttpInputBounds(unittest.TestCase):
    def test_invalid_content_lengths_fail_without_reading_request(self):
        handler_type = make_handler(SimpleNamespace(token='token'))
        for length in ['-1', 'not-an-integer']:
            with self.subTest(length=length):
                handler = object.__new__(handler_type)
                handler.path = '/api/config'
                handler.headers = {'Host': 'localhost:8875', 'X-NC-Token': 'token', 'Content-Length': length}
                handler.rfile = Mock()
                handler._send = Mock()
                handler.do_POST()
                self.assertEqual(handler._send.call_args.args[0], 400)
                handler.rfile.read.assert_not_called()


class ExcelDataIntegrity(unittest.TestCase):
    def run_data(self):
        dev = {'id': 'wlc-test', 'name': '=1+1', 'host': '192.0.2.1', 'role': 'WLC', 'status': 'unknown',
               'connected': True, 'metrics': {}, 'checks': [], 'issues': 0,
               'commands': [{'cmd_id': 'version', 'label': 'version', 'command': 'show version', 'ok': True}]}
        return {'id': 1, 'started': 1700000000.0, 'trigger': 'manual', 'summary': {'overall': 'unknown', 'counts': {}},
                'devices': {'wlc-test': dev}}

    def workbook(self, run):
        return load_workbook(io.BytesIO(build_workbook(run, '=1+1', DEFAULTS['thresholds'],
                                                      lambda *_: {'output': '=1+1'})))

    def test_device_and_raw_output_are_literal_text_not_formulas(self):
        wb = self.workbook(self.run_data())
        for cell in [wb['요약']['A1'], wb['요약']['A2'], wb['요약']['B5'], wb['원본 출력']['E5']]:
            self.assertEqual(cell.data_type, 's')
            self.assertTrue(cell.value.startswith('='))
        self.assertFalse(any(cell.data_type == 'f' for sheet in wb for row in sheet for cell in row))

    def test_missing_controller_metrics_are_unknown(self):
        wb = self.workbook(self.run_data())
        self.assertEqual(wb['컨트롤러 CPU·메모리']['L5'].value, '확인 불가')

    def test_missing_backbone_slot_metric_is_unknown(self):
        run = self.run_data()
        dev = run['devices']['wlc-test']
        dev['role'] = 'BB'
        dev['metrics'] = {'cpu_detail': {'slots': [{'slot': '1', '1m': 10}]}}
        wb = self.workbook(run)
        self.assertEqual(wb['백본 CPU·메모리']['K5'].value, '확인 불가')

    def test_two_runs_in_same_second_preserve_both_report_files(self):
        first = self.run_data()
        second = copy.deepcopy(first)
        second['id'] = 2
        self.assertNotEqual(report_filename(first), report_filename(second))
        with tempfile.TemporaryDirectory() as tmp:
            for run in [first, second]:
                save_report(run, 'synthetic', DEFAULTS['thresholds'], lambda *_: None, Path(tmp), 30)
            self.assertEqual(len(list(Path(tmp).glob('*.xlsx'))), 2)
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])


class CheckOnceExitStatus(unittest.TestCase):
    def test_failed_run_exits_nonzero_and_does_not_return_older_run(self):
        import app
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(app, 'base_dirs', return_value=(Path(tmp), Path(tmp))), \
                patch.object(app, 'CredentialStore'), patch.object(app, 'ConfigStore'), \
                patch.object(app, 'NetmikoDriver'), patch.object(app, 'Store') as store, \
                patch.object(app, 'Engine') as engine, patch.object(app, 'RotatingFileHandler'), \
                patch.object(app.logging, 'basicConfig'), patch.object(app.sys, 'argv', ['app.py', '--check-once']), \
                patch('sys.stdout', new_callable=io.StringIO) as stdout:
            engine.return_value.run_blocking.return_value = None
            self.assertEqual(app.main(), 1)
            store.return_value.get_run.assert_not_called()
            self.assertIn('점검 실패', stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
