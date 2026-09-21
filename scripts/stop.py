#!/usr/bin/env python3
"""Остановка парсера и всех сопутствующих процессов, запущенных run.py.

Что останавливается:
  * фоновые (detached_mode) процессы api / web / parser — по pid-файлам logs/*.pid
    (убивается вся группа процессов);
  * tmux-сессии (обычный режим): parser, api, web;
  * свой мобильный прокси: tinyproxy на телефоне (nohup, по SSH), если включён
    [avito.own_mobile_proxy].use.

Запуск:
    python scripts/stop.py                 # остановить всё
    python scripts/stop.py --dry-run       # только показать, что будет остановлено
    python scripts/stop.py --keep-proxy    # не трогать прокси на телефоне
"""
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"

# порядок важен: сначала парсер, потом api/web
PID_NAMES = ["parser", "api", "web"]
TMUX_SESSIONS = ["parser", "api", "web"]

# маркеры в командной строке процесса (чтобы не убить чужой pid при переиспользовании)
PID_MARKERS = {
    "parser": ["run_parser.py"],
    "api": ["uvicorn", "server.main"],
    "web": ["vite", "npm"],
}


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


def _pid_cmdline(pid: int) -> str:
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
        ).stdout.strip()
        return out
    except Exception:
        return ""


def _kill_group(pid: int, sig: int) -> None:
    try:
        os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def stop_detached(name: str, dry_run: bool) -> None:
    pid_file = LOGS_DIR / f"{name}.pid"
    pid = _read_pid(pid_file)
    if not pid:
        return

    if not _pid_alive(pid):
        print(f"  {name}: процесс {pid} уже не работает (чищу pid-файл)")
        if not dry_run:
            pid_file.unlink(missing_ok=True)
        return

    cmdline = _pid_cmdline(pid)
    markers = PID_MARKERS.get(name, [])
    if cmdline and markers and not any(m in cmdline for m in markers):
        print(f"  {name}: pid {pid} не похож на наш процесс — пропускаю ({cmdline[:80]})")
        return

    if dry_run:
        print(f"  {name}: будет остановлен (pid {pid})")
        return

    print(f"  {name}: останавливаю (pid {pid})...")
    _kill_group(pid, signal.SIGTERM)
    for _ in range(20):
        if not _pid_alive(pid):
            break
        time.sleep(0.25)
    if _pid_alive(pid):
        print(f"  {name}: не завершился — SIGKILL")
        _kill_group(pid, signal.SIGKILL)
        time.sleep(0.3)

    pid_file.unlink(missing_ok=True)


def stop_tmux(name: str, dry_run: bool) -> None:
    try:
        has = subprocess.run(
            ["tmux", "has-session", "-t", name], capture_output=True
        ).returncode == 0
    except FileNotFoundError:
        return
    if not has:
        return
    if dry_run:
        print(f"  tmux:{name}: будет закрыта")
        return
    print(f"  tmux:{name}: закрываю сессию...")
    subprocess.run(["tmux", "kill-session", "-t", name], check=False)


def stop_own_proxy(dry_run: bool) -> None:
    """Остановка своего мобильного прокси: tinyproxy на телефоне (nohup, по SSH)."""
    try:
        config = load_avito_config("config.toml")
    except Exception as err:
        print(f"  ⚠️ Не удалось прочитать config.toml: {err}")
        return
    if not getattr(getattr(config, "own_mobile_proxy", None), "use", False):
        return

    if dry_run:
        print("  proxy: tinyproxy на телефоне будет остановлен (nohup-процесс)")
        return

    from utils.own_mobile_proxy import stop_proxy

    print("  proxy: останавливаю tinyproxy на телефоне...")
    stop_proxy(config)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Остановка парсера и сопутствующих процессов (после run.py)"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Только показать, что будет остановлено")
    parser.add_argument("--keep-proxy", action="store_true",
                        help="Не останавливать прокси (хост + телефон)")
    args = parser.parse_args(argv)

    print("Фоновые процессы (logs/*.pid):")
    for name in PID_NAMES:
        stop_detached(name, args.dry_run)

    print("tmux-сессии:")
    for name in TMUX_SESSIONS:
        stop_tmux(name, args.dry_run)

    if not args.keep_proxy:
        print("Свой мобильный прокси (телефон):")
        stop_own_proxy(args.dry_run)

    print("Dry-run: ничего не изменено." if args.dry_run else "Готово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
