"""Клиент для запросов к поисковой выдаче Avito через Camoufox.

Camoufox — антидетект-браузер (форк Firefox) с нативным подменом отпечатка.
Здесь он используется с десктопным отпечатком и мобильным прокси
(свой — tinyproxy на телефоне по SSH — или внешний сервис).
"""
from loguru import logger
from engine.http.base import BaseHttpClient
from utils.http_logging import BrowserHttpLogger


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


class CamoufoxClient(BaseHttpClient):
    """Запросы к поиску Avito через Camoufox.

    Браузер запускается один раз и переиспользуется между запросами (свои cookies,
    десктопный отпечаток, обход блокировок сменой IP через прокси).
    """

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
        super().__init__(
            proxy=proxy,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
            block_threshold=block_threshold,
        )
        self.os = os
        self.headless = headless
        self.humanize = humanize
        self.geoip = geoip

        self._manager = None
        self._browser = None
        self._context = None
        self._page = None
        self._http_logger = None

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

        self._http_logger = BrowserHttpLogger(self._page, kwargs.get('proxy'))
        logger.info(f"Camoufox запущен (desktop fingerprint, os={self.os})")
        return self._page

    def _close(self):
        try:
            if self._manager is not None:
                self._manager.__exit__(None, None, None)
        except Exception:
            pass
        if self._http_logger is not None:
            self._http_logger.close()
            self._http_logger = None
        self._manager = self._browser = self._context = self._page = None

    def _ensure_page(self):
        if self._page is None:
            self._launch()
        return self._page

    def _send(self, method, url, *, cancellation, **kwargs):
        page = self._ensure_page()
        cancellation.checkpoint()
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self.timeout * 1000,
        )
        cancellation.checkpoint()
        status = response.status if response else 0
        body = response.text() if response else ""
        return CamoufoxResponse(text=body, status_code=status, url=str(url))

    def _check_response(self, response) -> None:
        # Браузер возвращает HTTP-ошибки вызывающему коду без сетевого ретрая.
        pass

    def _reset(self):
        """Перезапускает браузер после смены IP (сбрасывает cookies/сессию)."""
        self._close()
        self._launch()

    def _on_error(self, error) -> None:
        # В отличие от curl, сетевая ошибка не обнуляет накопленные блокировки.
        try:
            self._reset()
        except Exception:
            pass

    def close(self):
        self._close()
