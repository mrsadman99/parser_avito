"""Управление tinyproxy в Termux через выбранный transport: adb или ssh.

Запуск, остановка, статус, логи и смена IP используют один транспорт.
ADB требует root и выполняет команды с UID Termux. SSH подключается к Termux sshd.
Прокси доступен напрямую по server:port (резервный адрес — ssh.host).
"""
import base64
import os
import shlex
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from loguru import logger

from utils.adb import run_adb as _adb, stream_adb

ROOT = Path(__file__).resolve().parent.parent
FIX_INTERFACES_SCRIPT = ROOT / "scripts" / "fix_interfaces_via_ssh.sh"
FOLLOWER_SCRIPT = ROOT / "scripts" / "follow_tinyproxy_log.py"

LOGS_DIR = ROOT / "logs"
LOCAL_LOG = LOGS_DIR / "tinyproxy.log"          # лог tinyproxy на ХОСТЕ
FOLLOW_PID = LOGS_DIR / "tinyproxy_follow.pid"
FOLLOW_LOG = LOGS_DIR / "tinyproxy_follow.log"  # диагностика самого стрима

DEFAULT_CONFIG = "config.toml"
TERMUX_PREFIX = "/data/data/com.termux/files/usr"
TERMUX_HOME = "/data/data/com.termux/files/home"
TINYPROXY_CONF = f"{TERMUX_PREFIX}/etc/tinyproxy/tinyproxy.conf"
DEFAULT_DEVICE_LOG = f"{TERMUX_HOME}/tinyproxy.log"
REMOTE_FIX_INTERFACES_SCRIPT = f"{TERMUX_HOME}/fix_interfaces_via_ssh.sh"

AIRPLANE_ON_SLEEP = 5     # пауза в режиме полёта (сброс сети)
AIRPLANE_OFF_SLEEP = 12   # пауза после выхода из режима полёта (получение нового IP)

REMOTE_ENV = (
    f"export PREFIX={TERMUX_PREFIX}; "
    f"export HOME={TERMUX_HOME}; "
    "export PATH=$PREFIX/bin:/system/bin:/system/xbin:/sbin:$PATH; "
    "export LD_LIBRARY_PATH=$PREFIX/lib; "
    "export TMPDIR=$PREFIX/tmp; "
    "mkdir -p $TMPDIR; "
)


# --------------------------------------------------------------------------- #
# SSH (paramiko)
# --------------------------------------------------------------------------- #

def proxy_address(own) -> str:
    """Адрес прокси: {server}:{port}; если server пуст — {ssh.host}:{port}."""
    host = (getattr(own, "server", "") or "").strip()
    if not host:
        host = (getattr(getattr(own, "ssh", None), "host", "") or "").strip()
    port = int(getattr(own, "port", 0) or 8888)
    if host and ":" not in host:
        host = f"{host}:{port}"
    return host or f"127.0.0.1:{port}"


def _connect(ssh, timeout: int = 15):
    """Открывает SSH-соединение с телефоном (paramiko)."""
    host = (getattr(ssh, "host", "") or "").strip()
    if not host:
        raise ValueError("Не задан ssh.host в [avito.own_mobile_proxy.ssh]")

    try:
        import paramiko
    except ImportError as err:
        raise RuntimeError(
            "Для своего мобильного прокси нужен paramiko: pip install paramiko"
        ) from err

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=int(getattr(ssh, "port", 0) or 8022),
        username=(getattr(ssh, "user", "") or "").strip() or None,
        password=getattr(ssh, "password", None) or None,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
        allow_agent=False,
        look_for_keys=False,
    )
    client.get_transport().set_keepalive(30)
    return client


def _run_remote(client, command: str, timeout: int = 60):
    """Выполняет команду на телефоне, возвращает (code, stdout, stderr)."""
    if isinstance(client, _AdbTermuxClient):
        return client.run(command, timeout)
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    code = stdout.channel.recv_exit_status()
    return code, out, err


