"""Общий журнал и отдельные журналы трёх алгоритмов приложения."""
from pathlib import Path
import json
import traceback

from loguru import logger

# Устанавливает общую маскировку секретов также для новых файловых обработчиков.
import hide_private_data  # noqa: F401


def log_category(record):
    explicit = record["extra"].get("log_category")
    if explicit:
        return explicit
    name = record["name"] or ""
    if name.startswith("notifications."):
        return "notifications"
    if name == "engine.app" or record["file"].name == "app.py":
        if record["function"] in {"_notification_cycle", "_deliver_pending_notifications"}:
            return "notifications"
        return "scanning"
    if name.startswith(("engine.http.", "engine.cookies.", "engine.proxies.")) or name in {
        "mobile_proxy.own_mobile_proxy", "mobile_proxy.adb", "mobile_proxy.tinyproxy_forward", "proxy_helpers",
    }:
        return "blocking"
    if name.startswith("engine.export.") or name in {
        "engine.url_converter", "engine.request_queue", "engine.mobile_detail",
        "engine.filters", "persistence.ads", "utils.parse_phone",
    }:
        return "scanning"
    return None


def json_log_format(record):
    """Одна JSON-строка на событие; только явно выбранные безопасные поля."""
    exception = record["exception"]
    event = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name.lower(),
        "subsystem": log_category(record) or "general",
        "module": record["name"],
        "function": record["function"],
        "line": record["line"],
        "message": record["message"],
        "exception": "" if exception is None else "".join(traceback.format_exception(
            exception.type, exception.value, exception.traceback)),
    }
    # extra может содержать произвольные данные пользователя: в JSON его не копируем.
    record["extra"]["_json_line"] = json.dumps(
        {key: hide_private_data.redact_log_text(value) if isinstance(value, str) else value
         for key, value in event.items()}, ensure_ascii=False,
    )
    # Callable format не добавляет отдельный многострочный traceback после JSON.
    return "{extra[_json_line]}\n"


def configure_app_logging(directory="logs"):
    """Вызывается один раз при загрузке парсера; возвращает ID добавленных sinks."""
    directory = Path(directory)
    options = dict(rotation="5 MB", retention="5 days", level="DEBUG", encoding="utf-8")
    handlers = [logger.add(directory / "app.log", **options)]
    for category in ("scanning", "notifications", "blocking"):
        handlers.append(logger.add(
            directory / f"{category}.log",
            filter=lambda record, expected=category: log_category(record) == expected,
            **options,
        ))
    handlers.append(logger.add(
        directory / "events.jsonl", format=json_log_format, colorize=False,
        diagnose=False, backtrace=False, **options,
    ))
    return handlers
