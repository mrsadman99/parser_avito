"""Smoke-тест импорта: каждый модуль проекта должен импортироваться без ошибок.

Защищает от ImportError/NameError при переезде модулей между пакетами и
от поломки re-export'ов. Точки входа scripts/ и GUI проверяются отдельно;
server.main включён, поскольку его импорт не читает конфиг и не создаёт БД.
"""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Пакеты, внутри которых обходим каждый *.py и импортируем по точечному имени.
PACKAGES = ("engine", "server", "notifications", "mobile_proxy", "persistence", "domain", "utils")

# Модули в корне проекта (без AvitoParser.py — GUI на Flet — и entry-точек).
ROOT_MODULES = (
    "load_config",
    "proxy_helpers",
    "hide_private_data",
    "version",
    "lang",
)


def _module_names():
    names = list(ROOT_MODULES)
    for package in PACKAGES:
        package_dir = ROOT / package
        if not package_dir.is_dir():
            continue
        for path in sorted(package_dir.rglob("*.py")):
            relative = path.relative_to(ROOT)
            if relative.name == "__init__.py":
                continue
            name = ".".join(relative.with_suffix("").parts)
            names.append(name)
    return names


def test_all_modules_import():
    missing = []
    for name in _module_names():
        try:
            importlib.import_module(name)
        except Exception as err:  # noqa: BLE001 — фиксируем и отчитываемся
            missing.append(f"{name}: {type(err).__name__}: {err}")
    assert not missing, "Не импортируются:\n" + "\n".join(missing)
