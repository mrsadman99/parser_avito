"""Единая точка запуска/остановки своего мобильного прокси.

Свой мобильный прокси — это tinyproxy на телефоне (Termux). Запускается по SSH
через `nohup ... &` (без tmux): процесс живёт на телефоне независимо от SSH-сессии.
При каждом запуске старый tinyproxy сначала останавливается (`pkill -x tinyproxy`),
затем запускается новый.

Смена IP — перевод телефона в режим полёта и обратно **через adb**
(`adb shell settings put global airplane_mode_on …`). После смены IP и при каждом
запуске tinyproxy на телефоне выполняется `scripts/update_network.sh`
(маршрутизация Termux через мобильный интерфейс + обновление Bind в tinyproxy.conf):
стоп tinyproxy → update_network.sh → старт tinyproxy.

Порты НЕ пробрасываются (никакого `adb forward`): адрес прокси собирается из
`own_mobile_proxy.server` и `own_mobile_proxy.port` (пусто = `ssh.host`), парсер
обращается туда напрямую.

Настройки берутся из config.toml:

    [avito.own_mobile_proxy]
    use = true
    port = 8888
    adb_serial = ""          # серийник для adb (пусто — adb без -s)

    [avito.own_mobile_proxy.ssh]
    host = "192.168.1.50"
    port = 8022
    user = "u0_a123"
    password = "..."

Для SSH используется paramiko (pip install paramiko), для режима полёта — adb в PATH.
"""
import base64
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
UPDATE_NETWORK_SCRIPT = ROOT / "scripts" / "update_network.sh"

TERMUX_PREFIX = "/data/data/com.termux/files/usr"
TERMUX_HOME = "/data/data/com.termux/files/home"
TINYPROXY_CONF = f"{TERMUX_PREFIX}/etc/tinyproxy/tinyproxy.conf"
DEFAULT_DEVICE_LOG = f"{TERMUX_HOME}/tinyproxy.log"
REMOTE_UPDATE_SCRIPT = f"{TERMUX_HOME}/update_network.sh"

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
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    code = stdout.channel.recv_exit_status()
    return code, out, err


def _remote_start_command(device_log: str) -> str:
    """Команда на телефоне: остановить старый tinyproxy и запустить новый через nohup."""
    return (
        REMOTE_ENV
        + "pkill -x tinyproxy 2>/dev/null; sleep 1; "
        + f"nohup {TERMUX_PREFIX}/bin/tinyproxy -d -c {TINYPROXY_CONF} "
        + f">> {device_log} 2>&1 < /dev/null & "
        + 'echo "started pid $!"'
    )


def _remote_stop_command() -> str:
    """Команда на телефоне: остановить tinyproxy."""
    return REMOTE_ENV + "pkill -x tinyproxy 2>/dev/null; echo stopped"


def _remote_status_command() -> str:
    """Команда на телефоне: проверить, запущен ли tinyproxy."""
    return REMOTE_ENV + "pgrep -x tinyproxy >/dev/null 2>&1 && echo running || echo stopped"


def _update_network(client) -> bool:
    """Заливает scripts/update_network.sh на телефон и выполняет его.

    Скрипт настраивает маршрутизацию Termux через мобильный интерфейс и обновляет
    Bind в tinyproxy.conf (нужен root/`su` на телефоне).
    """
    if not UPDATE_NETWORK_SCRIPT.exists():
        logger.warning(f"Не найден {UPDATE_NETWORK_SCRIPT} — настройку сети пропускаю")
        return True

    try:
        payload = base64.b64encode(UPDATE_NETWORK_SCRIPT.read_bytes()).decode("ascii")
    except OSError as err:
        logger.warning(f"Не удалось прочитать {UPDATE_NETWORK_SCRIPT}: {err}")
        return False

    command = (
        REMOTE_ENV
        + f"echo {payload} | base64 -d > {REMOTE_UPDATE_SCRIPT} "
        + f"&& chmod +x {REMOTE_UPDATE_SCRIPT} "
        + f"&& {TERMUX_PREFIX}/bin/bash {REMOTE_UPDATE_SCRIPT}"
    )
    try:
        code, out, err = _run_remote(client, command, timeout=180)
    except Exception as err:
        logger.warning(f"Ошибка выполнения update_network.sh: {err}")
        return False

    if out:
        logger.info(f"update_network.sh:\n{out}")
    if code != 0:
        logger.warning(f"update_network.sh завершился с кодом {code}: {err}")
        return False
    return True


def _restart_tinyproxy(client, device_log: str):
    """Стоп tinyproxy → update_network.sh → старт tinyproxy. Возвращает (ok, output)."""
    _run_remote(client, _remote_stop_command())
    _update_network(client)
    code, out, err = _run_remote(client, _remote_start_command(device_log))
    if code != 0:
        logger.warning(f"Не удалось запустить tinyproxy (код {code}): {err}")
        return False, (err or out)
    return True, out


# --------------------------------------------------------------------------- #
# Публичный API
# --------------------------------------------------------------------------- #

