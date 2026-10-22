"""Deterministic task synchronization tests; all OS operations are mocked."""
from __future__ import annotations

import copy
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nc.config import ConfigStore
from nc.schedule_sync import ScheduleSynchronizer
from nc.server import App
from nc import wintask


def result(schedule, ok=True):
    return {'ok': ok, 'registered': bool(schedule['enabled'] and schedule['background']),
            'supported': True, 'message': '' if ok else 'synthetic failure',
            'interval': schedule['interval_minutes']}


class Synchronization(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigStore(Path(self.tmp.name) / 'config.json')
        self.app = App(SimpleNamespace(cfg=self.cfg, reschedule=Mock()), Path(self.tmp.name))
        self.published = []
        self.terminal = threading.Condition()

    def save(self, enabled, interval=60, background=True):
        cfg = self.cfg.get()
        cfg['schedule'].update(enabled=enabled, background=background, interval_minutes=interval)
        return self.cfg.save(cfg)

    def publish(self, state, schedule):
        accepted = self.app.publish_background(state, schedule)
        if accepted:
            with self.terminal:
                self.published.append((copy.deepcopy(state), copy.deepcopy(schedule)))
                self.terminal.notify_all()
        return accepted

    def synchronizer(self, apply, **options):
        worker = ScheduleSynchronizer(lambda: self.cfg.get()['schedule'], apply, self.publish, **options)
        self.addCleanup(worker.close, 1)
        self.app.on_config_saved = worker.request
        return worker

    def await_terminal(self, predicate, count=1):
        with self.terminal:
            reached = self.terminal.wait_for(
                lambda: sum(not state.get('pending') and predicate(state, schedule)
                            for state, schedule in self.published) >= count, timeout=5)
        self.assertTrue(reached, self.published)

    def test_serializes_and_coalesces_intervals_to_final_disable(self):
        entered, release = threading.Event(), threading.Event()
        calls, active = [], []
        def apply(schedule):
            active.append(1)
            self.assertEqual(len(active), 1)
            calls.append(copy.deepcopy(schedule))
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(5))
            active.pop()
            return result(schedule)
        self.save(True)
        worker = self.synchronizer(apply)
        self.addCleanup(release.set)
        worker.request()
        self.assertTrue(entered.wait(5))
        for enabled, interval in [(True, 30), (True, 15), (False, 15)]:
            saved = self.save(enabled, interval)
            worker.request(saved)
        self.assertTrue(self.app.background['pending'])
        self.assertFalse(self.app.background['registered'])
        release.set()
        self.await_terminal(lambda state, schedule: state['ok'] and not schedule['enabled'])
        self.assertTrue(worker.close(5))
        self.assertEqual([(c['enabled'], c['interval_minutes']) for c in calls], [(True, 60), (False, 15)])
        self.assertFalse(any(state.get('ok') and schedule['enabled'] for state, schedule in self.published))
        self.assertFalse(self.app.background['registered'])

    def test_reversed_old_callback_reads_latest_saved_schedule(self):
        calls = []
        old = self.save(True, 60)
        latest = self.save(False, 30)
        worker = self.synchronizer(lambda schedule: calls.append(copy.deepcopy(schedule)) or result(schedule))
        worker.request(latest)
        self.await_terminal(lambda state, _: state['ok'])
        worker.request(old)
        self.await_terminal(lambda state, _: state['ok'], count=2)
        self.assertTrue(worker.close(5))
        self.assertEqual(calls, [latest['schedule']])
        self.assertFalse(self.app.background['registered'])

    def test_changes_during_os_call_are_reread_even_before_callback_arrives(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def apply(schedule):
            calls.append(copy.deepcopy(schedule))
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(5))
            return result(schedule)
        old = self.save(True, 60)
        worker = self.synchronizer(apply)
        self.addCleanup(release.set)
        worker.request(old)
        self.assertTrue(entered.wait(5))
        self.save(True, 15)  # Save is authoritative, even if its callback is delayed.
        release.set()
        self.await_terminal(lambda state, _: state.get('interval') == 15)
        self.assertTrue(worker.close(5))
        self.assertEqual([s['interval_minutes'] for s in calls], [60, 15])
        self.assertFalse(any(state.get('ok') and state.get('interval') == 60 for state, _ in self.published))

    def test_os_exception_is_reported_and_retried(self):
        apply = Mock(side_effect=[RuntimeError('synthetic OS error'), result(self.cfg.get()['schedule'])])
        worker = self.synchronizer(apply, retry_delay=0)
        with self.assertLogs('netcheck', level='ERROR'):
            worker.request()
            self.await_terminal(lambda state, _: state['ok'])
        self.assertTrue(worker.close(5))
        self.assertEqual(apply.call_count, 2)
        failures = [state for state, _ in self.published if state.get('ok') is False]
        self.assertTrue(failures[0]['retrying'])
        self.assertIn('synthetic OS error', failures[0]['message'])

    def test_new_request_interrupts_failed_settings_retry_delay(self):
        self.save(True)
        calls = []
        def apply(schedule):
            calls.append(copy.deepcopy(schedule))
            return result(schedule, ok=not schedule['enabled'])
        worker = self.synchronizer(apply, retry_delay=600)
        worker.request()
        self.await_terminal(lambda state, _: state['ok'] is False)
        worker.request(self.save(False))
        self.await_terminal(lambda state, _: state['ok'])
        self.assertTrue(worker.close(5))
        self.assertEqual([s['enabled'] for s in calls], [True, False])

    def test_publish_exception_does_not_strand_later_settings(self):
        published_error = threading.Event()
        def publish(state, schedule):
            if state.get('ok') and schedule['enabled']:
                published_error.set()
                raise RuntimeError('synthetic presentation error')
            return self.publish(state, schedule)
        self.save(True)
        calls = []
        worker = ScheduleSynchronizer(lambda: self.cfg.get()['schedule'],
                                      lambda schedule: calls.append(schedule) or result(schedule), publish)
        self.addCleanup(worker.close, 1)
        with self.assertLogs('netcheck', level='ERROR'):
            worker.request()
            self.assertTrue(published_error.wait(5))
            worker.request(self.save(False))
            self.await_terminal(lambda state, _: state['ok'])
        self.assertTrue(worker.close(5))
        self.assertEqual([s['enabled'] for s in calls], [True, False])

    def test_shutdown_drains_latest_disable_after_inflight_registration(self):
        entered, release, closing = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def apply(schedule):
            calls.append(copy.deepcopy(schedule))
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(5))
            return result(schedule)
        self.save(True)
        worker = self.synchronizer(apply)
        self.addCleanup(release.set)
        worker.request()
        self.assertTrue(entered.wait(5))
        worker.request(self.save(False))
        outcome = []
        def close():
            self.app.begin_shutdown()
            closing.set()
            outcome.append(worker.close(5))
        thread = threading.Thread(target=close)
        thread.start()
        self.assertTrue(closing.wait(5))
        release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [True])
        self.assertEqual([s['enabled'] for s in calls], [True, False])
        self.assertFalse(worker.request(self.cfg.get()))
        self.assertFalse(self.app.background['registered'])

    def test_shutdown_failure_returns_false_without_endless_retries(self):
        apply = Mock(return_value={'ok': False, 'registered': True, 'message': 'delete denied'})
        worker = self.synchronizer(apply, retry_delay=0)
        with self.assertLogs('netcheck', level='WARNING'):
            self.assertFalse(worker.close(5))
        self.assertEqual(apply.call_count, 1)
        self.assertFalse(self.app.background['retrying'])

    def test_shutdown_timeout_stops_queued_updates_and_late_publication(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        simulated_os = {}
        def apply(schedule):
            calls.append(schedule)
            entered.set()
            self.assertTrue(release.wait(5))
            simulated_os.update(schedule)
            return result(schedule)
        self.save(True)
        worker = self.synchronizer(apply)
        self.addCleanup(release.set)
        worker.request()
        self.assertTrue(entered.wait(5))
        worker.request(self.save(False))
        with self.assertLogs('netcheck', level='WARNING'):
            self.assertFalse(worker.close(0))
        count = len(self.published)
        release.set()
        worker._thread.join(5)
        self.assertFalse(worker._thread.is_alive())
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.published), count)
        # An already running OS operation cannot be rolled back by a worker
        # timeout. close(False) must not be presented as final-disable success.
        self.assertTrue(simulated_os['enabled'])

    def test_api_shutdown_finishes_accepted_save_and_rejects_later_writes(self):
        entered, release, shutdown_done = threading.Event(), threading.Event(), threading.Event()
        saved, responses = self.cfg.save, []
        def save(body):
            entered.set()
            self.assertTrue(release.wait(5))
            return saved(body)
        self.app.on_config_saved = Mock()
        changed = self.cfg.get()
        changed['schedule']['interval_minutes'] = 15
        with patch.object(self.cfg, 'save', side_effect=save):
            writer = threading.Thread(target=lambda: responses.append(self.app.handle_post('/api/config', changed)))
            writer.start()
            self.assertTrue(entered.wait(5))
            stopper = threading.Thread(target=lambda: (self.app.begin_shutdown(), shutdown_done.set()))
            stopper.start()
            self.assertFalse(shutdown_done.is_set())
            release.set()
            writer.join(5)
            stopper.join(5)
        self.assertFalse(writer.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertEqual(responses[0][0], 200)
        self.app.on_config_saved.assert_called_once()
        later = self.cfg.get()
        later['schedule']['interval_minutes'] = 30
        self.assertEqual(self.app.handle_post('/api/config', later)[0], 503)
        self.assertEqual(self.cfg.get()['schedule']['interval_minutes'], 15)

    def test_publisher_rejects_stale_result_for_new_settings(self):
        old = self.save(True)['schedule']
        latest = self.save(False)['schedule']
        self.assertTrue(self.app.publish_background(result(latest), latest))
        self.assertFalse(self.app.publish_background(result(old), old))
        self.assertFalse(self.app.background['registered'])


class TaskFailureClassification(unittest.TestCase):
    def completed(self, code, stdout=b'', stderr=b''):
        return subprocess.CompletedProcess([], code, stdout, stderr)

    def test_failed_queries_cannot_claim_disabled_task_is_absent(self):
        denied = self.completed(1, stderr=b'access denied')
        with patch('nc.wintask.sys.platform', 'win32'), patch('nc.wintask._schtasks', side_effect=[denied, denied]):
            state = wintask.sync({'enabled': False, 'background': False})
        self.assertFalse(state['ok'])
        self.assertIsNone(state['registered'])

    def test_successful_listing_confirms_already_absent_task(self):
        missing = self.completed(1, stderr=b'not found')
        other = self.completed(0, b'"\\Other Task","N/A","Ready"\r\n')
        with patch('nc.wintask.sys.platform', 'win32'), patch('nc.wintask._schtasks', side_effect=[missing, other]):
            state = wintask.sync({'enabled': False, 'background': False})
        self.assertTrue(state['ok'])
        self.assertFalse(state['registered'])

    def test_failed_single_query_does_not_hide_task_present_in_listing(self):
        denied = self.completed(1, stderr=b'access denied')
        present = self.completed(0, f'"\\{wintask.TASK_NAME}","N/A","Ready"\r\n'.encode())
        with patch('nc.wintask.sys.platform', 'win32'), patch('nc.wintask._schtasks', side_effect=[denied, present]):
            state = wintask.sync({'enabled': False, 'background': False})
        self.assertFalse(state['ok'])
        self.assertTrue(state['registered'])

    def test_malformed_listing_cannot_confirm_absence(self):
        missing = self.completed(1)
        malformed = self.completed(0, b'unexpected output')
        with patch('nc.wintask.sys.platform', 'win32'), patch('nc.wintask._schtasks', side_effect=[missing, malformed]):
            state = wintask.sync({'enabled': False, 'background': False})
        self.assertFalse(state['ok'])
        self.assertIsNone(state['registered'])

    def test_failed_create_does_not_claim_previous_task_was_removed(self):
        with patch('nc.wintask.sys.platform', 'win32'), patch('nc.wintask.launch_command', return_value=('test.exe', '', '')), \
                patch('nc.wintask._schtasks', return_value=self.completed(1, stderr=b'access denied')):
            with self.assertLogs('netcheck', level='WARNING'):
                state = wintask.sync({'enabled': True, 'background': True})
        self.assertFalse(state['ok'])
        self.assertIsNone(state['registered'])

    def test_query_and_delete_share_one_timeout_budget(self):
        with patch('nc.wintask.sys.platform', 'win32'), \
                patch('nc.wintask.time.monotonic', side_effect=[100, 101, 110]), \
                patch('nc.wintask._schtasks', return_value=self.completed(0)) as task:
            state = wintask.sync({'enabled': False, 'background': False}, timeout=30)
        self.assertTrue(state['ok'])
        self.assertEqual([call.kwargs['timeout'] for call in task.call_args_list], [29, 20])

    def test_exhausted_total_budget_stops_before_second_os_command(self):
        with patch('nc.wintask.sys.platform', 'win32'), \
                patch('nc.wintask.time.monotonic', side_effect=[100, 101, 131]), \
                patch('nc.wintask._schtasks', return_value=self.completed(0)) as task:
            with self.assertLogs('netcheck', level='WARNING'):
                state = wintask.sync({'enabled': False, 'background': False}, timeout=30)
        self.assertFalse(state['ok'])
        self.assertIsNone(state['registered'])
        self.assertEqual(task.call_count, 1)


if __name__ == '__main__':
    unittest.main()
