import requests
from loguru import logger

from integrations.notifications.base import Notifier
from integrations.notifications.transport import send_with_retries
from models import Item
from proxy_helpers import build_proxies_dict


class TelegramNotifier(Notifier):
    def __init__(self, bot_token: str, chat_id: str, proxy: str = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.proxy = self.get_proxy(proxy=proxy)

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
        def _send_url():
            return requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendPhoto",
                json={
                    "chat_id": self.chat_id,
                    "caption": caption,
                    "photo": photo_url,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True,
                },
                proxies=self.proxy,
                timeout=30,
            )

        try:
            send_with_retries(_send_url)
        except requests.HTTPError as err:
            resp = getattr(err, "response", None)
            if resp is not None and resp.status_code == 400:
                logger.info("[notify] sendPhoto URL отклонён (400), пробуем байтами")
                img = requests.get(photo_url, proxies=self.proxy, timeout=15)
                img.raise_for_status()
                self._send_photo_bytes(img.content, caption)
                return
            raise

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