def start_proxy(config, device_log: str = DEFAULT_DEVICE_LOG) -> int:
    """Запускает tinyproxy на телефоне через nohup. Старый процесс останавливается."""
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
    print(f"SSH: {user}@{host}:{port} → nohup tinyproxy -d")
    print(f"Прокси для парсера: {proxy_address(own)}")

    try:
        client = _connect(ssh)
    except Exception as err:
        print(f"❌ Не удалось подключиться по SSH: {err}", file=sys.stderr)
        return 1

    try:
        ok, out = _restart_tinyproxy(client, device_log)
    except Exception as err:
        print(f"❌ Ошибка выполнения команды по SSH: {err}", file=sys.stderr)
        return 1
    finally:
        client.close()

    if out:
        print(out)
    if not ok:
        print("❌ Не удалось запустить tinyproxy на телефоне", file=sys.stderr)
        return 1

    print(f"tinyproxy запущен на телефоне (nohup), update_network.sh выполнен. "
          f"Лог на телефоне: {device_log}")
    return 0


def stop_proxy(config) -> int:
    """Останавливает tinyproxy на телефоне по SSH. Возвращает код выхода."""
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


def service_running(config) -> bool:
    """True, если tinyproxy уже запущен на телефоне (проверка по SSH)."""
    own = getattr(config, "own_mobile_proxy", None)
    if own is None or not getattr(own, "use", False):
        return False
    if not (getattr(getattr(own, "ssh", None), "host", "") or "").strip():
        return False

    try:
        client = _connect(own.ssh)
    except Exception:
        return False
    try:
        _, out, _ = _run_remote(client, _remote_status_command())
    except Exception:
        return False
    finally:
        client.close()
    return "running" in out


def _adb(adb_serial, *args, timeout: int = 30):
    """Выполняет команду adb (с -s adb_serial, если задан). Возвращает CompletedProcess или None."""
    cmd = ["adb"] + (["-s", str(adb_serial)] if adb_serial else []) + list(args)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        logger.warning("adb не найден в PATH — смена IP недоступна")
        return None
    except Exception as err:
        logger.warning(f"Ошибка adb {list(args)}: {err}")
        return None


def _rotate_airplane(adb_serial) -> bool:
    """Режим полёта через adb: включить → подождать → выключить → подождать."""
    device = f"adb -s {adb_serial}" if adb_serial else "adb"

    state = _adb(adb_serial, "get-state")
    if state is None or state.returncode != 0:
        err = (state.stderr.strip() if state is not None else "adb недоступен")
        logger.warning(f"Смена IP: устройство не найдено ({device}): {err}")
        return False

    logger.info(f"🔄 Смена IP через {device}: включаю режим полёта...")
    on = _adb(adb_serial, "shell", "settings", "put", "global", "airplane_mode_on", "1")
    if on is None or on.returncode != 0:
        logger.warning(f"Не удалось включить режим полёта: {(on.stderr.strip() if on else 'adb недоступен')}")
        return False
    _adb(adb_serial, "shell", "am", "broadcast",
         "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", "true")
    time.sleep(AIRPLANE_ON_SLEEP)

    logger.info("🔄 Возвращаю обычный режим...")
    off = _adb(adb_serial, "shell", "settings", "put", "global", "airplane_mode_on", "0")
    if off is None or off.returncode != 0:
        logger.warning(f"Не удалось выключить режим полёта: {(off.stderr.strip() if off else 'adb недоступен')}")
        return False
    _adb(adb_serial, "shell", "am", "broadcast",
         "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", "false")
    time.sleep(AIRPLANE_OFF_SLEEP)
    return True


def rotate_ip(adb_serial=None, ssh=None, device_log: str = DEFAULT_DEVICE_LOG) -> bool:
    """Смена IP своего прокси.

    1. режим полёта и обратно через adb;
    2. стоп tinyproxy → update_network.sh → старт tinyproxy (по SSH).
    """
    if not _rotate_airplane(adb_serial):
        return False

    if ssh is None or not (getattr(ssh, "host", "") or "").strip():
        logger.warning("Смена IP: не задан SSH — tinyproxy не перезапущен (Bind останется старым)")
        return False

    logger.info("🔧 Перезапускаю tinyproxy: стоп → update_network.sh → старт...")
    try:
        client = _connect(ssh)
    except Exception as err:
        logger.warning(f"Смена IP: не удалось подключиться по SSH для перезапуска tinyproxy: {err}")
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


def ensure_own_mobile_proxy(config) -> bool:
    """Поднимает свой мобильный прокси, если `[avito.own_mobile_proxy].use = true`.

    Если tinyproxy уже работает на телефоне — не трогает его. Иначе запускает через
    nohup (старый процесс при этом останавливается).
    Возвращает True, если прокси включён в конфиге, иначе False.
    """
    own = getattr(config, "own_mobile_proxy", None)
    if not getattr(own, "use", False):
        return False

    if service_running(config):
        logger.info("Свой мобильный прокси уже запущен на телефоне")
        return True

    start_proxy(config)
    return True