def _remote_start_command(device_log: str) -> str:
    """Команда на телефоне: запустить tinyproxy через nohup."""
    return (
        REMOTE_ENV
        + f"nohup {TERMUX_PREFIX}/bin/tinyproxy -d -c {TINYPROXY_CONF} "
        + f">> {device_log} 2>&1 < /dev/null & "
        + 'echo "started pid $!"'
    )


def _remote_stop_command() -> str:
    """Остановка tinyproxy на телефоне: pkill -x tinyproxy (по полной командной строке)."""
    return REMOTE_ENV + "pkill -x tinyproxy"


def _remote_kill_command() -> str:
    """Принудительная остановка: pkill -9 -x tinyproxy."""
    return REMOTE_ENV + "pkill -9 -x tinyproxy"


def _remote_status_command() -> str:
    """Команда на телефоне: проверить, запущен ли tinyproxy."""
    return REMOTE_ENV + "pgrep -x tinyproxy >/dev/null 2>&1 && echo running || echo stopped"


def _fix_interfaces_via_ssh(client) -> bool:
    """Заливает scripts/fix_interfaces_via_ssh.sh на телефон и выполняет его.

    Скрипт настраивает маршрутизацию Termux через мобильный интерфейс и обновляет
    Bind в tinyproxy.conf (нужен root/`su` на телефоне).
    """
    if not FIX_INTERFACES_SCRIPT.exists():
        logger.warning(f"Не найден {FIX_INTERFACES_SCRIPT} — настройку сети пропускаю")
        return True

    try:
        payload = base64.b64encode(FIX_INTERFACES_SCRIPT.read_bytes()).decode("ascii")
    except OSError as err:
        logger.warning(f"Не удалось прочитать {FIX_INTERFACES_SCRIPT}: {err}")
        return False

    command = (
        REMOTE_ENV
        + f"echo {payload} | base64 -d > {REMOTE_FIX_INTERFACES_SCRIPT} "
        + f"&& chmod +x {REMOTE_FIX_INTERFACES_SCRIPT} "
        + f"&& {TERMUX_PREFIX}/bin/bash -x {REMOTE_FIX_INTERFACES_SCRIPT}"
    )
    try:
        code, out, err = _run_remote(client, command, timeout=180)
    except Exception as err:
        logger.warning(f"Ошибка выполнения fix_interfaces_via_ssh.sh: {err}")
        return False

    if out:
        logger.info(f"fix_interfaces_via_ssh.sh:\n{out}")
    if code != 0:
        logger.warning(f"fix_interfaces_via_ssh.sh завершился с кодом {code}: {err}")
        return False
    return True


def _ensure_logfile(client, device_log: str) -> bool:
    """Прописывает LogFile/Syslog в tinyproxy.conf, чтобы tinyproxy писал логи в файл.

    Без этого при `-d` сообщения могут уходить в syslog, а не в перенаправленный
    вывод nohup. Ставим `LogFile "<device_log>"` и `Syslog Off`.
    """
    log_dir = device_log.rsplit("/", 1)[0] if "/" in device_log else TERMUX_HOME
    sed_logfile = (
        'sed -i -E "s|^[[:space:]]*#?[[:space:]]*LogFile[[:space:]].*|'
        f'LogFile \\"{device_log}\\"|" {TINYPROXY_CONF}'
    )
    sed_syslog = (
        'sed -i -E "s|^[[:space:]]*#?[[:space:]]*Syslog[[:space:]].*|Syslog Off|" '
        f'{TINYPROXY_CONF}'
    )
    command = (
        REMOTE_ENV
        + "set -e; "
        + f'mkdir -p "{log_dir}"; '
        + f'if grep -qE "^[[:space:]]*#?[[:space:]]*LogFile[[:space:]]" {TINYPROXY_CONF}; '
        + f"then {sed_logfile}; else echo 'LogFile \"{device_log}\"' >> {TINYPROXY_CONF}; fi; "
        + f'if grep -qE "^[[:space:]]*#?[[:space:]]*Syslog[[:space:]]" {TINYPROXY_CONF}; '
        + f'then {sed_syslog}; else echo "Syslog Off" >> {TINYPROXY_CONF}; fi; '
        + 'echo "logfile-ok"'
    )
    try:
        code, out, err = _run_remote(client, command)
    except Exception as err:
        logger.warning(f"Не удалось настроить LogFile для tinyproxy: {err}")
        return False
    if code != 0:
        logger.warning(f"Не удалось настроить LogFile для tinyproxy (код {code}): {err}")
        return False
    return True


