import json
import time
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

import requests
from loguru import logger

from engine.cookies.base import CookiesProvider, UnblockState
from engine.proxies.proxy import ProxyRotationError
from proxy_helpers import build_proxies_dict
from engine.cancellation import cancellable_lock

API_URL = "https://spfa.pro/api"


from utils.http_logging import http_call


def _recovery_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._recovery_lock:
            return method(self, *args, **kwargs)
    return wrapped


class ExternalApiCookiesProvider(CookiesProvider):
    MAX_STATUS_HISTORY = 20

    def __init__(
        self,
        config,
        storage_path: str | Path = "storage/cookies_external.json",
        proxy=None,
    ):
        self.api_key = config.cookies_api_key
        self._recovery_lock = threading.RLock()
        self.revision = 0
        self.proxy_handler = proxy
        own_proxy_string = (
            proxy.get_spfa_proxy_string() if proxy is not None else None
        )
        self.proxy = own_proxy_string or config.external_mobile_proxy.proxy_string
        # сами запросы к SPFA шлём через proxy_notifier (payload не меняем)
        self.request_proxies = build_proxies_dict(config.messengers.proxy_notifier)
        self.purchase_cooldown = config.purchase_cooldown
        self.storage_path = Path(storage_path)

        self.last_id: str | None = None
        self.last_cookies: dict | None = None
        self.user_agent: str | None = None
        self.fingerprint: dict | None = None
        self.mobile: bool | None = None

        self.unblock_started_at: float | None = None
        self.UNBLOCK_TIMEOUT = config.spfa_unblock_timeout
        self.unblock_check_interval = config.spfa_unblock_check_interval
        self.PAUSE_FOR_ERROR = 120 # 2 минуты
        self.NOT_BALANCE = 300 # 5 минуты
        self.WAIT_FOR_NEW = 3  # 3 сек, пауза после покупки для стабильности

        self.status_history: list[int] = []  # новые: последние коды
        self.last_purchase_at: float | None = None  # новые: время последней покупки

        self._load_from_disk()

        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def get(self) -> dict:
        if self.last_cookies:
            return self.last_cookies

        return self._get_new_cookies()

    def get_user_agent(self) -> str | None:
        if not self.last_cookies or not self.user_agent:
            self._get_new_cookies()
        return self.user_agent

    def get_fingerprint(self) -> dict | None:
        if not self.last_cookies or not self.fingerprint:
            self._get_new_cookies()
        return self.fingerprint

    def update(self, response):
        """
        Обновляем историю кодов ответа.
        Сохраняем на диск только при изменении или плохом коде.
        """
        if response is None:
            return

        code = getattr(response, "status_code", None)
        if code is None:
            return

        response_cookies = dict(response.cookies)
        if response_cookies:
            if self.last_cookies is None:
                self.last_cookies = {}
            self.last_cookies.update(response_cookies)

        last_code = self.status_history[-1] if self.status_history else None
        self.status_history.append(code)
        if len(self.status_history) > self.MAX_STATUS_HISTORY:
            self.status_history.pop(0)

        # сохраняем только если:
        # 1) код изменился относительно последнего
        # 2) код плохой (403 или 429)
        # 3) первый код (нет истории)
        if response_cookies or code != last_code or code in (403, 429, 439) or last_code is None:
            self._save_to_disk()

    def get_unblock_state(self) -> UnblockState | None:
        if self.unblock_started_at is None:
            return None
        return UnblockState(self.unblock_started_at + self.UNBLOCK_TIMEOUT,
                            self.unblock_check_interval)

    def expire_unblock(self) -> None:
        # Следующее задание также должно дождаться cookies, а не отправлять старые.
        self.unblock_started_at = time.monotonic()
        logger.warning('Истёк срок ожидания SPFA; запрос завершается, доступ к Avito остаётся приостановленным')

    def _request_unblock(self, timeout):
        return http_call('spfa', 'POST', requests.post,
            f"{API_URL}/unblock/",
            json={"id": self.last_id, "api_key": self.api_key, "proxy": self.proxy},
            headers=self.headers, timeout=timeout, proxies=self.request_proxies,
        )

    def _accept_unblock(self, response) -> bool:
        # SPFA возвращает готовые cookies и с HTTP 202; проверяем содержимое ответа.
        if response.status_code not in (200, 202):
            return False
        try:
            payload = response.json()
            data = payload.get('results') if isinstance(payload, dict) else None
            cookies = data.get('cookies') if isinstance(data, dict) else None
            valid = (payload.get('success') is True and isinstance(data, dict)
                     and str(data.get('id')) == str(self.last_id)
                     and isinstance(cookies, dict) and bool(cookies)
                     and all(isinstance(k, str) and isinstance(v, str) for k, v in cookies.items()))
        except (ValueError, AttributeError):
            valid = False
        if not valid:
            logger.warning('SPFA: ответ не подтверждает получение актуальных cookies; Avito ожидает')
            return False
        previous = self.last_cookies
        previous_history = self.status_history
        self.last_cookies = dict(cookies)
        self.status_history = []
        try:
            self._save_to_disk()
        except Exception:
            self.last_cookies = previous
            self.status_history = previous_history
            raise
        self.unblock_started_at = None
        self.revision += 1
        logger.info('✅ SPFA: актуальные cookies получены; запросы к Avito разрешены | id={}', self.last_id)
        return True

    @contextmanager
    def photo_access(self, cancellation):
        """CDN ждёт восстановления; уже начатая загрузка завершается до SPFA."""
        while True:
            with cancellable_lock(self._recovery_lock, cancellation):
                if self.unblock_started_at is None:
                    yield
                    return
            cancellation.wait(0.1)

    @_recovery_locked
    def poll_unblock(self, timeout: float) -> bool:
        try:
            response = self._request_unblock(timeout)
        except requests.RequestException as err:
            logger.warning('SPFA: ошибка ожидания {}; запросы к Avito приостановлены', type(err).__name__)
            return False
        logger.debug('SPFA: проверка готовности cookies, HTTP {}', response.status_code)
        if response.status_code in (404, 410):
            self._get_new_cookies()
            return True
        return self._accept_unblock(response)

    @_recovery_locked
    def handle_block(self):
        """
        Пытаемся разблокировать cookies.
        Если не получилось — получаем новые.
        """

        now = time.time()

        # Активная задача имеет приоритет над покупкой cookies и новой разблокировкой.
        state = self.get_unblock_state()
        if state is not None:
            if time.monotonic() < state.deadline:
                logger.info('SPFA уже выполняет разблокировку; IP и cookies сохраняются')
                return
            self.expire_unblock()
            return

        self.unblock_started_at = time.monotonic()

        # ---- Нет cookies вообще ----
        if not self.last_id:
            logger.warning("⚠️ Нет cookies id — запрашиваем новые cookies")
            self._get_new_cookies()
            return

        # ---- Проверяем историю кодов и время последней покупки ----
        if self.last_purchase_at and (now - self.last_purchase_at) < self.purchase_cooldown:
            logger.info(
                f"⏱ С последней покупки прошло меньше {self.purchase_cooldown} сек. "
                f"| id={self.last_id} | пытаемся разблокировать"
            )
            # идем к разблокировке
        elif (
                len(self.status_history) >= self.MAX_STATUS_HISTORY
                and all(code in (403, 429, 439) for code in self.status_history[-self.MAX_STATUS_HISTORY:])
        ):
            logger.warning(
                "⚠️ Все последние 20 кодов плохие (403/429/439) — покупаем новые cookies"
            )
            self._get_new_cookies()
            return

        logger.info(f"🔓 Пытаемся разблокировать cookies | id={self.last_id}")

        try:
            res = self._request_unblock(self.UNBLOCK_TIMEOUT)
        except requests.RequestException as e:
            logger.error(
                f"❌ Ошибка при запросе к API разблокировки | id={self.last_id} | {e}"
            )
            self._get_new_cookies()
            return

        if self._accept_unblock(res):
            return

        # Без актуальных cookies запросы Avito остаются приостановленными.
        if res.status_code in (200, 202):
            logger.info(f"⏳ Ожидаем актуальные cookies SPFA | id={self.last_id}")
            return

        # ---- Уже в процессе ----
        if res.status_code == 409:
            logger.info(f"⏳ Разблокировка уже выполняется | id={self.last_id}")
            return

        # ---- Слишком поздно ----
        if res.status_code == 410:
            logger.info(f"⏰ Истёк срок разблокировки cookies | id={self.last_id}")

        # ---- Фатальные ошибки ----
        elif res.status_code == 403:
            time.sleep(self.NOT_BALANCE)
            logger.error("⛔ Доступ запрещён: неверный API key, нет прав или не хватает баланса")

        elif res.status_code == 404:
            time.sleep(self.PAUSE_FOR_ERROR)
            logger.warning(f"❌ Cookies не найдены на сервере | id={self.last_id}")

        elif res.status_code == 503:
            logger.warning("🚧 Сервис временно недоступен, ждём")
            time.sleep(self.PAUSE_FOR_ERROR)
            return

        else:
            logger.error(f"❌ Неожиданный ответ от сервера | статус={res.status_code} | тело={res.text}")
            return

        # ---- Только здесь можно покупать новые ----
        logger.warning(f"➡️ Покупаем новые cookies вместо id={self.last_id}")
        self._get_new_cookies()

    @_recovery_locked
    def _get_new_cookies(self) -> dict:
        logger.info("🛒 Запрашиваем покупку новых cookies у сервиса")

        try:
            res = http_call('spfa', 'POST', requests.post,
                f"{API_URL}/cookies/mobile/",
                json={
                    "api_key": self.api_key,
                    "mobile": True,
                    "proxy": self.proxy
                },
                headers=self.headers,
                timeout=self.UNBLOCK_TIMEOUT,
                proxies=self.request_proxies,
            )
        except requests.RequestException as e:
            logger.error(f"❌ Не удалось связаться с сервисом cookies | ошибка={e}")
            self._handle_purchase_failure()
            raise

        # ---- Обработка HTTP ошибок ----
        if res.status_code == 401:
            logger.error("⛔ Не передан API key при запросе cookies")
            self._handle_purchase_failure(self.PAUSE_FOR_ERROR)
            res.raise_for_status()

        if res.status_code == 403:
            logger.error("⛔ Доступ запрещён: неверный API key или недостаточно средств")
            self._handle_purchase_failure(self.NOT_BALANCE)
            res.raise_for_status()

        if res.status_code == 503:
            logger.warning("🚧 Сервис cookies временно недоступен (парсер не готов)")
            self._handle_purchase_failure(self.PAUSE_FOR_ERROR)
            res.raise_for_status()

        if not res.ok:
            logger.error(f"❌ Ошибка при покупке cookies | статус={res.status_code} | тело={res.text}")
            self._handle_purchase_failure(self.PAUSE_FOR_ERROR)
            res.raise_for_status()

        # ---- Успешный ответ ----
        try:
            payload = res.json()
            if not isinstance(payload, dict) or payload.get("success") is not True:
                self._handle_purchase_failure()
                raise RuntimeError("Сервис cookies вернул success=false")
            data = payload.get("results", {})
        except ValueError:
            logger.error("❌ Сервер вернул некорректный JSON при покупке cookies")
            self._handle_purchase_failure()
            raise

        if not isinstance(data, dict):
            raise RuntimeError("Сервер вернул неполные данные cookies")
        new_id = data.get("id")
        new_cookies = data.get("cookies")
        fingerprint = data.get("fingerprint")

        fingerprint_headers = (
            fingerprint.get("headers", {})
            if isinstance(fingerprint, dict)
            else {}
        )
        user_agent = data.get("user_agent") or fingerprint_headers.get("user-agent")

        if (
            not new_id
            or not isinstance(new_cookies, dict)
            or not new_cookies
            or not user_agent
            or not isinstance(fingerprint, dict)
            or not fingerprint.get("impersonate")
            or not isinstance(fingerprint_headers, dict)
            or not fingerprint_headers
        ):
            logger.error("❌ Ответ сервера без полного набора cookies/fingerprint")
            self._handle_purchase_failure()
            raise RuntimeError("Сервер вернул неполные данные cookies")

        self.last_id = new_id
        self.last_cookies = new_cookies
        self.fingerprint = fingerprint
        self.mobile = data.get("mobile")
        self.user_agent = user_agent
        self.last_purchase_at = time.time()  # новое: сохраняем дату и время покупки
        self.status_history.clear()  # сбрасываем историю последних кодов после покупки
        self.unblock_started_at = None  # ожидание относилось к предыдущему набору cookies
        self.revision += 1

        logger.info(f"✅ Cookies успешно получены | id={self.last_id}")

        self._save_to_disk()
        logger.debug("💾 Cookies сохранены на диск")
        time.sleep(self.WAIT_FOR_NEW)
        return self.last_cookies

    def _handle_purchase_failure(self, pause: int | None = None) -> None:
        if self.proxy_handler is not None:
            try:
                self.proxy_handler.rotate_with_retries()
            except ProxyRotationError:
                raise
            except Exception as err:
                logger.warning(
                    f"Не удалось сменить IP после ошибки получения cookies: {err}"
                )

        if pause is not None:
            time.sleep(pause)

    def _save_to_disk(self):
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "id": self.last_id,
                "cookies": self.last_cookies,
                "user_agent": self.user_agent,
                "fingerprint": self.fingerprint,
                "mobile": self.mobile,
                "saved_at": time.time(),
                "status_history": self.status_history,
                "last_purchase_at": self.last_purchase_at,
            }
            self.storage_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug("💾 Cookies сохранены на диск")
        except Exception as err:
            logger.warning(f"Не удалось сохранить cookies локально: {err}")

    def _load_from_disk(self):
        if not self.storage_path.exists():
            logger.info("Нет сохраненных cookies")
            return

        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            self.last_id = data.get("id")
            self.last_cookies = data.get("cookies")
            self.user_agent = data.get("user_agent")
            self.fingerprint = data.get("fingerprint")
            self.mobile = data.get("mobile")
            self.status_history = data.get("status_history", [])
            self.last_purchase_at = data.get("last_purchase_at")

            if self.last_id and self.last_cookies and self.user_agent and self.fingerprint:
                logger.info("Загружаем сохраненные cookies с диска")
            else:
                logger.warning("Cookies файл есть, но нет id, cookies или user_agent в нем")

        except Exception as err:
            logger.warning(f"Не удалось загрузить cookies локально: {err}")
