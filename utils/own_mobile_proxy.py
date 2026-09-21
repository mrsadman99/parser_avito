"""Единая точка запуска/остановки своего мобильного прокси.

Свой мобильный прокси — это tinyproxy на телефоне (Termux). SSH-соединение с
телефоном держит **хост, на котором стартует парсер**: tmux-сессия `proxy` (или
фоновый процесс в detached_mode) запускает `scripts/start_own_proxy.py --foreground`,
который по SSH выполняет `tinyproxy -d` и стримит его вывод. Порты НЕ пробрасываются
(никакого `adb forward`): адрес прокси собирается из `own_mobile_proxy.server` и
`own_mobile_proxy.port` (пусто = `ssh.host`), парсер обращается туда напрямую.

Настройки берутся из config.toml:

    [avito.own_mobile_proxy]
    use = true
    port = 8888

    [avito.own_mobile_proxy.ssh]
    host = "192.168.1.50"
    port = 8022
    user = "u0_a123"
    password = "..."

Для SSH используется paramiko (pip install paramiko).
"""
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "scripts" / "start_own_proxy.py"
LOGS_DIR = ROOT / "logs"

SESSION_NAME = "proxy"
DEFAULT_CONFIG = "config.toml"
TERMUX_PREFIX = "/data/data/com.termux/files/usr"
TERMUX_HOME = "/data/data/com.termux/files/home"
TINYPROXY_CONF = f"{TERMUX_PREFIX}/etc/tinyproxy/tinyproxy.conf"

REMOTE_ENV = (
    f"export PREFIX={TERMUX_PREFIX}; "
    f"export HOME={TERMUX_HOME}; "
    "export PATH=$PREFIX/bin:$PATH; "
    "export LD_LIBRARY_PATH=$PREFIX/lib; "
    "export TMPDIR=$PREFIX/tmp; "
    "mkdir -p $TMPDIR; "
)


# --------------------------------------------------------------------------- #
# SSH (paramiko)
# --------------------------------------------------------------------------- #

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
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    code = stdout.channel.recv_exit_status()
    return code, out, err


def _remote_run_command() -> str:
    """Команда на телефоне: убить старый tinyproxy и запустить новый в foreground."""
    return (
        REMOTE_ENV
        + "pkill -x tinyproxy 2>/dev/null; sleep 1; "
        + f"exec {TERMUX_PREFIX}/bin/tinyproxy -d -c {TINYPROXY_CONF}"
    )


def _remote_stop_command() -> str:
    """Команда на телефоне: остановить tinyproxy."""
    return REMOTE_ENV + "pkill -x tinyproxy 2>/dev/null; echo stopped"


# --------------------------------------------------------------------------- #
# Foreground-раннер (выполняется внутри tmux/фонового процесса на хосте)
# --------------------------------------------------------------------------- #

def run_foreground(config) -> int:
    """Держит SSH-соединение с телефоном и стримит вывод `tinyproxy -d`."""
    own = getattr(config, "own_mobile_proxy", None)
    if own is None or not getattr(own, "use", False):
        print("own_mobile_proxy.use = false — свой мобильный прокси не запускается.")
        return 0

    ssh = getattr(own, "ssh", None)
    host = (getattr(ssh, "host", "") or "").strip()
    if not host:
        print("❌ Не задан ssh.host в [avito.own_mobile_proxy.ssh]", file=sys.stderr)
        return 1

    port = int(getattr(ssh, "port", 0) or 8022)
    user = (getattr(ssh, "user", "") or "").strip() or "?"
    proxy_port = int(getattr(own, "port", 0) or 8888)
    print(f"SSH: {user}@{host}:{port} → tinyproxy -d (tmux на хосте)")
    print(f"Прокси для парсера: {host}:{proxy_port}")

    try:
        client = _connect(ssh)
    except Exception as err:
        print(f"❌ Не удалось подключиться по SSH: {err}", file=sys.stderr)
        return 1

    code = 0
    try:
        channel = client.get_transport().open_session()
        channel.set_combine_stderr(True)
        channel.exec_command(_remote_run_command())
        while True:
            data = channel.recv(4096)
            if not data:
                break
            sys.stdout.write(data.decode("utf-8", "replace"))
            sys.stdout.flush()
        code = channel.recv_exit_status()
    except KeyboardInterrupt:
        code = 0
    finally:
        client.close()

    print(f"\nSSH-сессия с телефоном закрыта (код {code}).")
    return code


# --------------------------------------------------------------------------- #
# Управление сервисом на хосте
# --------------------------------------------------------------------------- #

def _read_pid(path: Path):
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _tmux_has_session(name: str) -> bool:
    try:
        return subprocess.run(
            ["tmux", "has-session", "-t", name], capture_output=True
        ).returncode == 0
    except FileNotFoundError:
        return False


def service_running() -> bool:
    """True, если на хосте уже работает tmux-сессия/фоновый процесс proxy."""
    if _tmux_has_session(SESSION_NAME):
        return True
    pid = _read_pid(LOGS_DIR / f"{SESSION_NAME}.pid")
    return bool(pid and _pid_alive(pid))