def _restart_tinyproxy(client, device_log: str):
    """Стоп и старт tinyproxy; настройка сети и LogFile выполняется только через SSH."""
    code, out, err = _run_remote(client, REMOTE_ENV + "pkill -x tinyproxy")
    if code not in (0, 1):  # 1: процесс уже остановлен
        return False, err or out
    time.sleep(1)
    if not isinstance(client, _AdbTermuxClient):
        if not _fix_interfaces_via_ssh(client):
            return False, "Не удалось обновить сеть и Bind"
        if not _ensure_logfile(client, device_log):
            return False, "Не удалось настроить лог tinyproxy"
    code, out, err = _run_remote(client, _remote_start_command(device_log))
    if code != 0:
        logger.warning(f"Не удалось запустить tinyproxy (код {code}): {err}")
        return False, (err or out)
    time.sleep(1)
    status, state, error = _run_remote(client, _remote_status_command())
    return status == 0 and state.strip() == "running", error or state or out


# --------------------------------------------------------------------------- #
# Стрим лога tinyproxy с телефона на хост
# --------------------------------------------------------------------------- #

def _read_pid(path) -> int | None:
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    _reap(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _reap(pid) -> None:
    """Подбирает zombie-ребёнка (если процесс — наш потомок), иначе no-op."""
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


def _kill_pid(pid, sig) -> None:
    try:
        os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def stream_remote_log(own, remote_log: str, local_log: str = str(LOCAL_LOG),
                      retry_delay: int = 5) -> None:
    """Бесконечно стримит `remote_log` с телефона в `local_log` (tail -F через выбранный транспорт).

    Переподключается при обрыве соединения и переживает перезапуски tinyproxy.
    """
    Path(local_log).parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            client = _open_control(own)
        except Exception as err:
            logger.warning(f"Лог tinyproxy: не подключиться через выбранный транспорт ({err}); повтор через {retry_delay}с")
            time.sleep(retry_delay)
            continue
        try:
            if isinstance(client, _AdbTermuxClient):
                command = REMOTE_ENV + "exec tail -n +1 -F " + shlex.quote(remote_log)
                with open(local_log, "ab") as output:
                    code = stream_adb(client.serial, ["shell", client.shell_command(command)], output)
                raise RuntimeError(f"ADB log stream завершился с кодом {code}")
            channel = client.get_transport().open_session()
            channel.set_combine_stderr(True)
            channel.exec_command(REMOTE_ENV + "tail -n +1 -F " + shlex.quote(remote_log))
            with open(local_log, "ab") as fh:
                while True:
                    data = channel.recv(65536)
                    if not data:
                        break
                    fh.write(data)
                    fh.flush()
        except Exception as err:
            logger.warning(f"Лог tinyproxy: обрыв стрима ({err}); повтор через {retry_delay}с")
        finally:
            try:
                client.close()
            except Exception:
                pass
        time.sleep(retry_delay)


def _start_log_follower(config_path: str, remote_log: str) -> None:
    """Запускает фоновый процесс, который пишет лог tinyproxy с телефона в logs/tinyproxy.log."""
    pid = _read_pid(FOLLOW_PID)
    if _pid_alive(pid):
        return
    if not FOLLOWER_SCRIPT.exists():
        logger.warning(f"Не найден {FOLLOWER_SCRIPT} — лог tinyproxy на хост не стримится")
        return

    LOGS_DIR.mkdir(exist_ok=True)
    cmd = [sys.executable, str(FOLLOWER_SCRIPT),
           "--config", str(config_path), "--remote-log", remote_log]
    log = open(FOLLOW_LOG, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd, cwd=ROOT, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
    finally:
        log.close()

    FOLLOW_PID.write_text(str(proc.pid))
    logger.info(f"Лог tinyproxy стримится на хост: logs/{LOCAL_LOG.name} (pid {proc.pid})")


def _stop_log_follower() -> None:
    """Останавливает фоновый стрим лога tinyproxy."""
    pid = _read_pid(FOLLOW_PID)
    if pid and _pid_alive(pid):
        _kill_pid(pid, signal.SIGTERM)
        for _ in range(20):
            if not _pid_alive(pid):
                break
            time.sleep(0.25)
        if _pid_alive(pid):
            _kill_pid(pid, signal.SIGKILL)
            _reap(pid)
    FOLLOW_PID.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Публичный API
# --------------------------------------------------------------------------- #

def start_proxy(config, device_log: str = DEFAULT_DEVICE_LOG,
                config_path: str = DEFAULT_CONFIG) -> int:
    """Запускает tinyproxy на телефоне через nohup. Старый процесс останавливается."""
    own = getattr(config, "own_mobile_proxy", None)
    if own is None or not getattr(own, "use", False):
        print("own_mobile_proxy.use = false — свой мобильный прокси не запускается.")
        return 0

    print(f"Управление телефоном: {own.transport}")
    print(f"Прокси для парсера: {proxy_address(own)}")

    try:
        client = _open_control(own)
    except Exception as err:
        print(f"❌ Не удалось подключиться через выбранный транспорт: {err}", file=sys.stderr)
        return 1

    try:
        ok, out = _restart_tinyproxy(client, device_log)
    except Exception as err:
        print(f"❌ Ошибка выполнения команды через выбранный транспорт: {err}", file=sys.stderr)
        return 1
    finally:
        client.close()

    if out:
        print(out)
    if not ok:
        print("❌ Не удалось запустить tinyproxy на телефоне", file=sys.stderr)
        return 1

    _start_log_follower(config_path, device_log)
    print(f"tinyproxy запущен на телефоне (nohup, транспорт {own.transport}). "
          f"Лог на телефоне: {device_log}; стрим на хост: logs/{LOCAL_LOG.name}")
    return 0


def stop_proxy(config, force: bool = False) -> int:
    """Останавливает tinyproxy на телефоне через выбранный транспорт. Возвращает код выхода.

    force=True — останавливать даже если `[avito.own_mobile_proxy].use = false`
    (очистка оставшихся процессов; нужен заданный ssh.host).
    """
    own = getattr(config, "own_mobile_proxy", None)
    if own is None:
        return 0
    if not getattr(own, "use", False) and not force:
        return 0

    _stop_log_follower()

    try:
        client = _open_control(own)
    except Exception as err:
        print(f"⚠️ Не удалось подключиться через выбранный транспорт для остановки: {err}", file=sys.stderr)
        return 1

    try:
        _run_remote(client, _remote_stop_command())
        code, out, _ = _run_remote(client, _remote_status_command())
    except Exception as err:
        print(f"⚠️ Ошибка остановки через выбранный транспорт: {err}", file=sys.stderr)
        return 1
    finally:
        client.close()

    if code != 0 or out.strip() != "stopped":
        print("  proxy: tinyproxy не остановился, пробую SIGKILL...")
        try:
            client2 = _open_control(own)
            try:
                _run_remote(client2, _remote_kill_command())
                code, out, _ = _run_remote(client2, _remote_status_command())
            finally:
                client2.close()
        except Exception as err:
            print(f"  ⚠️ SIGKILL не удался: {err}", file=sys.stderr)

    if code != 0 or out.strip() != "stopped":
        print("  ⚠️ tinyproxy всё ещё запущен на телефоне", file=sys.stderr)
        return 1
    print("    tinyproxy остановлен (pkill -x tinyproxy)")
    return 0


def service_running(config) -> bool:
    """True, если tinyproxy уже запущен на телефоне (проверка через выбранный транспорт)."""
    own = getattr(config, "own_mobile_proxy", None)
    if own is None or not getattr(own, "use", False):
        return False
    try:
        client = _open_control(own)
    except Exception:
        return False
    try:
        code, out, _ = _run_remote(client, _remote_status_command())
    except Exception:
        return False
    finally:
        client.close()
    return code == 0 and out.strip() == "running"


def _open_control(own):
    if own.transport == "adb":
        return _AdbTermuxClient(own.adb_serial)
    if own.transport == "ssh":
        return _connect(own.ssh)
    raise ValueError("own_mobile_proxy.transport должен быть ssh или adb")


def _rotate_airplane_ssh(ssh, on_sleep=AIRPLANE_ON_SLEEP, off_sleep=AIRPLANE_OFF_SLEEP):
    """Оба переключения выполняются на телефоне даже при потере SSH-соединения."""
    marker = f"{TERMUX_HOME}/.airplane-{uuid.uuid4().hex}"
    # Выключение выполняется даже при ошибке включения; результат пишется после него.
    script = (
        "cmd connectivity airplane-mode enable; enabled=$?; "
        f"sleep {float(on_sleep)}; "
        "cmd connectivity airplane-mode disable; disabled=$?; "
        "test $enabled -eq 0 && test $disabled -eq 0"
    )
    job = f"su -c {shlex.quote(script)}; echo $? > {shlex.quote(marker)}"
    command = (REMOTE_ENV + f"nohup {TERMUX_PREFIX}/bin/bash -c {shlex.quote(job)} "
               ">/dev/null 2>&1 </dev/null &")
    client = None
    try:
        client = _connect(ssh)
        try:
            code, _, _ = _run_remote(client, command)
            if code != 0:
                return False
        except (OSError, EOFError):
            # Режим полёта мог оборвать SSH после запуска фоновой команды.
            pass
        client.close()
        client = None
        time.sleep(on_sleep + off_sleep)
        client = _connect(ssh)
        code, out, _ = _run_remote(client, REMOTE_ENV +
            f"cat {shlex.quote(marker)}; result=$?; rm -f {shlex.quote(marker)}; exit $result")
        return code == 0 and out.strip() == "0"
    except Exception as err:
        logger.warning(f"Смена IP через SSH не удалась: {err}")
        return False
    finally:
        if client is not None:
            client.close()


def set_airplane_adb(adb_serial, enable: bool) -> bool:
    """Переключение через Android connectivity service с root, без protected broadcast."""
    action = "enable" if enable else "disable"
    result = _adb(adb_serial, "shell", "su -c " + shlex.quote(
        f"cmd connectivity airplane-mode {action}"))
    if result is None or result.returncode != 0:
        error = ((result.stderr.strip() or result.stdout.strip())
                 if result is not None else "ADB недоступен или timeout")
        logger.warning(f"Режим полёта ({action}) не переключён: {error}")
        return False
    return True


def _rotate_airplane(adb_serial) -> bool:
    """Режим полёта через adb: включить → подождать → выключить → подождать."""
    device = f"adb -s {adb_serial}" if adb_serial else "adb"

    state = _adb(adb_serial, "get-state")
    if state is None or state.returncode != 0:
        err = (state.stderr.strip() if state is not None else "adb недоступен")
        logger.warning(f"Смена IP: устройство не найдено ({device}): {err}")
        return False

    logger.info(f"🔄 Смена IP через {device}: включаю режим полёта...")
    if not set_airplane_adb(adb_serial, True):
        return False
    try:
        time.sleep(AIRPLANE_ON_SLEEP)
    finally:
        logger.info("🔄 Возвращаю обычный режим...")
        off = set_airplane_adb(adb_serial, False)
    if not off:
        return False
    time.sleep(AIRPLANE_OFF_SLEEP)
    return True


class _AdbTermuxClient:
    """ADB → su UID → run-as com.termux → login shell Termux."""

    def __init__(self, serial):
        self.serial = serial
        result = _adb(serial, "shell", "su -c " + shlex.quote(
            f"/system/bin/stat -c %u {TERMUX_HOME}"))
        if result is None or result.returncode != 0:
            raise RuntimeError("ADB: нужен разрешённый root-доступ (su) и установленный Termux; "
                               + (result.stderr.strip() if result is not None else "см. logs/adb.log"))
        uid = result.stdout.strip()
        if not uid.isdecimal() or int(uid) < 10000:
            raise RuntimeError("ADB: не удалось определить UID приложения Termux")
        self.uid = uid

    def shell_command(self, command):
        # Общие команды содержат окружение для SSH; ADB использует login shell Termux.
        command = command.removeprefix(REMOTE_ENV)
        return shlex.join(["su", self.uid, "run-as", "com.termux",
                           "/usr/bin/bash", "-lc", command])

    def run(self, command, timeout=60):
        result = _adb(self.serial, "shell", self.shell_command(command), timeout=timeout)
        if result is None:
            raise RuntimeError("ADB: команда Termux не выполнена или истёк timeout")
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def close(self):
        pass


def rotate_ip(adb_serial=None, ssh=None, device_log: str = DEFAULT_DEVICE_LOG,
              transport: str = "ssh") -> bool:
    """Смена IP своего прокси.

    1. режим полёта и обратно через выбранный транспорт;
    2. стоп и старт tinyproxy; при SSH — сначала fix_interfaces_via_ssh.sh.
    """
    if transport not in ("ssh", "adb"):
        raise ValueError("transport должен быть ssh или adb")
    if not (_rotate_airplane(adb_serial) if transport == "adb" else _rotate_airplane_ssh(ssh)):
        return False

    if transport == "ssh" and (ssh is None or not (getattr(ssh, "host", "") or "").strip()):
        logger.warning("Смена IP: не задан SSH — tinyproxy не перезапущен (Bind останется старым)")
        return False

    logger.info(f"🔧 Перезапускаю tinyproxy через {transport}...")
    try:
        client = _AdbTermuxClient(adb_serial) if transport == "adb" else _connect(ssh)
    except Exception as err:
        logger.warning(f"Смена IP: подключение через {transport} для перезапуска tinyproxy не удалось: {err}")
        return False
    try:
        ok, out = _restart_tinyproxy(client, device_log)
    except Exception as err:
        logger.warning(f"Смена IP: ошибка перезапуска tinyproxy: {err}")
        return False
    finally:
        client.close()

    if out:
        logger.info(f"tinyproxy: {out}")
    if ok:
        logger.success("IP обновлён: режим полёта выключен, tinyproxy перезапущен")
    return ok


def ensure_own_mobile_proxy(config, config_path: str = DEFAULT_CONFIG) -> bool:
    """Поднимает свой мобильный прокси, если `[avito.own_mobile_proxy].use = true`.

    Если tinyproxy уже работает на телефоне — не трогает его, но гарантирует, что
    его лог стримится на хост. Иначе запускает через nohup (старый процесс при этом
    останавливается).
    Возвращает True, если прокси включён в конфиге, иначе False.
    """
    own = getattr(config, "own_mobile_proxy", None)
    if not getattr(own, "use", False):
        return False

    if service_running(config):
        logger.info("Свой мобильный прокси уже запущен на телефоне")
        _start_log_follower(config_path, DEFAULT_DEVICE_LOG)
        return True

    if start_proxy(config, config_path=config_path) != 0:
        raise RuntimeError("Не удалось запустить свой мобильный прокси")
    return True
