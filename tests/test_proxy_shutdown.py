"""Очистка прокси: реальные локальные процессы; обращения к телефону подменены."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from domain.config import AvitoConfig, OwnMobileProxyConfig
from scripts import stop as stop_script
from mobile_proxy import background_process as process
from mobile_proxy import own_mobile_proxy as mobile
from mobile_proxy import tinyproxy_forward as forward


class RemoteStopTests(unittest.TestCase):
    def test_term_waits_for_delayed_shutdown_without_kill(self):
        with patch.object(mobile, '_run_remote', side_effect=[
                (0, '', ''), (0, 'running', ''), (0, 'running', ''), (0, 'stopped', '')]) as run, \
             patch.object(mobile.time, 'sleep'):
            self.assertTrue(mobile._stop_tinyproxy(Mock())[0])
        self.assertFalse(any('pkill -9' in call.args[1] for call in run.call_args_list))
        self.assertIn("pkill -f '^/data/data/com\\.termux/files/usr/bin/tinyproxy([[:space:]]|$)'",
                      run.call_args_list[0].args[1])

    def test_kill_waits_and_checks_result(self):
        responses = [(0, '', '')] + [(0, 'running', '')] * 20 + [
            (0, '', ''), (0, 'running', ''), (0, 'stopped', '')]
        with patch.object(mobile, '_run_remote', side_effect=responses) as run, \
             patch.object(mobile.time, 'sleep'):
            self.assertTrue(mobile._stop_tinyproxy(Mock())[0])
        self.assertEqual(sum('pkill -9' in call.args[1] for call in run.call_args_list), 1)
        kill_command = next(call.args[1] for call in run.call_args_list if 'pkill -9' in call.args[1])
        self.assertIn("pkill -9 -f '^/data/data/com\\.termux/files/usr/bin/tinyproxy([[:space:]]|$)'", kill_command)

    def test_signal_and_status_errors_are_not_success(self):
        for responses in ([(2, '', 'denied')], [(0, '', ''), (2, '', 'pgrep failed')],
                          [(0, '', ''), (0, '', '')]):
            with self.subTest(responses=responses), \
                 patch.object(mobile, '_run_remote', side_effect=responses):
                self.assertFalse(mobile._stop_tinyproxy(Mock())[0])

    def test_restart_does_not_launch_when_old_proxy_cannot_stop(self):
        with patch.object(mobile, '_stop_tinyproxy', return_value=(False, 'denied')), \
             patch.object(mobile, '_run_remote') as run:
            self.assertEqual(mobile._restart_tinyproxy(Mock(), '/phone/log'), (False, 'denied'))
            run.assert_not_called()

    def test_pgrep_error_is_preserved_by_remote_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'pgrep'
            script.write_text('#!/bin/sh\nexit 2\n')
            script.chmod(0o755)
            with patch.object(mobile, 'REMOTE_ENV', f'export PATH={directory}:$PATH; '):
                result = subprocess.run(['bash', '-c', mobile._remote_status_command()], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(b'stopped', result.stdout)

    @unittest.skipIf(os.name == 'nt', 'Termux shell test')
    def test_remote_tail_pid_is_cleaned_even_without_new_log_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            logfile, pidfile = Path(directory) / 'log', Path(directory) / 'tail.pid'
            logfile.touch()
            with patch.object(mobile, 'REMOTE_ENV', ''):
                tail = subprocess.Popen(['bash', '-c', mobile._remote_tail_command(str(logfile), str(pidfile))],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 3
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                # Дожидаемся exec, чтобы проверять именно tail.
                for _ in range(100):
                    name = subprocess.run(['ps', '-p', str(tail.pid), '-o', 'comm='],
                                          capture_output=True, text=True).stdout.strip()
                    if name == 'tail':
                        break
                    time.sleep(.02)
                with patch.object(mobile, 'REMOTE_ENV', ''):
                    result = subprocess.run(['bash', '-c', mobile._remote_stop_tails_command(str(pidfile))],
                                            capture_output=True, timeout=3)
                self.assertEqual(result.returncode, 0, result.stderr)
                tail.wait(timeout=3)
                self.assertFalse(pidfile.exists())
            finally:
                if tail.poll() is None:
                    tail.kill()
                tail.wait()


class ShutdownRoutesTests(unittest.TestCase):
    def setUp(self):
        self.follower = patch.object(mobile, '_stop_log_follower').start()
        self.forward = patch.object(mobile, 'stop_forward').start()
        self.control = patch.object(mobile, '_open_control').start()
        self.remote = patch.object(mobile, '_run_remote', return_value=(0, '', '')).start()
        self.phone = patch.object(mobile, '_stop_tinyproxy', return_value=(True, 'stopped')).start()
        self.addCleanup(patch.stopall)

    def test_disabled_proxy_still_cleans_all_processes(self):
        config = AvitoConfig(own_mobile_proxy=OwnMobileProxyConfig(use=False))
        self.assertEqual(mobile.stop_proxy(config), 0)
        self.follower.assert_called_once()
        self.forward.assert_called_once()
        self.phone.assert_called_once()

    def test_local_failure_does_not_skip_remaining_cleanup(self):
        self.follower.side_effect = RuntimeError('cannot stop follower')
        self.assertEqual(mobile.stop_proxy(AvitoConfig()), 1)
        self.forward.assert_called_once()
        self.phone.assert_called_once()

    def test_remote_tail_failure_does_not_skip_tinyproxy(self):
        self.remote.side_effect = RuntimeError('tail timeout')
        self.assertEqual(mobile.stop_proxy(AvitoConfig()), 1)
        self.phone.assert_called_once()

    def test_missing_ssh_host_still_stops_local_processes(self):
        self.control.side_effect = ValueError('no ssh.host')
        with patch.object(stop_script, 'load_avito_config', return_value=AvitoConfig()):
            self.assertEqual(stop_script.stop_own_proxy(False), 1)
        self.follower.assert_called_once()
        self.forward.assert_called_once()

    def test_invalid_config_still_stops_local_processes(self):
        with patch.object(stop_script, 'load_avito_config', side_effect=ValueError('invalid config')):
            self.assertEqual(stop_script.stop_own_proxy(False), 1)
        self.follower.assert_called_once()
        self.forward.assert_called_once()
        self.control.assert_not_called()

    def test_dry_run_does_not_stop_processes(self):
        with patch.object(stop_script, 'load_avito_config', return_value=AvitoConfig()):
            self.assertEqual(stop_script.stop_own_proxy(True), 0)
        self.follower.assert_not_called()
        self.forward.assert_not_called()

    def test_stop_command_reports_proxy_failure_as_nonzero(self):
        with patch.object(stop_script, 'stop_detached'), patch.object(stop_script, 'stop_tmux'), \
             patch.object(stop_script, 'stop_own_proxy', return_value=1):
            self.assertEqual(stop_script.main([]), 1)


class ForwardRemovalTests(unittest.TestCase):
    def test_already_removed_forward_is_success(self):
        with patch.object(forward, 'run_adb', side_effect=[
                subprocess.CompletedProcess([], 1, '', 'listener not found'),
                subprocess.CompletedProcess([], 0, 'other tcp:4444 tcp:5555\n', '')]):
            forward._remove_forward(dict(serial='device', local_port=15556))

    def test_failed_removal_keeps_state_for_retry(self):
        import json
        state = dict(pid=123, serial='device', phone_port=5556, local_port=15556)
        with tempfile.TemporaryDirectory() as directory, patch.object(forward, 'STATE', Path(directory) / 'state'), \
             patch.object(forward, '_stop_process') as stop, \
             patch.object(forward, '_remove_forward', side_effect=RuntimeError('offline')):
            forward.STATE.write_text(json.dumps(state))
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                forward._stop(state)
            self.assertEqual(forward._read_state(), state)
            stop.assert_called_once()

    def test_remove_failure_is_not_hidden_when_mapping_still_exists(self):
        for listing in (None, subprocess.CompletedProcess([], 0, 'device tcp:15556 tcp:5556\n', '')):
            with self.subTest(listing=listing), patch.object(forward, 'run_adb', side_effect=[None, listing]):
                with self.assertRaises(RuntimeError):
                    forward._remove_forward(dict(serial='device', local_port=15556))


@unittest.skipIf(os.name == 'nt', 'POSIX process groups')
class LocalProcessTests(unittest.TestCase):
    def test_simultaneous_starts_create_only_one_log_follower(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            barrier = threading.Barrier(2)
            errors = []
            def start():
                try:
                    barrier.wait(timeout=3)
                    mobile._start_log_follower('config.toml', '/phone/log')
                except BaseException as err:
                    errors.append(err)
            with patch.object(mobile, 'FOLLOW_PID', root / 'pid'), \
                 patch.object(mobile, 'FOLLOW_LOCK', root / 'lock'), \
                 patch.object(mobile, 'FOLLOW_LOG', root / 'log'), \
                 patch.object(mobile, '_pid_alive', side_effect=lambda pid: pid == 123), \
                 patch.object(mobile.subprocess, 'Popen', return_value=Mock(pid=123)) as spawn:
                threads = [threading.Thread(target=start) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)
                self.assertFalse(any(thread.is_alive() for thread in threads))
                self.assertEqual(errors, [])
                spawn.assert_called_once()
                self.assertEqual((root / 'pid').read_text(), '123')

    def test_follower_stops_actual_stream_child_before_exiting(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script, ready, journal = root / 'follow.py', root / 'ready', root / 'adb.log'
            script.write_text(
                'import signal,sys\nfrom pathlib import Path\n'
                f'sys.path.insert(0, {str(mobile.ROOT)!r})\n'
                'from mobile_proxy import adb\n'
                f'adb.ADB_LOG = Path({str(journal)!r})\n'
                'def stop(*args): raise SystemExit(0)\n'
                'signal.signal(signal.SIGTERM, stop)\n'
                'adb._command = lambda *args: [sys.executable, "-c", '
                '"import time; print(\'ready\', flush=True); time.sleep(60)"]\n'
                'class Output:\n'
                '    def write(self, data):\n'
                f'        Path({str(ready)!r}).touch()\n'
                '    def flush(self): pass\n'
                'adb.stream_adb(None, [], Output())\n'
            )
            child = subprocess.Popen([sys.executable, str(script)], start_new_session=True,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 3
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(ready.exists())
                process.stop(child.pid, scripts=(script,))
                events = [json.loads(line) for line in journal.read_text().splitlines()]
                adb_pid = next(event['child_pid'] for event in events if event['event'] == 'spawn')
                self.assertFalse(process.alive(adb_pid))
                self.assertEqual(events[-1]['event'], 'finish')
                self.assertIsNotNone(events[-1]['returncode'])
            finally:
                if process.alive(child.pid):
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait()

    def test_follower_gets_time_for_finally_and_is_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'follow.py'
            ready, cleaned = root / 'ready', root / 'cleaned'
            script.write_text('import signal,time\nfrom pathlib import Path\n'
                              'def stop(*args): raise SystemExit(0)\n'
                              'signal.signal(signal.SIGTERM, stop)\n'
                              f'Path({str(ready)!r}).touch()\n'
                              'try:\n    time.sleep(60)\nfinally:\n'
                              f'    Path({str(cleaned)!r}).touch()\n')
            child = subprocess.Popen([sys.executable, str(script)], start_new_session=True)
            try:
                deadline = time.monotonic() + 3
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                pidfile = root / 'follow.pid'
                pidfile.write_text(str(child.pid))
                with patch.object(mobile, 'FOLLOW_PID', pidfile), \
                     patch.object(mobile, 'FOLLOW_LOCK', root / 'lock'), \
                     patch.object(mobile, 'FOLLOWER_SCRIPT', script):
                    mobile._stop_log_follower()
                self.assertFalse(process.alive(child.pid))
                self.assertTrue(cleaned.exists())
                self.assertFalse(pidfile.exists())
            finally:
                if process.alive(child.pid):
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait()

    def test_stubborn_process_is_killed_and_reaped_in_one_call(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / 'ready'
            child = subprocess.Popen([sys.executable, '-c',
                'import signal,time; from pathlib import Path; '
                'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                f'Path({str(ready)!r}).touch(); time.sleep(60)'], start_new_session=True)
            try:
                deadline = time.monotonic() + 3
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                process.stop(child.pid, timeout=.1)
                self.assertFalse(process.alive(child.pid))
            finally:
                if process.alive(child.pid):
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait()

    def test_reused_pid_of_foreign_process_is_not_killed(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            with self.assertRaisesRegex(RuntimeError, 'не принадлежит'):
                process.stop(child.pid, scripts=(mobile.FOLLOWER_SCRIPT,))
            self.assertIsNone(child.poll())
        finally:
            child.kill()
            child.wait()

    def test_invalid_pid_never_signals_process_group(self):
        for pid in (-1, 0, 1, None):
            with patch.object(process.os, 'killpg') as kill, self.assertRaises(ValueError):
                process.stop(pid)
            kill.assert_not_called()
