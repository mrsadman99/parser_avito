"""Единая точка запуска/остановки своего мобильного прокси.

Свой мобильный прокси — это tinyproxy на телефоне (Termux), запущенный в tmux-сессии
по SSH. Порты НЕ пробрасываются (никакого `adb forward`): парсер обращается к
`{ssh.host}:{own_mobile_proxy.port}` напрямую.

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
import subprocess
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "scripts" / "start_own_proxy.py"

SESSION_NAME = "proxy"
TERMUX_PREFIX = "/data/data/com.termux/files/usr"
TERMUX_HOME = "/data/data/com.termux/files/home"
TINYPROXY_CONF = f"{TERMUX_PREFIX}/etc/tinyproxy/tinyproxy.conf"
DEFAULT_DEVICE_LOG = "/sdcard/tinyproxy.log"

REMOTE_ENV = (
    f"export PREFIX={TERMUX_PREFIX}; "
    f"export HOME={TERMUX_HOME}; "
    "export PATH=$PREFIX/bin:$PATH; "
    "export LD_LIBRARY_PATH=$PREFIX/lib; "
    "export TMPDIR=$PREFIX/tmp; "
    "mkdir -p $TMPDIR; "
)


def _connect(ssh, timeout: int = 15):
    """Открывает SSH-соединение с телефоном (paramiko)."""
    try:
        import paramiko
    except ImportError as err:
        raise RuntimeError(
            "Для своего мобильного прокси нужен paramiko: pip install paramiko"
        ) from err

    host = (getattr(ssh, "host", "") or "").strip()
    if not host:
        raise ValueError("Не задан ssh.host в [avito.own_mobile_proxy.ssh]")

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
    return client


def _run_remote(client, command: str, timeout: int = 60):
    """Выполняет команду на телефоне, возвращает (code, stdout, stderr)."""
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    code = stdout.channel.recv_exit_status()
    return code, out, err


def _start_script(device_log: str) -> str:
    """Команда на телефоне: запустить tinyproxy в tmux-сессии (идемпотентно)."""
    return (
        REMOTE_ENV
        + f'if tmux has-session -t {SESSION_NAME} 2>/dev/null; then echo "already-running"; '
        + "elif "
        + f'tmux new-session -d -s {SESSION_NAME} "{TERMUX_PREFIX}/bin/tinyproxy -d -c {TINYPROXY_CONF}"; then '
        + f'tmux pipe-pane -t {SESSION_NAME} "cat >> {device_log}" 2>/dev/null || true; '
        + 'echo "started"; '
        + 'else echo "start-failed"; fi'
    )


def _stop_script() -> str:
    """Команда на телефоне: закрыть tmux-сессию и убить tinyproxy."""
    return (
        REMOTE_ENV
        + f"tmux kill-session -t {SESSION_NAME} 2>/dev/null; "
        + "pkill -x tinyproxy 2>/dev/null; "
        + 'echo "stopped"'
    )


def _rotate_script() -> str:
    """Команда на телефоне: смена IP через airplane mode (best-effort, нужен root/tsu)."""
    return REMOTE_ENV + (
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


def start_proxy(config, device_log: str = DEFAULT_DEVICE_LOG) -> int:
    """Запускает tinyproxy на телефоне по SSH. Возвращает код выхода."""
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
    print(f"SSH: подключаюсь к {host}:{port}...")
    try:
        client = _connect(ssh)
    except Exception as err:
        print(f"❌ Не удалось подключиться по SSH: {err}", file=sys.stderr)
        return 1

    try:
        code, out, err = _run_remote(client, _start_script(device_log))
    except Exception as err:
        print(f"❌ Ошибка выполнения команды по SSH: {err}", file=sys.stderr)
        return 1
    finally:
        client.close()

    if out:
        print(out)
    if "start-failed" in out:
        print(f"❌ Не удалось запустить tinyproxy на телефоне: {err}", file=sys.stderr)
        return 1
    if code != 0:
        print(f"❌ Ошибка на телефоне (код {code}): {err}", file=sys.stderr)
        return 1

    proxy_port = int(getattr(own, "port", 0) or 8888)
    if "already-running" in out:
        print(f"tinyproxy уже запущен на телефоне ({host}:{proxy_port}).")
    else:
        print(f"tinyproxy запущен на телефоне в tmux-сессии '{SESSION_NAME}'.")
    print(f"Прокси для парсера: {host}:{proxy_port}")
    print(f"Лог на телефоне: {device_log}")
    return 0


def stop_proxy(config) -> int:
    """Останавливает tinyproxy на телефоне по SSH. Возвращает код выхода."""
    own = getattr(config, "own_mobile_proxy", None)
    if own is None or not getattr(own, "use", False):
        return 0

    ssh = getattr(own, "ssh", None)
    host = (getattr(ssh, "host", "") or "").strip()
    if not host:
        print("⚠️ Не задан ssh.host — не могу остановить прокси на телефоне", file=sys.stderr)
        return 1

    try:
        client = _connect(ssh)
    except Exception as err:
        print(f"⚠️ Не удалось подключиться по SSH для остановки: {err}", file=sys.stderr)
        return 1

    try:
        code, out, err = _run_remote(client, _stop_script())
    except Exception as err:
        print(f"⚠️ Ошибка остановки по SSH: {err}", file=sys.stderr)
        return 1
    finally:
        client.close()

    if out:
        print(f"    {out}")
    return 0 if code == 0 else 1


def rotate_ip(ssh) -> bool:
    """Меняет IP на телефоне (airplane mode) по SSH. Используется парсером."""
    try:
        client = _connect(ssh)
    except Exception as err:
        logger.warning(f"Не удалось подключиться по SSH для смены IP: {err}")
        return False

    try:
        code, out, err = _run_remote(client, _rotate_script(), timeout=120)
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


def ensure_own_mobile_proxy(config, config_path: str = "config.toml") -> bool:
    """Запускает свой мобильный прокси, если `[avito.own_mobile_proxy].use = true`.

    Идемпотентно: скрипт сам проверяет tmux-сессию на телефоне.
    Возвращает True, если прокси включён в конфиге, иначе False.
    """
    own = getattr(config, "own_mobile_proxy", None)
    if not getattr(own, "use", False):
        return False

    if not STARTER.exists():
        logger.warning(f"Свой мобильный прокси включён, но не найден скрипт {STARTER}")
        return True

    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path

    logger.info("Запускаю свой мобильный прокси (tinyproxy на телефоне по SSH)...")
    try:
        subprocess.run([sys.executable, str(STARTER), "--config", str(cfg_path)], check=False)
    except FileNotFoundError:
        logger.warning("Не удалось запустить свой мобильный прокси: python не найден")
    return True
