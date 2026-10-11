"""Прямой ADB forward и монитор восстановления; телефон и ADB подменены."""
from contextlib import nullcontext
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dto import AvitoConfig, OwnMobileProxyConfig, SshConfig
from load_config import _coerce_own_mobile_proxy, load_avito_config
from parser.proxies.proxy_factory import build_proxy
from utils import own_mobile_proxy as mobile
from utils import tinyproxy_forward as forward


class ForwardConfigTests(unittest.TestCase):
    def test_ports_validated_and_phone_port_comes_from_array(self):
        self.assertEqual(OwnMobileProxyConfig(port=9999, adb_forward=[5556, 8888]).port, 8888)
        for value in (True, False, [], [1], [1, 2, 3], [0, 8888], [5556, 65536],
                      ['5556', 8888], [True, 8888], [5556, 8.5]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                OwnMobileProxyConfig(adb_forward=value)

    def test_legacy_boolean_or_missing_array_cannot_disable_forward(self):
        for raw in ({'port': 5556}, {'port': 5556, 'adb_forward': False},
                    {'port': 5556, 'adb_forward': True}):
            self.assertEqual(_coerce_own_mobile_proxy(raw).adb_forward, [5556, 5556])

    def test_config_round_trip_and_proxy_addresses(self):
        import tomli_w
        raw = {'avito': {'own_mobile_proxy': dict(use=True, transport='ssh', port=9999,
                                                server='example.com:9999', adb_forward=[5556, 8888])}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_bytes(tomli_w.dumps(raw).encode())
            config = load_avito_config(path)
        proxy = build_proxy(config)
        self.assertEqual(proxy.get_httpx_proxy(), 'http://example.com:9999')
        self.assertEqual(proxy.get_playwright_proxy()['server'], 'http://example.com:9999')
        self.assertEqual(proxy.get_spfa_proxy_string(), 'example.com:9999')
        self.assertEqual(mobile.proxy_address(config.own_mobile_proxy), 'example.com:9999')
        with patch.object(mobile, 'rotate_ip', return_value=True) as rotate:
            self.assertTrue(proxy.handle_block())
            self.assertEqual(rotate.call_args.kwargs['adb_forward'], [5556, 8888])

    def test_empty_server_uses_host_localhost_not_phone_ssh_address(self):
        own = OwnMobileProxyConfig(use=True, ssh=SshConfig(host='phone'), adb_forward=[5556, 8888])
        self.assertEqual(mobile.proxy_address(own), '127.0.0.1:5556')
        self.assertEqual(build_proxy(AvitoConfig(own_mobile_proxy=own)).host, '127.0.0.1:5556')
        self.assertEqual(forward.proxy_address('[::1]:7777', [5556, 8888]), '[::1]:7777')

    def test_server_port_is_used_by_all_clients_and_does_not_change_adb_ports(self):
        own = OwnMobileProxyConfig(use=True, server='90.189.153.8:5556',
                                   adb_forward=[15556, 5556], login='user', password='secret')
        proxy = build_proxy(AvitoConfig(own_mobile_proxy=own))
        self.assertEqual(proxy.get_httpx_proxy(), 'http://user:secret@90.189.153.8:5556')
        self.assertEqual(proxy.get_playwright_proxy(), {
            'server': 'http://90.189.153.8:5556', 'username': 'user', 'password': 'secret'})
        self.assertEqual(proxy.get_spfa_proxy_string(), 'user:secret@90.189.153.8:5556')
        self.assertEqual(mobile.proxy_address(own), '90.189.153.8:5556')
        self.assertEqual(proxy.adb_forward, [15556, 5556])
        with patch.object(mobile, 'rotate_ip', return_value=True) as rotate:
            self.assertTrue(proxy.handle_block())
            self.assertEqual(rotate.call_args.kwargs['adb_forward'], [15556, 5556])

    def test_host_only_uses_forward_port_and_explicit_ports_are_validated(self):
        for host, expected in [('90.189.153.8', '90.189.153.8:15556'),
                               ('proxy.example.com', 'proxy.example.com:15556'),
                               ('[::1]', '[::1]:15556'), (' 127.0.0.1:5556 ', '127.0.0.1:5556')]:
            with self.subTest(host=host):
                self.assertEqual(forward.proxy_address(host, [15556, 5556]), expected)
        for invalid in ('127.0.0.1:0', '127.0.0.1:65536', '127.0.0.1:abc', '127.0.0.1:',
                        'http://127.0.0.1:5556', 'user@127.0.0.1:5556', '127.0.0.1/path'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                forward.proxy_address(invalid, [15556, 5556])


class ForwardLifecycleTests(unittest.TestCase):
    def test_command_uses_supported_tcp_port_syntax_and_selected_device(self):
        response = subprocess.CompletedProcess([], 0, '', '')
        with patch.object(forward, 'run_adb', return_value=response) as adb:
            forward._forward('device', 45678, 8888)
            adb.assert_called_once_with('device', 'forward', 'tcp:45678', 'tcp:8888', timeout=10)
        for response in (None, subprocess.CompletedProcess([], 1, '', 'offline')):
            with patch.object(forward, 'run_adb', return_value=response), self.assertRaises(RuntimeError):
                forward._forward('device', 45678, 8888)

    def test_existing_monitor_restores_configured_port_without_new_process(self):
        state = dict(pid=123, serial='device', phone_port=8888, local_port=5556)
        with patch.object(forward, '_locked', return_value=nullcontext()), \
             patch.object(forward, '_read_state', return_value=state), \
             patch.object(forward, '_alive', return_value=True), \
             patch.object(forward, '_forward') as restore, \
             patch.object(forward.subprocess, 'Popen') as spawn:
            forward.ensure_forward('device', [5556, 8888])
            restore.assert_called_once_with('device', 5556, 8888)
            spawn.assert_not_called()

    def test_stop_removes_only_owned_adb_port(self):
        with patch.object(forward, 'run_adb') as adb:
            forward._remove_forward(dict(serial='device', local_port=45678))
        adb.assert_called_once_with('device', 'forward', '--remove', 'tcp:45678', timeout=10)

    def test_start_requires_forward_for_both_control_transports(self):
        for transport in ('ssh', 'adb'):
            own = OwnMobileProxyConfig(use=True, transport=transport, adb_serial='device', adb_forward=[5556, 8888])
            with self.subTest(transport=transport), patch.object(mobile, '_open_control'), \
                 patch.object(mobile, '_restart_tinyproxy', return_value=(True, 'running')), \
                 patch.object(mobile, 'ensure_forward', side_effect=RuntimeError('offline')) as create, \
                 patch.object(mobile, '_start_log_follower') as follower:
                self.assertEqual(mobile.start_proxy(AvitoConfig(own_mobile_proxy=own)), 1)
                create.assert_called_once_with('device', [5556, 8888])
                follower.assert_not_called()

    def test_already_running_phone_still_requires_forward(self):
        own = OwnMobileProxyConfig(use=True, adb_serial='device', adb_forward=[5556, 8888])
        with patch.object(mobile, 'service_running', return_value=True), \
             patch.object(mobile, 'start_proxy') as start, \
             patch.object(mobile, '_start_log_follower'), \
             patch.object(mobile, 'ensure_forward') as create:
            self.assertTrue(mobile.ensure_own_mobile_proxy(AvitoConfig(own_mobile_proxy=own)))
            create.assert_called_once_with('device', [5556, 8888])
            start.assert_not_called()

    def test_rotation_forward_failure_is_returned_to_retry_mechanism(self):
        with patch.object(mobile, '_rotate_airplane', return_value=True), \
             patch.object(mobile, '_AdbTermuxClient'), \
             patch.object(mobile, '_restart_tinyproxy', return_value=(True, 'running')), \
             patch.object(mobile, 'ensure_forward', side_effect=RuntimeError('offline')):
            self.assertFalse(mobile.rotate_ip('device', transport='adb', adb_forward=[5556, 8888]))

    def test_stop_closes_forward_even_if_phone_is_unavailable(self):
        own = OwnMobileProxyConfig(use=True)
        with patch.object(mobile, '_stop_log_follower'), \
             patch.object(mobile, '_open_control', side_effect=RuntimeError('offline')), \
             patch.object(mobile, 'stop_forward') as stop:
            self.assertEqual(mobile.stop_proxy(AvitoConfig(own_mobile_proxy=own)), 1)
            stop.assert_called_once_with()


class ForwardMonitorTests(unittest.TestCase):
    def test_disconnect_is_retried_until_restored(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(forward, 'STATE', Path(directory) / 'state.json'), \
             patch.object(forward.signal, 'signal'), \
             patch.object(forward, '_forward', side_effect=[None, RuntimeError('offline'), None]) as restore, \
             patch.object(forward, '_remove_forward') as remove, \
             patch.object(forward.time, 'sleep', side_effect=[None, None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                forward.watch_forward('device', [15556, 5556])
            self.assertEqual(restore.call_count, 3)
            self.assertTrue(all(call.args == ('device', 15556, 5556) for call in restore.call_args_list))
            remove.assert_called_once()
            self.assertIsNone(forward._read_state())

    def test_failed_initial_forward_does_not_remove_existing_mapping(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(forward, 'STATE', Path(directory) / 'state.json'), \
             patch.object(forward.signal, 'signal'), \
             patch.object(forward, '_forward', side_effect=RuntimeError('port occupied')), \
             patch.object(forward, '_remove_forward') as remove:
            with self.assertRaises(RuntimeError):
                forward.watch_forward('device', [15556, 5556])
            remove.assert_not_called()
            self.assertIsNone(forward._read_state())

    def test_old_receiver_is_stopped_before_creating_direct_forward(self):
        old_state = dict(pid=123, serial='device', public_port=5556, phone_port=8888, local_port=45678)
        process = unittest.mock.Mock()
        process.poll.return_value = 1
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(forward, 'LOG', Path(directory) / 'log'), \
             patch.object(forward, '_locked', return_value=nullcontext()), \
             patch.object(forward, '_read_state', return_value=old_state), \
             patch.object(forward, '_alive', return_value=True), \
             patch.object(forward, '_stop') as stop, \
             patch.object(forward.subprocess, 'Popen', return_value=process):
            with self.assertRaises(RuntimeError):
                forward.ensure_forward('device', [5556, 8888])
            stop.assert_called_once_with(old_state)

    def test_background_monitor_starts_is_reused_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'fake_phone.py'
            # Реальный фоновый процесс без listener; все обращения к ADB подменены.
            script.write_text(
                'import argparse\nfrom pathlib import Path\nimport sys\n'
                f'sys.path.insert(0, {str(forward.ROOT)!r})\n'
                'from utils import tinyproxy_forward as f\n'
                f'f.STATE = Path({str(root / "state.json")!r})\n'
                f'calls = Path({str(root / "calls.log")!r})\n'
                'def record(*args):\n'
                '    with calls.open("a") as out: out.write(repr(args) + "\\n")\n'
                'f._forward = lambda *args: record("forward", *args)\n'
                'f._remove_forward = lambda state: record("remove", state["local_port"])\n'
                'p = argparse.ArgumentParser()\np.add_argument("--serial")\n'
                'p.add_argument("--ports", nargs=2, type=int)\na=p.parse_args()\n'
                'f.watch_forward(a.serial, a.ports)\n'
            )
            with patch.object(forward, 'STATE', root / 'state.json'), \
                 patch.object(forward, 'LOCK', root / 'lock'), \
                 patch.object(forward, 'LOG', root / 'process.log'), \
                 patch.object(forward, 'SCRIPT', script), \
                 patch.object(forward, '_forward') as restore, \
                 patch.object(forward, '_remove_forward'):
                try:
                    forward.ensure_forward('device', [15556, 5556])
                    state = forward._read_state()
                    self.assertIsNotNone(state)
                    self.assertEqual(state['local_port'], 15556)
                    self.assertNotIn('public_port', state)
                    forward.ensure_forward('device', [15556, 5556])
                    self.assertEqual(forward._read_state(), state)
                    restore.assert_called_once_with('device', 15556, 5556)
                finally:
                    forward.stop_forward()
                self.assertFalse(forward._alive(state['pid']))
                self.assertIsNone(forward._read_state())
                self.assertIn("'remove', 15556", (root / 'calls.log').read_text())


if __name__ == '__main__':
    unittest.main()
