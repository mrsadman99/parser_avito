import re
from loguru import logger


def redact_log_text(value: str) -> str:
    """Скрывает токены Telegram (включая URL-encoded) и авторизацию прокси."""
    value = re.sub(r"(?<![\w])\d{5,}(?::|%3[aA])[A-Za-z0-9_-]{20,}", "<redacted-token>", str(value))
    # В URL токену предшествует bot, поэтому граница слова выше не подходит.
    value = re.sub(r"bot\d+(?::|%3[aA])[A-Za-z0-9_-]+", "bot<redacted-token>", value)
    return re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1<redacted-auth>@", value)


def redact_log_record(record):
    record['message'] = redact_log_text(record['message'])
    exception = record.get('exception')
    if exception is not None:
        # Не оставляем секрет в цепочке исключений и локальных переменных traceback.
        current, seen, messages, changed = exception.value, set(), [], False
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            original = str(current)
            safe = redact_log_text(original)
            changed |= safe != original or getattr(current, '_log_sensitive', False)
            messages.append(f'{type(current).__name__}: {safe}')
            current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
        if changed:
            record['exception'] = exception._replace(
                type=RuntimeError, value=RuntimeError(' | '.join(messages)), traceback=None)


# Общая защита консоли, файлов и GUI Loguru, включая исключения из requests.
logger.configure(patcher=redact_log_record)


def mask_sensitive_data(config_str: str) -> str:
    """
    Маскирует приватные данные (прокси, токены, пароли и т.п.) в строке конфига.
    """
    masked = config_str

    # Прокси: user:pass@host:port → user:***@host:port
    masked = re.sub(
        r"([\w\-]+):([\w\-]+)@([\w\.\-]+):(\d+)",
        lambda m: f"{m.group(1)}:***@{m.group(3)}:{m.group(4)}",
        masked,
    )

    # Telegram токен
    masked = re.sub(
        r"(tg_token[\"']?\s*[:=]\s*[\"'])([^\"']+)([\"'])",
        lambda m: f"{m.group(1)}{m.group(2)[:5]}***{m.group(3)}",
        masked,
    )

    # Telegram chat_id
    masked = re.sub(
        r"(tg_chat_id[\"']?\s*[:=]\s*)(\[?[^\]]*\]?)",
        lambda m: f"{m.group(1)}['***']",
        masked,
    )

    # proxy_change_url / change_url / change_urls → скрываем почти полностью, оставляем домен
    masked = re.sub(
        r"((?:proxy_)?change_urls?[\"']?\s*[:=]\s*[\"'])([^\"']+)([\"'])",
        lambda m: f"{m.group(1)}{_mask_url(m.group(2))}{m.group(3)}",
        masked,
    )

    # proxy_key=... в changeip-ссылках (в т.ч. внутри списка change_urls) — скрываем значение
    masked = re.sub(r"(proxy_key=)[^&\"'\]\s]+", r"\1***", masked)

    # Общая маскировка чувствительных ключей (password, token, api_key, secret)
    masked = re.sub(
        r"((?:password|token|api_key|secret)[\"']?\s*[:=]\s*[\"'])([^\"']+)([\"'])",
        lambda m: f"{m.group(1)}***{m.group(3)}",
        masked,
        flags=re.IGNORECASE,
    )

    return redact_log_text(masked)


def _mask_url(url: str) -> str:
    """Маскирует URL, оставляя только домен для наглядности."""
    match = re.search(r"https?://([^/]+)/?", url)
    if match:
        domain = match.group(1)
        return f"https://{domain}/***"
    return "***"


def log_config(config, version: str):
    """
    Безопасно логирует конфигурацию, скрывая чувствительные данные.
    """
    safe_config_str = mask_sensitive_data(str(config))
    logger.info(f"Запуск AvitoParse v{version} с настройками:\n{safe_config_str}")
