from dto import AvitoConfig
from integrations.notifications.base import Notifier
from integrations.notifications.composite import NullNotifier, CompositeNotifier
from integrations.notifications.telegram import TelegramNotifier
from integrations.notifications.vk import VKNotifier


def build_notifier(config: AvitoConfig) -> Notifier:
    notifiers = []

    if config.messengers.tg_token:
        for _chat_id in config.messengers.tg_chat_id:
            notifiers.append(TelegramNotifier(bot_token=config.messengers.tg_token,
                                              chat_id=_chat_id,
                                              proxy=config.messengers.proxy_notifier,
                                              ))

    if config.messengers.vk_token:
        for _user_id in config.messengers.vk_user_id:
            notifiers.append(VKNotifier(vk_token=config.messengers.vk_token, user_id=_user_id))

    if notifiers:
        return CompositeNotifier(notifiers)

    return NullNotifier()  # если уведомления вообще не нужны
