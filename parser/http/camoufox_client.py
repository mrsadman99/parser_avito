"""Клиент для запросов к поисковой выдаче Avito через Camoufox.

Camoufox — антидетект-браузер (форк Firefox) с нативным подменом отпечатка.
Здесь он используется с десктопным отпечатком и мобильным прокси (adb + microsocks).
"""
import time

import requests
from loguru import logger


class CamoufoxResponse:
    """Минимальная обёртка, совместимая с requests.Response (text/json/status_code)."""

    def __init__(self, text: str, status_code: int, url: str):
        self.text = text
        self.status_code = status_code
        self.url = url

    def json(self):
        import json
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} для {self.url}")


class CamoufoxClient:
    """Запросы к поиску Avito через Camoufox.

    Браузер запускается один раз и переиспользуется между запросами (свои cookies,
    десктопный отпечаток, обход блокировок сменой IP через прокси).
    """

    BLOCK_CODES = (403, 429, 439)

    def __init__(
        self,
        proxy=None,
        os: str = "windows",
        headless: bool = True,
        humanize: bool = True,
        geoip: bool = True,
        timeout: int = 30,
        max_retries: int = 5,
        retry_delay: int = 5,
        block_threshold: int = 3,
    ):
        self.proxy = proxy
        self.os = os
        self.headless = headless
        self.humanize = humanize
        self.geoip = geoip
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.block_threshold = block_threshold

        self.block_count = 0
        self.error_count = 0
        self._block_attempts = 0
        self._manager = None
        self._browser = None
        self._context = None
        self._page = None

    def _launch(self):
        try:
            from camoufox.sync_api import Camoufox
        except ImportError as err:
            raise RuntimeError(
                'Camoufox не установлен. Выполните: pip install "camoufox[geoip]"'
            ) from err

        kwargs = {
            "os": self.os,
            "headless": self.headless,
            "humanize": self.humanize,
        }
        if self.geoip:
            kwargs["geoip"] = True
        if self.proxy:
            proxy_dict = getattr(self.proxy, "get_playwright_proxy", lambda: None)()
            if proxy_dict:
                kwargs["proxy"] = proxy_dict

        try:
            self._manager = Camoufox(**kwargs)
            self._browser = self._manager.__enter__()
        except Exception as err:
            if kwargs.get("geoip"):
                logger.warning(f"Запуск с geoip не удался ({err}), пробуем без geoip")
                kwargs.pop("geoip", None)
                self._manager = Camoufox(**kwargs)
                self._browser = self._manager.__enter__()
            else:
                raise

        if hasattr(self._browser, "new_page"):
            self._page = self._browser.new_page()
        elif hasattr(self._browser, "new_context"):
            self._context = self._browser.new_context()
            self._page = self._context.new_page()
        else:
            raise RuntimeError("Не удалось создать страницу Camoufox")

        logger.info(f"Camoufox запущен (desktop fingerprint, os={self.os})")
        return self._page

    def _reset(self):
        """Перезапускает браузер после смены IP (сбрасывает cookies/сессию)."""
        self._close()
        self._launch()

    def _close(self):
        try:
            if self._manager is not None:
                self._manager.__exit__(None, None, None)
        except Exception:
            pass
        self._manager = self._browser = self._context = self._page = None

    def close(self):
        self._close()

    def get_current_ip(self) -> str | None:
        """Текущий внешний IP (через прокси, если он задан)."""
        proxy = self.proxy.get_httpx_proxy() if self.proxy else None
        proxies = {"http": proxy, "https": proxy} if proxy else None
        for service in ("https://api.ipify.org?format=json", "https://ipinfo.io/ip"):
            try:
                resp = requests.get(service, proxies=proxies, timeout=10)
                if resp.status_code != 200:
                    continue
                if "ipify" in service:
                    return resp.json().get("ip")
                return resp.text.strip()
            except Exception:
                continue
        return None

    def _ensure_page(self):
        if self._page is None:
            self._launch()
        return self._page

    def request(self, method: str, url: str, **kwargs) -> CamoufoxResponse:
        last_exc = None

        current_ip = self.get_current_ip()
        logger.info(f"🦊 Camoufox {method.upper()} {url} — IP: {current_ip or 'не определён'}")

        for attempt in range(1, self.max_retries + 1):
            try:
                page = self._ensure_page()
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout * 1000,
                )
                status = response.status if response else 0
                body = response.text() if response else ""

                if status in self.BLOCK_CODES:
                    self._block_attempts += 1
                    self.block_count += 1
                    logger.warning(
                        f"Camoufox: блокировка ({status}) на {url}, "
                        f"попытка {self._block_attempts}"
                    )
                    if self._block_attempts >= self.block_threshold:
                        logger.warning(
                            "Достигнут лимит блокировок — меняем IP и перезапускаем браузер"
                        )
                        if self.proxy:
                            try:
                                self.proxy.handle_block()
                            except Exception as err:
                                logger.warning(f"Смена IP через прокси не удалась: {err}")
                        self._reset()
                        self._block_attempts = 0
                    time.sleep(self.retry_delay)
                    continue

                self._block_attempts = 0
                return CamoufoxResponse(text=body, status_code=status, url=str(url))

            except Exception as err:
                last_exc = err
                self.error_count += 1
                logger.warning(f"Camoufox request error (attempt {attempt}): {err}")
                try:
                    self._reset()
                except Exception:
                    pass
                time.sleep(self.retry_delay)

        raise RuntimeError("Camoufox: запросы были неуспешными") from last_exc
