from loguru import logger

from dto import AvitoConfig
from .proxy import NoProxy, ServerProxy, MobileProxy, Proxy


def build_proxy(config: AvitoConfig) -> Proxy:
    """
    Определяет тип прокси (мобильный/серверный/без прокси).

    Мобильный прокси может иметь НЕСКОЛЬКО ссылок смены IP:
        proxy_change_url = "..."            # основная (одиночная)
        proxy_change_urls = ["...", "..."]  # дополнительные (fallback)
    Если одна ссылка не смогла сменить IP — парсер пробует следующую.
    """
    change_urls = []
    if config.proxy_change_url:
        change_urls.append(config.proxy_change_url)
    if config.proxy_change_urls:
        for cu in config.proxy_change_urls:
            if cu and cu not in change_urls:
                change_urls.append(cu)

    if change_urls and not config.proxy_string:
        raise ValueError("proxy_change_url указан без proxy_string")

    if config.proxy_string and change_urls:
        logger.info(f"Прокси определен как мобильный (ссылок смены IP: {len(change_urls)})")
        return MobileProxy(
            config.proxy_string,
            change_urls,
            change_ip_proxy=config.proxy_notifier,
        )

    if config.proxy_string:
        logger.info("Прокси определен как серверный")
        return ServerProxy(config.proxy_string)

    return NoProxy()

