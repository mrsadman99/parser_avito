from abc import ABC, abstractmethod
import time

import requests
from loguru import logger

from proxy_helpers import build_proxies_dict


class Proxy(ABC):
    @abstractmethod
    def get_httpx_proxy(self) -> dict | None:
        pass

    @abstractmethod
    def handle_block(self):
        pass


class NoProxy(Proxy):
    def get_httpx_proxy(self):
        return None

    def handle_block(self):
        return False


class ServerProxy(Proxy):
    def __init__(self, proxy):
        self.proxy = proxy

    def get_httpx_proxy(self):
        return f"http://{self.proxy}"

    def handle_block(self):
        # серверный прокси не умеет менять IP
        return False


class MobileProxy(Proxy):
    CHANGE_IP_RETRIES = 3
    CHANGE_IP_TIMEOUT = 30
    CHANGE_IP_RETRY_DELAY = 5

    def __init__(self, url, change_ip_urls, change_ip_proxy=None):
        self.url = url
        # список ссылок смены IP (fallback: если одна не сработала — пробуем следующую)
        self.change_ip_urls = list(change_ip_urls) if change_ip_urls else []
        # прокси, через который ходить на сервис смены IP
        # (если changeip.mobileproxy.space недоступен напрямую)
        self.change_ip_proxy = change_ip_proxy

    def get_httpx_proxy(self):
        return f"http://{self.url}"

    def _change_ip_proxies(self):
        return build_proxies_dict(self.change_ip_proxy)

    def handle_block(self):
        # делаем запрос на смену IP: перебираем все ссылки по очереди,
        # каждая с повторами и через proxy_notifier, если он задан
        params = {"format": "json"}
        proxies = self._change_ip_proxies()
        if proxies:
            logger.info(f"Смена IP через прокси {self.change_ip_proxy}")

        last_err = None
        for url_index, change_ip_url in enumerate(self.change_ip_urls, start=1):
            for attempt in range(1, self.CHANGE_IP_RETRIES + 1):
                try:
                    res = requests.get(
                        change_ip_url,
                        params=params,
                        timeout=self.CHANGE_IP_TIMEOUT,
                        proxies=proxies,
                    )
                    if res.status_code == 200:
                        new_ip = res.json().get("new_ip")
                        logger.success(
                            f"новый IP {new_ip} (ссылка смены #{url_index})"
                        )
                        return True
                    logger.warning(
                        f"[ссылка {url_index}/{len(self.change_ip_urls)}] "
                        f"[попытка {attempt}/{self.CHANGE_IP_RETRIES}] "
                        f"неожиданный статус {res.status_code}"
                    )
                except Exception as err:
                    last_err = err
                    logger.warning(
                        f"[ссылка {url_index}/{len(self.change_ip_urls)}] "
                        f"[попытка {attempt}/{self.CHANGE_IP_RETRIES}] "
                        f"ошибка: {err}"
                    )
                if attempt < self.CHANGE_IP_RETRIES:
                    time.sleep(self.CHANGE_IP_RETRY_DELAY)

        logger.error(
            f"Не удалось сменить IP ни по одной из {len(self.change_ip_urls)} ссылок: {last_err}"
        )
        return False
