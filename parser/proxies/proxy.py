from abc import ABC, abstractmethod
import time

import requests
from loguru import logger


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
        pass


class ServerProxy(Proxy):
    def __init__(self, proxy):
        self.proxy = proxy

    def get_httpx_proxy(self):
        return f"http://{self.proxy}"

    def handle_block(self):
        pass


class MobileProxy(Proxy):
    CHANGE_IP_RETRIES = 3
    CHANGE_IP_TIMEOUT = 30
    CHANGE_IP_RETRY_DELAY = 5

    def __init__(self, url, change_ip_url, change_ip_proxy=None):
        self.url = url
        self.change_ip_url = change_ip_url
        # прокси, через который ходить на сервис смены IP
        # (если changeip.mobileproxy.space недоступен напрямую)
        self.change_ip_proxy = change_ip_proxy

    def get_httpx_proxy(self):
        return f"http://{self.url}"

    def _change_ip_proxies(self):
        if not self.change_ip_proxy:
            return None
        proxy = f"http://{self.change_ip_proxy}"
        return {"http": proxy, "https": proxy}

    def handle_block(self):
        # делаем запрос на смену IP (с повторами, бОльшим таймаутом
        # и через proxy_notifier, если он задан)
        params = {"format": "json"}
        proxies = self._change_ip_proxies()
        if proxies:
            logger.info(
                f"Смена IP через прокси {self.change_ip_proxy}"
            )
        last_err = None
        for attempt in range(1, self.CHANGE_IP_RETRIES + 1):
            try:
                res = requests.get(
                    self.change_ip_url,
                    params=params,
                    timeout=self.CHANGE_IP_TIMEOUT,
                    proxies=proxies,
                )
                if res.status_code == 200:
                    new_ip = res.json().get("new_ip")
                    logger.success(f"новый IP {new_ip}")
                    return True
                logger.warning(
                    f"[{attempt}/{self.CHANGE_IP_RETRIES}] Смена IP: "
                    f"неожиданный статус {res.status_code}"
                )
            except Exception as err:
                last_err = err
                logger.warning(
                    f"[{attempt}/{self.CHANGE_IP_RETRIES}] Ошибка при смене IP: {err}"
                )
            if attempt < self.CHANGE_IP_RETRIES:
                time.sleep(self.CHANGE_IP_RETRY_DELAY)

        logger.error(
            f"Не удалось сменить IP за {self.CHANGE_IP_RETRIES} попытки: {last_err}"
        )
        return False
