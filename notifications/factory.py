from domain.config import AvitoConfig
from notifications.base import Notifier
from notifications.composite import NullNotifier, CompositeNotifier
from notifications.telegram import TelegramNotifier
from notifications.vk import VKNotifier
from engine.proxies.proxy import Proxy
from engine.proxies.proxy_factory import build_proxy


def build_notifier(config: AvitoConfig, *, avito_proxy: Proxy | None = None) -> Notifier:
    notifiers = []
    photo_proxy = (avito_proxy if avito_proxy is not None else build_proxy(config)).get_httpx_proxy()

    if config.messengers.tg_token:
        for _chat_id in config.messengers.tg_chat_id:
            notifiers.append(TelegramNotifier(bot_token=config.messengers.tg_token,
                                              chat_id=_chat_id,
                                              proxy=config.messengers.proxy_notifier,
                                              photo_proxy=photo_proxy,
                                              ))

    if config.messengers.vk_token:
        for _user_id in config.messengers.vk_user_id:
            notifiers.append(VKNotifier(vk_token=config.messengers.vk_token, user_id=_user_id,
                                        proxy=config.messengers.proxy_notifier,
                                        photo_proxy=photo_proxy))

    if notifiers:
        return CompositeNotifier(notifiers)

    return NullNotifier()  # если уведомления вообще не нужны
