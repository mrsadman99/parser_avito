"""
Клиент для запросов парсера (curl_cffi)
"""
from curl_cffi import requests

from engine.cookies.base import CookiesProvider
from engine.http.base import BaseHttpClient
from engine.proxies.proxy import Proxy


from utils.http_logging import http_call


class HttpClient(BaseHttpClient):
    def __init__(
        self,
        proxy: Proxy,
        cookies: CookiesProvider | None = None,
        timeout: int = 30,
        max_retries: int = 5,
        retry_delay: int = 5,
        block_threshold: int = 3,
    ):
        super().__init__(
            proxy=proxy,
            cookies=cookies,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
            block_threshold=block_threshold,
        )
        self._client = self._build_client()

    def _build_client(self) -> requests.Session:
        fingerprint = self.cookies.get_fingerprint() if self.cookies else None
        fingerprint = fingerprint if isinstance(fingerprint, dict) else {}
        fingerprint_headers = fingerprint.get("headers", {})
        fingerprint_headers = (
            fingerprint_headers if isinstance(fingerprint_headers, dict) else {}
        )
        user_agent = fingerprint_headers.get("user-agent")
        if not user_agent and self.cookies:
            user_agent = self.cookies.get_user_agent()
        user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        )
        is_mobile = " Mobile " in user_agent
        impersonate = fingerprint.get("impersonate") or "chrome"
        session = requests.Session(impersonate=impersonate)
        default_headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            "referer": "https://www.avito.ru/",
            'sec-ch-ua': '"Not=A?Brand";v="99", "Google Chrome";v="149", "Chromium";v="149"',
            'sec-ch-ua-mobile': '?1' if is_mobile else '?0',
            'sec-ch-ua-platform': '"Android"' if is_mobile else '"Windows"',
            'user-agent': user_agent,
        }
        headers = {**default_headers, **fingerprint_headers}
        headers["user-agent"] = user_agent
        session.headers.update(headers)
        if self.cookies:
            session.cookies.update(self.cookies.get())
        self._cookies_revision = getattr(self.cookies, 'revision', None)

        proxy = self.proxy.get_httpx_proxy()
        if proxy:
            session.proxies = {
                "http": proxy,
                "https": proxy,
            }

        return session

    def _send(self, method, url, *, cancellation, **kwargs):
        # Отмена могла произойти после ответа SPFA, но до сброса сессии в _rotate.
        if getattr(self.cookies, 'revision', None) != self._cookies_revision:
            self._reset()
        return http_call(
            'avito', method, self._client.request, url, session=self._client, with_method=True,
            timeout=kwargs.pop('timeout', self.timeout), **kwargs,
        )

    def _get_ip_response(self, service, proxies):
        return http_call('other', 'GET', requests.get, service, proxies=proxies, timeout=10, impersonate="chrome")

    def _reset(self) -> None:
        self._reset_client()

    def _reset_client(self) -> None:
        self._client.close()
        self._client = self._build_client()

    def _retryable_error(self, error) -> bool:
        return isinstance(error, requests.RequestsError)

    def close(self) -> None:
        self._client.close()
