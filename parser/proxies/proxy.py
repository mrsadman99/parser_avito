import time
from abc import ABC, abstractmethod

import requests
from loguru import logger

from proxy_helpers import build_proxies_dict, BROWSER_USER_AGENT


class Proxy(ABC):
    @abstractmethod
    def get_httpx_proxy(self) -> dict | None:
        pass

    @abstractmethod
    def handle_block(self):
        pass

    def get_playwright_proxy(self) -> dict | None:
        """Return a Camoufox proxy dict ({server, username, password}) or None."""
        return None

    def get_spfa_proxy_string(self) -> str | None:
        """Строка прокси для передачи во внешний сервис (login:password@host:port)."""
        return None


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


class ExternalMobileProxy(Proxy):
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
        """Смена IP внешнего мобильного прокси: перебираем change_urls по порядку,
        пока запрос не выполнится успешно (успех = 200 и непустой `new_ip`)."""
        if not self.change_ip_urls:
            logger.warning("Смена IP недоступна: не задан change_urls")
            return False

        params = {"format": "json"}
        proxies = self._change_ip_proxies()
        if proxies:
            logger.info(f"Смена IP через прокси {self.change_ip_proxy}")

        total = len(self.change_ip_urls)
        for url_index, change_ip_url in enumerate(self.change_ip_urls, start=1):
            for attempt in range(1, self.CHANGE_IP_RETRIES + 1):
                try:
                    res = requests.get(
                        change_ip_url,
                        params=params,
                        timeout=self.CHANGE_IP_TIMEOUT,
                        proxies=proxies,
                        headers={"User-Agent": BROWSER_USER_AGENT},
                    )
                    if res.status_code == 200:
                        try:
                            new_ip = res.json().get("new_ip")
                        except ValueError:
                            new_ip = None
                        if new_ip:
                            logger.success(
                                f"новый IP {new_ip} (ссылка смены {url_index}/{total})"
                            )
                            return True
                        logger.warning(
                            f"[ссылка {url_index}/{total}] "
                            f"[попытка {attempt}/{self.CHANGE_IP_RETRIES}] "
                            f"статус 200, но new_ip пустой"
                        )
                    else:
                        logger.warning(
                            f"[ссылка {url_index}/{total}] "
                            f"[попытка {attempt}/{self.CHANGE_IP_RETRIES}] "
                            f"статус {res.status_code}"
                        )
                except Exception as err:
                    logger.warning(
                        f"[ссылка {url_index}/{total}] "
                        f"[попытка {attempt}/{self.CHANGE_IP_RETRIES}] "
                        f"ошибка: {err}"
                    )
                if attempt < self.CHANGE_IP_RETRIES:
                    time.sleep(self.CHANGE_IP_RETRY_DELAY)

        logger.error(f"Не удалось сменить IP ни по одной из {total} ссылок change_urls")
        return False


class OwnMobileProxy(Proxy):
    """Свой мобильный прокси: tinyproxy на телефоне, запуск по SSH (без adb forward).

    Адрес прокси собирается из `server` (own_mobile_proxy.server) и `port`
    (own_mobile_proxy.port): {server}:{port}. Если `server` пуст — берётся ssh.host.
    Трафик идёт: Camoufox -> http://{server}:{port} -> tinyproxy на телефоне
    -> мобильная сеть. Смена IP — режим полёта через adb (adb_serial).
    """

    def __init__(self, adb_serial=None, server=None, port=8888, rotate_ip=True,
                 login=None, password=None, ssh=None):
        self.adb_serial = adb_serial
        self.ssh = ssh
        self.port = int(port or 8888)
        host = (server or "").strip() or (getattr(ssh, "host", "") or "").strip()
        if host and ":" not in host:
            host = f"{host}:{self.port}"
        self.host = host or f"127.0.0.1:{self.port}"
        self.rotate_ip = rotate_ip
        self.login = login
        self.password = password
        auth = f"{login}:{password}@" if login and password else ""
        self.proxy_url = f"http://{auth}{self.host}"

    def get_httpx_proxy(self):
        return self.proxy_url

    def get_playwright_proxy(self):
        proxy = {"server": f"http://{self.host}"}
        if self.login and self.password:
            proxy["username"] = self.login
            proxy["password"] = self.password
        return proxy

    def get_spfa_proxy_string(self):
        auth = f"{self.login}:{self.password}@" if self.login and self.password else ""
        return f"{auth}{self.host}"

    def handle_block(self):
        if not self.rotate_ip:
            logger.warning("Смена IP своего мобильного прокси отключена (rotate_ip = false)")
            return False
        from utils.own_mobile_proxy import rotate_ip
        return rotate_ip(self.adb_serial, ssh=self.ssh)
