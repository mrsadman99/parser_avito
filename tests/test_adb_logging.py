"""Журнал ADB: локальные дочерние процессы, без подключения к телефону."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mobile_proxy import adb
from mobile_proxy import own_mobile_proxy as mobile


class AdbLoggingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.log = Path(self.directory.name) / 'adb.log'
        self.log_patch = patch.object(adb, 'ADB_LOG', self.log)
        self.log_patch.start()
        self.addCleanup(self.log_patch.stop)

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def run_python(self, source, timeout=3):
        with patch.object(adb, '_command', return_value=[sys.executable, '-c', source]):
            return adb.run_adb('device', 'shell', timeout=timeout)

    def test_success_preserves_stdout_and_stderr_even_with_zero_code(self):
        response = self.run_python("import sys; print('готово'); print('warning', file=sys.stderr)")
        self.assertEqual(response.returncode, 0)
        start, finish = self.events()
        self.assertEqual(start['event'], 'start')
        self.assertEqual(finish['event'], 'finish')
        self.assertEqual(start['request_id'], finish['request_id'])
        self.assertEqual(finish['stdout'], 'готово\n')
        self.assertEqual(finish['stderr'], 'warning\n')
        self.assertGreaterEqual(finish['elapsed'], 0)

    def test_nonzero_code_is_recorded(self):
        self.run_python("import sys; print('denied', file=sys.stderr); sys.exit(7)")
        self.assertEqual(self.events()[-1]['returncode'], 7)
        self.assertEqual(self.events()[-1]['stderr'], 'denied\n')

    def test_timeout_preserves_partial_outputs(self):
        response = self.run_python("import sys,time; print('partial', flush=True); print('err', file=sys.stderr, flush=True); time.sleep(10)", timeout=.2)
        self.assertIsNone(response)
        finish = self.events()[-1]
        self.assertEqual(finish['event'], 'timeout')
        self.assertEqual(finish['stdout'], 'partial\n')
        self.assertEqual(finish['stderr'], 'err\n')

    def test_missing_adb_and_other_launch_errors(self):
        for error in (FileNotFoundError('adb missing'), PermissionError('denied')):
            with self.subTest(error=error), patch.object(adb.subprocess, 'run', side_effect=error):
                self.assertIsNone(adb.run_adb('device', 'get-state'))
                event = self.events()[-1]
                self.assertEqual(event['event'], 'error')
                self.assertIn(type(error).__name__, event['error'])

    def test_actual_adb_arguments_are_saved(self):
        with patch.object(adb.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            adb.run_adb('10241-device', 'shell', "su -c 'id'", timeout=12)
            self.assertEqual(self.events()[0]['command'], ['adb', '-s', '10241-device', 'shell', "su -c 'id'"])
            self.assertEqual(run.call_args.kwargs['timeout'], 12)

    def test_stream_captures_both_pipes_without_deadlock(self):
        output = io.BytesIO()
        source = "import sys; sys.stderr.write('E'*150000); sys.stderr.flush(); sys.stdout.write('лог\\n'*5000); sys.stdout.flush(); sys.exit(4)"
        with patch.object(adb, '_command', return_value=[sys.executable, '-c', source]):
            self.assertEqual(adb.stream_adb('device', ['shell', 'tail'], output), 4)
        events = self.events()
        stdout = ''.join(e['data'] for e in events if e['event'] == 'stdout')
        stderr = ''.join(e['data'] for e in events if e['event'] == 'stderr')
        self.assertEqual(stdout, 'лог\n' * 5000)
        self.assertEqual(output.getvalue().decode(), stdout)
        self.assertEqual(stderr, 'E' * 150000)
        self.assertEqual(events[-1]['returncode'], 4)

    def test_stream_spawn_failure_is_logged(self):
        with patch.object(adb.subprocess, 'Popen', side_effect=FileNotFoundError('missing')):
            with self.assertRaises(FileNotFoundError):
                adb.stream_adb('device', ['shell', 'tail'], io.BytesIO())
        self.assertEqual(self.events()[-1]['event'], 'error')

    def test_cli_uses_shared_adb_logger(self):
        from scripts import airplane_mode
        self.assertIs(airplane_mode._adb, adb.run_adb)
        self.assertIs(mobile._adb, adb.run_adb)

    def test_logfile_setup_propagates_edit_error(self):
        directory = Path(self.directory.name)
        config = directory / 'tinyproxy.conf'
        config.write_text('LogFile "old"\nSyslog On\n')
        fake_sed = directory / 'sed'
        fake_sed.write_text('#!/bin/sh\necho "edit denied" >&2\nexit 23\n')
        fake_sed.chmod(0o755)
        results = []
        def execute(client, command, timeout=60):
            result = subprocess.run(['bash', '-c', command], capture_output=True, text=True)
            results.append(result)
            return result.returncode, result.stdout, result.stderr
        with patch.object(mobile, 'REMOTE_ENV', f'export PATH={directory}:$PATH; '), \
             patch.object(mobile, 'TINYPROXY_CONF', str(config)), \
             patch.object(mobile, '_run_remote', side_effect=execute):
            self.assertFalse(mobile._ensure_logfile(object(), str(directory / 'tinyproxy.log')))
        self.assertEqual(results[0].returncode, 23)
        self.assertNotIn('logfile-ok', results[0].stdout)


if __name__ == '__main__':
    unittest.main()
