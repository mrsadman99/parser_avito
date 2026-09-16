from loguru import logger

from dto import AvitoConfig
from .proxy import NoProxy, ServerProxy, MobileProxy, AdbMicrosocksProxy, Proxy


def build_proxy(config: AvitoConfig) -> Proxy:
    """
    Определяет тип прокси (adb-мобильный/мобильный/серверный/без прокси).

    Мобильный прокси может иметь НЕСКОЛЬКО ссылок смены IP:
        change_url = "..."            # основная (одиночная)
        change_urls = ["...", "..."]  # дополнительные (fallback)
    Если одна ссылка не смогла сменить IP — парсер пробует следующую.
    """
    if config.adb_proxy.use:
        logger.info("Прокси определён как ADB (tinyproxy/microsocks на телефоне)")
        return AdbMicrosocksProxy(
            local_port=config.adb_proxy.local_port,
            remote_port=config.adb_proxy.remote_port,
            device_serial=config.adb_proxy.device_serial or None,
            rotate_ip=config.adb_proxy.rotate_ip,
            login=config.adb_proxy.login or None,
            password=config.adb_proxy.password or None,
            spfa_server=config.adb_proxy.server or None,
        )

    change_urls = []
    if config.mobile_proxy.change_url:
        change_urls.append(config.mobile_proxy.change_url)
    if config.mobile_proxy.change_urls:
        for cu in config.mobile_proxy.change_urls:
            if cu and cu not in change_urls:
                change_urls.append(cu)

    if change_urls and not config.mobile_proxy.proxy_string:
        raise ValueError("change_url указан без proxy_string")

    if config.mobile_proxy.proxy_string and change_urls:
        logger.info(f"Прокси определен как мобильный (ссылок смены IP: {len(change_urls)})")
        return MobileProxy(
            config.mobile_proxy.proxy_string,
            change_urls,
            change_ip_proxy=config.messengers.proxy_notifier,
        )

    if config.mobile_proxy.proxy_string:
        logger.info("Прокси определен как серверный")
        return ServerProxy(config.mobile_proxy.proxy_string)

    return NoProxy()