def start_service(config, config_path: str = DEFAULT_CONFIG) -> int:
    """Запускает свой мобильный прокси на ХОСТЕ (tmux-сессия или фон) и возвращает код."""
    own = getattr(config, "own_mobile_proxy", None)
    if own is None or not getattr(own, "use", False):
        print("own_mobile_proxy.use = false — свой мобильный прокси не запускается.")
        return 0

    host = (getattr(getattr(own, "ssh", None), "host", "") or "").strip()
    if not host:
        print("❌ Не задан ssh.host в [avito.own_mobile_proxy.ssh]", file=sys.stderr)
        return 1

    if service_running():
        print(f"Свой мобильный прокси уже запущен (tmux-сессия '{SESSION_NAME}' или фоновый процесс).")
        return 0

    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    cmd = [sys.executable, str(STARTER), "--foreground", "--config", str(cfg_path)]

    LOGS_DIR.mkdir(exist_ok=True)
    log_path = LOGS_DIR / "proxy.log"

    if bool(getattr(config, "detached_mode", False)):
        log = open(log_path, "a", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                cmd, cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
        finally:
            log.close()
        (LOGS_DIR / f"{SESSION_NAME}.pid").write_text(str(proc.pid))
        print(f"Свой мобильный прокси: фоновый процесс (pid {proc.pid}, лог logs/proxy.log)")
        return 0

    try:
        shell_cmd = " ".join(shlex.quote(str(c)) for c in cmd)
        result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", SESSION_NAME, "-c", str(ROOT), shell_cmd],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        print("❌ tmux не найден на хосте. Установите tmux или включите detached_mode = true",
              file=sys.stderr)
        return 1

    if result.returncode != 0:
        print(f"❌ Не удалось создать tmux-сессию: {result.stderr.strip()}", file=sys.stderr)
        return 1

    subprocess.run(
        ["tmux", "pipe-pane", "-t", SESSION_NAME, f"cat >> '{log_path}'"],
        check=False,
    )
    print(f"Свой мобильный прокси: tmux-сессия '{SESSION_NAME}' (tmux attach -t {SESSION_NAME}); "
          f"лог: logs/proxy.log")
    return 0


def _kill_local_service() -> None:
    if _tmux_has_session(SESSION_NAME):
        subprocess.run(["tmux", "kill-session", "-t", SESSION_NAME], check=False)
        print(f"  proxy: tmux-сессия '{SESSION_NAME}' закрыта")

    pid_file = LOGS_DIR / f"{SESSION_NAME}.pid"
    pid = _read_pid(pid_file)
    if pid and _pid_alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        for _ in range(20):
            if not _pid_alive(pid):
                break
            time.sleep(0.25)
        if _pid_alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except OSError:
                pass
        print("  proxy: фоновый процесс остановлен")
    if pid_file.exists():
        pid_file.unlink(missing_ok=True)


def stop_proxy(config) -> int:
    """Best-effort остановка tinyproxy на телефоне по SSH. Возвращает код выхода."""
    own = getattr(config, "own_mobile_proxy", None)
    if own is None or not getattr(own, "use", False):
        return 0

    ssh = getattr(own, "ssh", None)
    if not (getattr(ssh, "host", "") or "").strip():
        print("⚠️ Не задан ssh.host — не могу остановить tinyproxy на телефоне", file=sys.stderr)
        return 1

    try:
        client = _connect(ssh)
    except Exception as err:
        print(f"⚠️ Не удалось подключиться по SSH для остановки: {err}", file=sys.stderr)
        return 1

    try:
        code, out, err = _run_remote(client, _remote_stop_command())
    except Exception as err:
        print(f"⚠️ Ошибка остановки по SSH: {err}", file=sys.stderr)
        return 1
    finally:
        client.close()

    if out:
        print(f"    {out}")
    return 0 if code == 0 else 1


def stop_service(config) -> None:
    """Останавливает локальный сервис прокси (tmux/фон) и tinyproxy на телефоне."""
    _kill_local_service()
    stop_proxy(config)


def rotate_ip(ssh) -> bool:
    """Меняет IP на телефоне (airplane mode) по SSH. Используется парсером."""
    try:
        client = _connect(ssh)
    except Exception as err:
        logger.warning(f"Не удалось подключиться по SSH для смены IP: {err}")
        return False

    rotate_script = REMOTE_ENV + (
        'SUDO=""; '
        'if command -v tsu >/dev/null 2>&1; then SUDO="tsu -c"; '
        'elif command -v su >/dev/null 2>&1; then SUDO="su -c"; fi; '
        '_run() { if [ -n "$SUDO" ]; then $SUDO "$1"; else sh -c "$1"; fi; }; '
        "_run 'settings put global airplane_mode_on 1'; "
        "_run 'am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true'; "
        "sleep 3; "
        "_run 'settings put global airplane_mode_on 0'; "
        "_run 'am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false'; "
        "sleep 8; "
        'echo "rotated"'
    )
    try:
        code, out, err = _run_remote(client, rotate_script, timeout=120)
    except Exception as err:
        logger.warning(f"Ошибка смены IP по SSH: {err}")
        return False
    finally:
        client.close()

    if code == 0 and "rotated" in out:
        logger.success("IP обновлён через SSH (airplane mode на телефоне)")
        return True
    logger.warning(f"Не удалось сменить IP на телефоне (код {code}): {err}")
    return False


def ensure_own_mobile_proxy(config, config_path: str = DEFAULT_CONFIG) -> bool:
    """Поднимает свой мобильный прокси на ХОСТЕ, если `[avito.own_mobile_proxy].use = true`.

    Идемпотентно: если tmux-сессия/фоновый процесс уже работают — ничего не делает.
    Возвращает True, если прокси включён в конфиге, иначе False.
    """
    own = getattr(config, "own_mobile_proxy", None)
    if not getattr(own, "use", False):
        return False

    if not STARTER.exists():
        logger.warning(f"Свой мобильный прокси включён, но не найден скрипт {STARTER}")
        return True

    start_service(config, config_path)
    return True
