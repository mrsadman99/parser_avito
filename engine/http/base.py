"""Общий контракт HTTP-клиентов парсера и разделяемая retry/ротация-логика.

HttpClient (curl_cffi) и CamoufoxClient (антидетект-браузер) реализуют один
интерфейс, поэтому engine.app обращается к ним единообразно. Различия
(транспорт, сброс сессии, что считать ретрай-ошибкой) вынесены в хуки.
"""
from abc import ABC, abstractmethod
import time

import requests
from loguru import logger

from engine.cancellation import Cancellation, ParseCancelled
from engine.cookies.base import UnblockState
from engine.proxies.proxy import ProxyRotationError


from utils.http_logging import http_call


class UnblockTimeoutError(RuntimeError):
    """SPFA не восстановил доступ за отведённое время."""


class BaseHttpClient(ABC):
    BLOCK_CODES = (403, 429, 439)

    def __init__(
        self,
        proxy,
        timeout: int = 30,
        max_retries: int = 5,
        retry_delay: int = 5,
        block_threshold: int = 3,
        cookies=None,
    ):
        self.proxy = proxy
        self.cookies = cookies
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.block_threshold = block_threshold

        self.block_count = 0
        self.error_count = 0
        self.last_response = None
        self._block_attempts = 0

    # -- хуки, реализуемые подклассами ------------------------------------- #

    @abstractmethod
    def _send(self, method: str, url: str, *, cancellation: Cancellation, **kwargs):
        """Один «сырой» запрос; возвращает объект со status_code/raise_for_status."""

    @abstractmethod
    def _reset(self) -> None:
        """Пересоздаёт сессию/браузер после смены IP."""

    @abstractmethod
    def close(self) -> None:
        """Освобождает ресурсы клиента."""

    def _retryable_error(self, error) -> bool:
        """Какие ошибки считать ретраями (по умолчанию — все)."""
        return True

    def _on_error(self, error) -> None:
        """По умолчанию сетевая ошибка сбрасывает последовательность блокировок."""
        self._block_attempts = 0

    def _check_response(self, response) -> None:
        response.raise_for_status()

    def _get_ip_response(self, service, proxies):
        return http_call('other', 'GET', requests.get, service, proxies=proxies, timeout=10)

    # -- общая логика ------------------------------------------------------- #

    def get_current_ip(self, cancellation: Cancellation | None = None) -> str | None:
        """Определяет текущий внешний IP (через настроенный прокси, если он есть)."""
        cancellation = cancellation or Cancellation()
        proxy = self.proxy.get_httpx_proxy() if self.proxy else None
        proxies = {"http": proxy, "https": proxy} if proxy else None
        for service in ("https://api.ipify.org?format=json", "https://ipinfo.io/ip"):
            cancellation.checkpoint()
            try:
                resp = self._get_ip_response(service, proxies)
                cancellation.checkpoint()
                if resp.status_code != 200:
                    continue
                if "ipify" in service:
                    return resp.json().get("ip")
                return resp.text.strip()
            except ParseCancelled:
                raise
            except Exception:
                continue
        return None

    def _unblock_state(self) -> UnblockState | None:
        state = self.cookies.get_unblock_state() if self.cookies else None
        return state if isinstance(state, UnblockState) else None

    def _rotate(self, cancellation: Cancellation) -> None:
        """Смена IP, обновление cookies и пересоздание сессии."""
        state = self._unblock_state()
        if state is not None and time.monotonic() < state.deadline:
            logger.info('SPFA: смена IP отложена до завершения активной разблокировки')
            return
        try:
            rotated = self.proxy.rotate_with_retries(cancellation=cancellation) if self.proxy else False
        except (ParseCancelled, ProxyRotationError):
            raise
        except Exception as err:
            cancellation.checkpoint()
            raise ProxyRotationError("Ошибка при смене IP прокси") from err
        cancellation.checkpoint()
        if not rotated:
            raise ProxyRotationError("Не удалось сменить IP прокси")
        if self.cookies:
            self.cookies.handle_block()
        cancellation.checkpoint()
        if self.cookies:
            self.cookies.handle_ip_change()
        cancellation.checkpoint()
        self._reset()
        new_ip = self.get_current_ip(cancellation=cancellation)
        if new_ip:
            logger.success(f"Прокси обновлён, новый IP: {new_ip}")
        else:
            logger.warning("Не удалось определить IP после смены прокси")

    def request(self, method: str, url: str, *, cancellation: Cancellation | None = None,
                accepted_statuses=(), **kwargs):
        """Единый цикл: блокировка → смена IP → ретраи с паузой."""
        cancellation = cancellation or Cancellation()
        cancellation.checkpoint()
        self.last_response = None
        last_exc = None

        current_ip = self.get_current_ip(cancellation=cancellation)
        logger.info(f"Запрос {method.upper()} {url} — IP: {current_ip or 'не определён'}")

        attempt = 0
        recovery_retry = False
        recovery_retry_used = False
        while True:
            cancellation.checkpoint()
            state = self._unblock_state()
            probe = state is not None
            if probe:
                remaining = state.deadline - time.monotonic()
                if remaining > 0:
                    delay = min(state.check_interval, remaining)
                    logger.info('SPFA: проверка cookies через {:.1f}с; до конца ожидания {:.1f}с; Avito приостановлен',
                                delay, remaining)
                    cancellation.wait(delay)
                remaining = state.deadline - time.monotonic()
                if remaining <= 0:
                    self.cookies.expire_unblock()
                    self._block_attempts = 0
                    status = getattr(self.last_response, 'status_code', None)
                    raise UnblockTimeoutError(
                        f'Истёк срок ожидания SPFA для {url}; последний HTTP-статус: {status}'
                    ) from last_exc
                if self.cookies.poll_unblock(timeout=remaining):
                    # Сессия должна получить именно подтверждённый SPFA набор.
                    self._reset()
                    recovery_retry = True
                continue
            else:
                if attempt >= self.max_retries:
                    if recovery_retry and not recovery_retry_used:
                        recovery_retry_used = True
                    else:
                        break
                attempt += 1
            try:
                request_kwargs = dict(kwargs)
                response = self._send(method, url, cancellation=cancellation, **request_kwargs)
                self.last_response = response
                cancellation.checkpoint()
                if self.cookies:
                    self.cookies.update(response)

                status = getattr(response, "status_code", 0)
                logger.debug("HTTP-ответ {}: {}", status, getattr(response, "url", url))
                if status in self.BLOCK_CODES:
                    self._block_attempts += 1
                    self.block_count += 1
                    logger.warning(
                        f"Запрос заблокирован ({status}) к {url}, "
                        f"попытка {self._block_attempts}"
                    )
                    if self._block_attempts >= self.block_threshold:
                        logger.warning("Достигнут лимит блокировок, запускается обработка")
                        self._rotate(cancellation)
                        self._block_attempts = 0
                    if self._unblock_state() is None:
                        cancellation.wait(self.retry_delay)
                    continue

                self._block_attempts = 0
                if status in accepted_statuses:
                    return response
                self._check_response(response)
                return response

            except (ParseCancelled, ProxyRotationError):
                raise
            except Exception as err:
                if not self._retryable_error(err):
                    raise
                cancellation.checkpoint()
                last_exc = err
                self.error_count += 1
                logger.warning(f"Request error (attempt {attempt}): {err}")
                self._on_error(err)
                if self._unblock_state() is None:
                    cancellation.wait(self.retry_delay)

        raise RuntimeError("HTTP запросы были неуспешными") from last_exc
