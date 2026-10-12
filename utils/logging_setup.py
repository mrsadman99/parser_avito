"""Общий журнал и отдельные журналы трёх алгоритмов приложения."""
from pathlib import Path

from loguru import logger

# Устанавливает общую маскировку секретов также для новых файловых обработчиков.
import hide_private_data  # noqa: F401


def log_category(record):
    explicit = record["extra"].get("log_category")
    if explicit:
        return explicit
    name = record["name"] or ""
    if name.startswith("integrations.notifications."):
        return "notifications"
    if name == "parser_cls" or record["file"].name == "parser_cls.py":
        if record["function"] in {"_notification_cycle", "_deliver_pending_notifications"}:
            return "notifications"
        return "scanning"
    if name.startswith(("parser.http.", "parser.cookies.", "parser.proxies.")) or name in {
        "utils.own_mobile_proxy", "utils.adb", "utils.tinyproxy_forward", "proxy_helpers",
    }:
        return "blocking"
    if name.startswith(("parser.export.", "filters.")) or name in {
        "parser.url_converter", "parser.request_queue", "parser.mobile_detail", "db_service", "utils.parse_phone",
    }:
        return "scanning"
    return None


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
    return handlers
