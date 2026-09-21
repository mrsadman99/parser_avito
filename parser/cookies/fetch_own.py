"""Провайдер собственных cookies: куки получаются напрямую с Avito через прокси.

Аналог scripts/fetch_cookies.py: curl_cffi (Chrome 131 на Android) делает GET
https://www.avito.ru/ через мобильный прокси и собирает Set-Cookie. При блокировке
(вместо разблокировки/покупки) просто получает куки заново по этому же алгоритму.
"""
import json
import time
from pathlib import Path

from loguru import logger

from parser.cookies.base import CookiesProvider

TARGET_URL = "https://www.avito.ru/"
IMPERSONATE = "chrome131_android"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 15; SM-S938B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.7420.57 Mobile Safari/537.36"
)

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "referer": "https://www.avito.ru/",
    "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="131", "Chromium";v="131"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "user-agent": USER_AGENT,
}


class FetchOwnCookiesProvider(CookiesProvider):
    """Свои cookies: получаются GET-запросом к Avito через мобильный прокси."""

    def __init__(self, config, proxy=None,
                 storage_path: str | Path = "storage/own_cookies.json"):
        self.proxy = proxy          # Proxy-объект (get_httpx_proxy / get_spfa_proxy_string)
        self.storage_path = Path(storage_path)
        self.last_cookies: dict | None = None

        self._load_from_disk()

    # ------------------------------ интерфейс ------------------------------

    def get(self) -> dict:
        if self.last_cookies:
            return self.last_cookies
        try:
            return self._fetch_cookies()
        except Exception as err:
            logger.error(f"❌ Не удалось получить свои cookies с Avito: {err}")
            return {}

    def get_user_agent(self) -> str:
        return USER_AGENT

    def get_fingerprint(self) -> dict:
        return {
            "client": "curl_cffi",
            "impersonate": IMPERSONATE,
            "headers": HEADERS,
        }

    def update(self, response):
        """Сливаем новые Set-Cookie из ответа в текущие куки."""
        if not response:
            return
        response_cookies = dict(response.cookies)
        if not response_cookies:
            return
        if self.last_cookies is None:
            self.last_cookies = {}
        changes = {k: v for k, v in response_cookies.items()
                   if self.last_cookies.get(k) != v}
        if not changes:
            return
        self.last_cookies.update(changes)
        logger.info(f"🔄 Обновлены cookies: {list(changes.keys())}")
        self._save_to_disk()

    def handle_block(self):
        """Вместо разблокировки — получаем куки заново по тому же алгоритму."""
        logger.warning("🚫 Блокировка с own_cookies — получаю куки с Avito заново")
        try:
            self.last_cookies = self._fetch_cookies()
        except Exception as err:
            logger.error(f"❌ Не удалось перевыпустить свои cookies: {err}")
            self.last_cookies = None

    # ------------------------------ вспомогательное ------------------------------

    def _fetch_cookies(self) -> dict:
        from curl_cffi import requests

        session = requests.Session(impersonate=IMPERSONATE)
        if self.proxy is not None:
            proxy_url = self.proxy.get_httpx_proxy()
            if proxy_url:
                session.proxies = {"http": proxy_url, "https": proxy_url}

        logger.info(f"🍪 Получаю свои cookies: GET {TARGET_URL} (impersonate={IMPERSONATE})")
        response = session.get(TARGET_URL, headers=HEADERS, timeout=30)

        cookies = dict(session.cookies)
        if not cookies:
            raise RuntimeError(
                f"Avito вернул пустые cookies (status={response.status_code})"
            )
        self.last_cookies = cookies
        self._save_to_disk()
        logger.info(f"✅ Свои cookies получены ({len(cookies)} шт.)")
        return cookies

    def _load_from_disk(self):
        if not self.storage_path.exists():
            logger.info("Нет сохранённых собственных cookies")
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            cookies = data.get("cookies")
            if isinstance(cookies, dict) and cookies:
                self.last_cookies = cookies
                logger.info("📂 Загружены собственные cookies с диска")
            else:
                logger.warning("Файл cookies есть, но в нём нет cookies")
        except Exception as err:
            logger.warning(f"Не удалось загрузить собственные cookies: {err}")

    def _save_to_disk(self):
        if not self.last_cookies:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "cookies": self.last_cookies,
                "saved_at": time.time(),
                "cookie_count": len(self.last_cookies),
            }
            self.storage_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as err:
            logger.warning(f"Не удалось сохранить собственные cookies: {err}")
