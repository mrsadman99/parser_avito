"""
Клиент для уведомлений, для парсера есть свой отдельный
"""
import time
from typing import Callable

import requests
from loguru import logger
from hide_private_data import redact_log_text

RETRY_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def is_permanent_delivery_error(error: Exception) -> bool:
    """Ошибки HTTP-запроса, которые повтор той же отправки не исправит."""
    response = getattr(error, 'response', None)
    return (isinstance(error, requests.HTTPError) and response is not None
            and 400 <= response.status_code < 500
            and response.status_code not in RETRY_STATUS_CODES)


def safe_request_error(error):
    message = redact_log_text(str(error))
    response = getattr(error, 'response', None)
    if response is not None:
        try:
            payload = response.json()
        except (ValueError, requests.RequestException):
            payload = None
        description = payload.get('description') if isinstance(payload, dict) else None
        if isinstance(description, str):
            # Только причина ошибки API: без запроса, заголовков и полного тела ответа.
            description = redact_log_text(description).replace('\n', ' ').replace('\r', ' ')[:500]
            message += f'; API description: {description}'
    return message


def send_with_retries(
    send_fn: Callable[[], requests.Response],
    *,
    retries: int = 3,
    delay: float = 2.0,
    backoff: float = 1.5,
):
    """
    Универсальный retry для отправки уведомлений
    """

    for attempt in range(1, retries + 1):
        try:
            response = send_fn()

            if response.status_code in RETRY_STATUS_CODES:
                raise requests.HTTPError(
                    f"Retryable status {response.status_code}",
                    response=response,
                )

            response.raise_for_status()
            return response

        except requests.HTTPError as e:
            e._log_sensitive = getattr(e, '_log_sensitive', False) or redact_log_text(str(e)) != str(e)
            e.args = (safe_request_error(e),)
            resp = e.response
            # Permanent errors must not re-enter the persistent delivery queue either.
            if is_permanent_delivery_error(e):
                logger.error(
                    f"[notify] non-retryable client error {resp.status_code}, aborting: {e}"
                )
                raise

            logger.warning(
                f"[notify retry] attempt {attempt}/{retries}: {e}"
            )

            if attempt >= retries:
                logger.error("[notify retry] retries exhausted")
                raise

            sleep_time = delay * (backoff ** (attempt - 1))
            time.sleep(sleep_time)

        except requests.RequestException as e:
            e._log_sensitive = getattr(e, '_log_sensitive', False) or redact_log_text(str(e)) != str(e)
            e.args = (redact_log_text(str(e)),)
            logger.warning(
                f"[notify retry] attempt {attempt}/{retries}: {e}"
            )

            if attempt >= retries:
                logger.error("[notify retry] retries exhausted")
                raise

            sleep_time = delay * (backoff ** (attempt - 1))
            time.sleep(sleep_time)
