from loguru import logger

from domain.item import Item
from .base import Notifier


class CompositeNotifier(Notifier):
    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = notifiers

    def notify(self, ad: Item = None, message: str = None):
        errors = []
        for notifier in self.notifiers:
            try:
                notifier.notify(ad=ad, message=message)
            except Exception as e:
                errors.append(e)
                logger.exception(
                    f"Ошибка {e} отправки уведомления через {notifier.__class__.__name__}"
                )
        if errors:
            raise RuntimeError("Не все уведомления доставлены") from errors[0]

    def delivery_targets(self):
        return {key: target for notifier in self.notifiers
                for key, target in notifier.delivery_targets().items()}


class NullNotifier(Notifier):
    def delivery_targets(self):
        return {}

    def notify(self, ad: Item = None, message: str = None):
        pass
