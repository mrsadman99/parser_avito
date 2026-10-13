import hashlib
import requests
from loguru import logger

from integrations.notifications.base import Notifier
from integrations.notifications.photos import download_photo
from integrations.notifications.transport import send_with_retries
from models import Item
from proxy_helpers import build_proxies_dict


class TelegramNotifier(Notifier):
    def __init__(self, bot_token: str, chat_id: str, proxy: str = None, *, photo_proxy: str = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.proxy = self.get_proxy(proxy=proxy)
        self.photo_proxy = self.get_proxy(proxy=photo_proxy)
        self.delivery_key = "telegram:" + hashlib.sha256(
            f"{bot_token.split(':', 1)[0]}:{chat_id}".encode()
        ).hexdigest()

    @staticmethod
    def get_proxy(proxy: str = None):
        return build_proxies_dict(proxy)

    def notify_message(self, message: str):
        def _send():
            return requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "MarkdownV2",
                },
                proxies=self.proxy,
                timeout=30,
            )

        send_with_retries(_send)

    def _send_photo(self, photo_url: str, caption: str) -> None:
        self._send_photo_bytes(self._download_photo(photo_url), caption)

    def _download_photo(self, photo_url: str) -> bytes:
        return download_photo(photo_url, self.photo_proxy)

    def _send_photo_bytes(self, image_bytes: bytes, caption: str) -> None:
        def _send():
            return requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendPhoto",
                data={
                    "chat_id": self.chat_id,
                    "caption": caption,
                    "parse_mode": "MarkdownV2",
                },
                files={"photo": ("photo.jpg", image_bytes, "image/jpeg")},
                proxies=self.proxy,
                timeout=30,
            )

        send_with_retries(_send)

    def notify_ad(self, ad: Item):
        """Отправляет объявление с главным фото; при ошибке — фолбэк на текст."""
        message = self.format(ad)
        photo_url = ad.main_image_url()

        if not photo_url:
            self.notify_message(message)
            return

        try:
            self._send_photo(photo_url, message)
        except Exception as err:
            logger.warning(f"[notify] не удалось отправить фото, фолбэк на текст: {err}")
            self.notify_message(message)

    def notify(self, ad: Item = None, message: str = None):
        if ad:
            return self.notify_ad(ad=ad)
        return self.notify_message(message=message)
