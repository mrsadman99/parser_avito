import subprocess
from abc import ABC, abstractmethod
import time

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
        """Return a Playwright/Camoufox proxy dict ({server, username, password}) or None."""
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
                        headers={"User-Agent": BROWSER_USER_AGENT},
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


class AdbMicrosocksProxy(Proxy):
    """Мобильный прокси через телефон: microsocks на Android + проброс adb forward.

    Трафик идёт: Camoufox -> http://127.0.0.1:<local_port> -> adb -> microsocks
    на телефоне -> мобильная сеть. Смена IP — через airplane mode по adb.
    """

    ROTATE_WAIT_OFF = 3   # пауза после включения airplane mode
    ROTATE_WAIT_ON = 8    # пауза после выключения (получение нового IP)

    def __init__(self, local_port=1080, remote_port=1080, device_serial=None, rotate_ip=True,
                 login=None, password=None, spfa_server=None):
        self.local_port = local_port
        self.remote_port = remote_port
        self.device_serial = device_serial
        self.rotate_ip = rotate_ip
        self.login = login
        self.password = password
        self.spfa_server = spfa_server
        self.host = f"127.0.0.1:{self.local_port}"
        auth = f"{login}:{password}@" if login and password else ""
        self.proxy_url = f"http://{auth}{self.host}"
        self._ensure_forward()

    def _adb(self, *args):
        cmd = ["adb"]
        if self.device_serial:
            cmd += ["-s", self.device_serial]
        cmd += list(args)
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except Exception as err:
            logger.warning(f"Ошибка adb {list(args)}: {err}")
            return None

    def _ensure_forward(self):
        result = self._adb("forward", f"tcp:{self.local_port}", f"tcp:{self.remote_port}")
        if result is None:
            logger.warning("Не удалось выполнить adb forward")
        elif result.returncode == 0:
            logger.info(
                f"ADB: проброшен порт tcp:{self.local_port} -> tcp:{self.remote_port} (microsocks)"
            )
        else:
            logger.warning(f"adb forward ошибка: {result.stderr.strip()}")

    def get_httpx_proxy(self):
        return self.proxy_url

    def get_playwright_proxy(self):
        proxy = {"server": f"http://{self.host}"}
        if self.login and self.password:
            proxy["username"] = self.login
            proxy["password"] = self.password
        return proxy

    def get_spfa_proxy_string(self):
        host = self.spfa_server or self.host
        auth = f"{self.login}:{self.password}@" if self.login and self.password else ""
        return f"{auth}{host}"

    def handle_block(self):
        if not self.rotate_ip:
            logger.warning("Смена IP через adb отключена (adb_rotate_ip=false)")
            return False
        return self._rotate_ip()

    def _rotate_ip(self):
        logger.info("🔄 Смена IP: включаю airplane mode через adb...")
        self._adb("shell", "settings", "put", "global", "airplane_mode_on", "1")
        self._adb(
            "shell", "am", "broadcast",
            "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", "true",
        )
        time.sleep(self.ROTATE_WAIT_OFF)

        self._adb("shell", "settings", "put", "global", "airplane_mode_on", "0")
        self._adb(
            "shell", "am", "broadcast",
            "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", "false",
        )
        time.sleep(self.ROTATE_WAIT_ON)

        # после перезагрузки сети пробрасываем порт заново (на случай сброса adbd)
        self._ensure_forward()
        logger.success("IP обновлён через adb (airplane mode)")
        return True
