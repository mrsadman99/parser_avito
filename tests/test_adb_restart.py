"""Перезапуск Termux: все обращения к телефону замоканы."""
import shlex
import subprocess
import unittest
from unittest.mock import Mock, patch

from dto import AvitoConfig, OwnMobileProxyConfig
from parser.proxies.proxy_factory import build_proxy
from utils import own_mobile_proxy as mobile


def result(code=0, stdout='', stderr=''):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class AdbRestartTests(unittest.TestCase):
    def test_termux_uid_and_shell_quoting(self):
        command = "echo 'hello'; export HOME=/data/data/com.termux/files/home"
        with patch.object(mobile, '_adb', side_effect=[result(stdout='10234'), result(stdout='ok')]) as adb:
            client = mobile._AdbTermuxClient('device-1')
            self.assertEqual(client.run(command, 12), (0, 'ok', ''))
        args, kwargs = adb.call_args
        self.assertEqual(args[:2], ('device-1', 'shell'))
        outer = shlex.split(args[2])
        inner = shlex.split(outer[2])
        self.assertEqual(inner, ['su', '10234', '-s', mobile.TERMUX_PREFIX + '/bin/bash', '-c', command])
        self.assertEqual(kwargs['timeout'], 12)

    def test_reject_missing_root_and_invalid_uid(self):
        for response in (None, result(1), result(stdout='0'), result(stdout='invalid')):
            with self.subTest(response=response), patch.object(mobile, '_adb', return_value=response):
                with self.assertRaises(RuntimeError):
                    mobile._AdbTermuxClient(None)

    def test_rotation_uses_adb_without_ssh(self):
        for ok in (True, False):
            with self.subTest(ok=ok), patch.object(mobile, '_rotate_airplane', return_value=True), \
                 patch.object(mobile, '_AdbTermuxClient') as client, \
                 patch.object(mobile, '_connect') as ssh, \
                 patch.object(mobile, '_restart_tinyproxy', return_value=(ok, 'state')):
                self.assertEqual(mobile.rotate_ip('device', transport='adb'), ok)
                client.assert_called_once_with('device')
                client.return_value.close.assert_called_once()
                ssh.assert_not_called()

    def test_network_failure_does_not_start_proxy(self):
        with patch.object(mobile, '_run_remote', return_value=(1, '', '')) as run, \
             patch.object(mobile, '_fix_interfaces_via_ssh', return_value=False):
            self.assertFalse(mobile._restart_tinyproxy(Mock(), mobile.DEFAULT_DEVICE_LOG)[0])
            self.assertEqual(run.call_count, 1)

    def test_dead_process_is_failure(self):
        with patch.object(mobile, '_run_remote', side_effect=[(0, '', ''), (0, 'started', ''), (0, 'stopped', '')]), \
             patch.object(mobile, '_fix_interfaces_via_ssh', return_value=True), \
             patch.object(mobile, '_ensure_logfile', return_value=True), patch.object(mobile.time, 'sleep'):
            self.assertFalse(mobile._restart_tinyproxy(Mock(), mobile.DEFAULT_DEVICE_LOG)[0])

    def test_factory_passes_transport(self):
        config = AvitoConfig(own_mobile_proxy=OwnMobileProxyConfig(use=True, transport='adb'))
        proxy = build_proxy(config)
        with patch.object(mobile, 'rotate_ip', return_value=False) as rotate:
            self.assertFalse(proxy.handle_block())
            self.assertEqual(rotate.call_args.kwargs['transport'], 'adb')
        with self.assertRaises(ValueError):
            OwnMobileProxyConfig(transport='bad')

    def test_lifecycle_routes_all_commands(self):
        for transport in ('adb', 'ssh'):
            config = AvitoConfig(own_mobile_proxy=OwnMobileProxyConfig(use=True, transport=transport))
            with self.subTest(transport=transport), patch.object(mobile, '_AdbTermuxClient') as adb, \
                 patch.object(mobile, '_connect') as ssh, \
                 patch.object(mobile, '_restart_tinyproxy', return_value=(True, 'running')), \
                 patch.object(mobile, '_start_log_follower'), patch.object(mobile, '_stop_log_follower'), \
                 patch.object(mobile, '_run_remote', side_effect=[(0, 'running', ''), (0, '', ''), (0, 'running', ''), (0, '', ''), (0, 'stopped', '')]):
                self.assertEqual(mobile.start_proxy(config), 0)
                self.assertTrue(mobile.service_running(config))
                self.assertEqual(mobile.stop_proxy(config), 0)
                selected, unused = (adb, ssh) if transport == 'adb' else (ssh, adb)
                self.assertEqual(selected.call_count, 4)
                unused.assert_not_called()

    def test_ssh_rotation_never_calls_adb(self):
        with patch.object(mobile, '_adb') as adb, patch.object(mobile, '_connect') as connect, \
             patch.object(mobile, '_run_remote', side_effect=[(0, '', ''), (0, '0', '')]) as run, \
             patch.object(mobile, '_restart_tinyproxy', return_value=(True, 'running')), \
             patch.object(mobile.time, 'sleep'):
            self.assertTrue(mobile.rotate_ip(ssh=Mock(host='phone'), transport='ssh'))
            adb.assert_not_called()
            self.assertEqual(connect.call_count, 3)
            command = run.call_args_list[0].args[1]
            self.assertIn('nohup', command)
            self.assertIn('airplane-mode enable', command)
            self.assertIn('airplane-mode disable', command)

    def test_ssh_rotation_failure_is_propagated(self):
        with patch.object(mobile, '_connect'), \
             patch.object(mobile, '_run_remote', side_effect=[(0, '', ''), (0, '1', '')]), \
             patch.object(mobile, '_restart_tinyproxy') as restart, patch.object(mobile.time, 'sleep'):
            self.assertFalse(mobile.rotate_ip(ssh=Mock(host='phone'), transport='ssh'))
            restart.assert_not_called()

    def test_legacy_config_and_explicit_transport(self):
        from load_config import _coerce_own_mobile_proxy
        self.assertEqual(_coerce_own_mobile_proxy({'restart_via': 'adb'}).transport, 'adb')
        self.assertEqual(_coerce_own_mobile_proxy({'restart_via': 'adb', 'transport': 'ssh'}).transport, 'ssh')

    def test_adb_log_stream_uses_selected_device(self):
        import tempfile
        client = mobile._AdbTermuxClient.__new__(mobile._AdbTermuxClient)
        client.serial, client.uid = 'test-device', '10234'
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(mobile, '_open_control', return_value=client), \
             patch.object(mobile, '_connect') as ssh, \
             patch.object(mobile, 'stream_adb', return_value=1) as stream, \
             patch.object(mobile.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                mobile.stream_remote_log(Mock(), '/phone/log', directory + '/log')
            self.assertEqual(stream.call_args.args[0], 'test-device')
            self.assertEqual(stream.call_args.args[1][0], 'shell')
            self.assertIn('tail -n +1 -F', stream.call_args.args[1][1])
            ssh.assert_not_called()

    def test_stop_script_accepts_adb_without_ssh_host(self):
        from scripts import stop
        config = AvitoConfig(own_mobile_proxy=OwnMobileProxyConfig(use=True, transport='adb'))
        with patch.object(stop, 'load_avito_config', return_value=config), \
             patch.object(mobile, 'stop_proxy', return_value=0) as shutdown:
            stop.stop_own_proxy(False)
            shutdown.assert_called_once_with(config, force=True)

    def test_airplane_cli_obeys_ssh_transport(self):
        from scripts import airplane_mode
        config = AvitoConfig(own_mobile_proxy=OwnMobileProxyConfig(transport='ssh'))
        with patch('load_config.load_avito_config', return_value=config), \
             patch.object(airplane_mode, '_adb') as adb, \
             patch.object(mobile, '_rotate_airplane_ssh', return_value=True) as rotate:
            self.assertEqual(airplane_mode.main(['--on-sleep', '2', '--off-sleep', '3']), 0)
            rotate.assert_called_once_with(config.own_mobile_proxy.ssh, 2, 3)
            adb.assert_not_called()

    def test_ssh_log_stream_does_not_spawn_adb(self):
        import tempfile
        own = OwnMobileProxyConfig(transport='ssh')
        client = Mock()
        channel = client.get_transport.return_value.open_session.return_value
        channel.recv.side_effect = [b'log line', b'']
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(mobile, '_connect', return_value=client), \
             patch.object(mobile.subprocess, 'Popen') as popen, \
             patch.object(mobile.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                mobile.stream_remote_log(own, '/phone/log', directory + '/log')
            from pathlib import Path
            self.assertEqual(Path(directory + '/log').read_bytes(), b'log line')
            popen.assert_not_called()
            client.close.assert_called_once()

    def test_adb_restart_preserves_network_and_existing_config(self):
        client = mobile._AdbTermuxClient.__new__(mobile._AdbTermuxClient)
        client.uid, client.serial = '10241', 'device'
        with patch.object(mobile, '_run_remote', side_effect=[(0, '', ''), (0, 'started', ''), (0, 'running', '')]) as run, \
             patch.object(mobile, '_fix_interfaces_via_ssh') as fix, \
             patch.object(mobile, '_ensure_logfile') as edit_config, patch.object(mobile.time, 'sleep'):
            self.assertTrue(mobile._restart_tinyproxy(client, mobile.DEFAULT_DEVICE_LOG)[0])
            fix.assert_not_called()
            edit_config.assert_not_called()
            self.assertEqual(run.call_count, 3)
            commands = [c.args[1] for c in run.call_args_list]
            self.assertIn('pkill -x tinyproxy', commands[0])
            self.assertIn('nohup /data/data/com.termux/files/usr/bin/tinyproxy -d -c ', commands[1])
            self.assertIn('pgrep -x tinyproxy', commands[2])
            self.assertNotIn('sed ', ''.join(commands))
            self.assertNotIn('base64', ''.join(commands))

    def test_ssh_restart_runs_interface_fix_before_start(self):
        steps = []
        def run(client, command, timeout=60):
            steps.append(command)
            return 0, 'running', ''
        def fix(client):
            steps.append('fix')
            return True
        def logfile(client, log):
            steps.append('logfile')
            return True
        with patch.object(mobile, '_run_remote', side_effect=run), \
             patch.object(mobile, '_fix_interfaces_via_ssh', side_effect=fix), \
             patch.object(mobile, '_ensure_logfile', side_effect=logfile), patch.object(mobile.time, 'sleep'):
            self.assertTrue(mobile._restart_tinyproxy(Mock(), mobile.DEFAULT_DEVICE_LOG)[0])
        self.assertIn('pkill', steps[0])
        self.assertEqual(steps[1:3], ['fix', 'logfile'])
        self.assertIn('nohup', steps[3])

    def test_ssh_interface_script_uses_renamed_local_and_remote_paths(self):
        with patch.object(mobile, '_run_remote', return_value=(0, '', '')) as run:
            self.assertTrue(mobile._fix_interfaces_via_ssh(Mock()))
            command = run.call_args.args[1]
            self.assertIn('/home/fix_interfaces_via_ssh.sh', command)
            self.assertIn('bash -x', command)
            self.assertEqual(mobile.FIX_INTERFACES_SCRIPT.name, 'fix_interfaces_via_ssh.sh')
            self.assertTrue(mobile.FIX_INTERFACES_SCRIPT.exists())

    def test_adb_airplane_cycle_uses_root_connectivity_service(self):
        with patch.object(mobile, '_adb', return_value=result()) as adb, patch.object(mobile.time, 'sleep') as sleep:
            self.assertTrue(mobile._rotate_airplane('device'))
            self.assertEqual(adb.call_args_list, [
                unittest.mock.call('device', 'get-state'),
                unittest.mock.call('device', 'shell', "su -c 'cmd connectivity airplane-mode enable'"),
                unittest.mock.call('device', 'shell', "su -c 'cmd connectivity airplane-mode disable'"),
            ])
            self.assertEqual(sleep.call_args_list, [unittest.mock.call(5), unittest.mock.call(12)])

    def test_adb_airplane_permission_failure_is_not_success(self):
        with patch.object(mobile, '_adb', side_effect=[result(), result(1, stderr='Permission Denial')]) as adb, \
             patch.object(mobile.time, 'sleep') as sleep:
            self.assertFalse(mobile._rotate_airplane('device'))
            self.assertEqual(adb.call_count, 2)
            sleep.assert_not_called()

    def test_adb_airplane_disable_failure_is_not_success(self):
        with patch.object(mobile, '_adb', side_effect=[result(), result(), result(1, stderr='denied')]), \
             patch.object(mobile.time, 'sleep') as sleep:
            self.assertFalse(mobile._rotate_airplane('device'))
            sleep.assert_called_once_with(5)

    def test_adb_airplane_attempts_disable_after_interrupted_wait(self):
        with patch.object(mobile, '_adb', return_value=result()) as adb, \
             patch.object(mobile.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                mobile._rotate_airplane('device')
            self.assertEqual(adb.call_args.args, ('device', 'shell', "su -c 'cmd connectivity airplane-mode disable'"))

    def test_airplane_cli_uses_same_checked_root_command(self):
        from scripts import airplane_mode
        with patch.object(mobile, '_adb', return_value=result(1, stderr='Permission Denial')) as adb:
            self.assertFalse(airplane_mode.set_airplane('device', True))
            adb.assert_called_once_with('device', 'shell', "su -c 'cmd connectivity airplane-mode enable'")


if __name__ == '__main__':
    unittest.main()
