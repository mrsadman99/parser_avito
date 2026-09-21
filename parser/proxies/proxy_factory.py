from loguru import logger

from dto import AvitoConfig
from .proxy import NoProxy, ServerProxy, ExternalMobileProxy, OwnMobileProxy, Proxy


def build_proxy(config: AvitoConfig) -> Proxy:
    """
    Определяет тип прокси (свой мобильный / внешний мобильный / серверный / без прокси).

    Свой мобильный прокси — tinyproxy на телефоне (SSH, без adb forward).
    Внешний мобильный прокси может иметь НЕСКОЛЬКО ссылок смены IP:
        change_url = "..."            # основная (одиночная)
        change_urls = ["...", "..."]  # дополнительные (fallback)
    Если одна ссылка не смогла сменить IP — парсер пробует следующую.
    """
    if config.own_mobile_proxy.use:
        logger.info("Прокси определён как свой мобильный (tinyproxy на телефоне по SSH)")
        return OwnMobileProxy(
            ssh=config.own_mobile_proxy.ssh,
            port=config.own_mobile_proxy.port,
            rotate_ip=config.own_mobile_proxy.rotate_ip,
            login=config.own_mobile_proxy.login or None,
            password=config.own_mobile_proxy.password or None,
            spfa_server=config.own_mobile_proxy.server or None,
        )

    change_urls = []
    if config.external_mobile_proxy.change_url:
        change_urls.append(config.external_mobile_proxy.change_url)
    if config.external_mobile_proxy.change_urls:
        for cu in config.external_mobile_proxy.change_urls:
            if cu and cu not in change_urls:
                change_urls.append(cu)

    if change_urls and not config.external_mobile_proxy.proxy_string:
        raise ValueError("change_url указан без proxy_string")

    if config.external_mobile_proxy.proxy_string and change_urls:
        logger.info(f"Прокси определён как внешний мобильный (ссылок смены IP: {len(change_urls)})")
        return ExternalMobileProxy(
            config.external_mobile_proxy.proxy_string,
            change_urls,
            change_ip_proxy=config.messengers.proxy_notifier,
        )

    if config.external_mobile_proxy.proxy_string:
        logger.info("Прокси определён как серверный")
        return ServerProxy(config.external_mobile_proxy.proxy_string)

    return NoProxy()
