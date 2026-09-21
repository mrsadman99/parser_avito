"""Единая точка запуска ADB-прокси (tinyproxy/microsocks на телефоне).

Если в config.toml включён `[avito.adb_proxy].use`, запускает
`scripts/start_adb_proxy.py` (идемпотентно: скрипт сам проверяет tmux-сессию
и `pgrep tinyproxy` на устройстве). Используется парсером (`AvitoParse`) и
скриптами, работающими через этот прокси.
"""
import subprocess
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "scripts" / "start_adb_proxy.py"


def ensure_adb_proxy(config, config_path: str = "config.toml", attach: bool = False) -> bool:
    """Запускает ADB-прокси, если `[avito.adb_proxy].use = true`. Идемпотентно.

    Возвращает True, если ADB-прокси включён в конфиге, иначе False.
    """
    if not getattr(getattr(config, "adb_proxy", None), "use", False):
        return False

    if not STARTER.exists():
        logger.warning(f"ADB-прокси включён, но не найден скрипт {STARTER}")
        return True

    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path

    cmd = [sys.executable, str(STARTER), "--config", str(cfg_path)]
    if not attach:
        cmd.append("--no-attach")

    logger.info("Запускаю ADB-прокси (scripts/start_adb_proxy.py)...")
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        logger.warning("Не удалось запустить ADB-прокси: python не найден")
    return True
