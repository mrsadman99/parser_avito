from abc import ABC, abstractmethod

from integrations.notifications.utils import escape_markdown_v2, get_price
from models import Item


class Notifier(ABC):

    @abstractmethod
    def notify(self, ad: Item = None, message: str = None):
        """Отправляем одно объявление"""
        pass

    def notify_many(self, ads: list[Item]):
        """Отправляем список объявлений"""
        for ad in ads:
            self.notify(ad=ad)

    # default форматирование
    def format(self, ad: Item) -> str:
        price = escape_markdown_v2(get_price(ad))
        title = escape_markdown_v2(getattr(ad, "title", ""))
        seller = escape_markdown_v2(str(getattr(ad, "sellerId", "")))
        short_url = f"https://avito.ru/{getattr(ad, 'id', '')}"

        parts = []

        if price:
            part = f"*{price}*"
            if getattr(ad, "isPromotion", False):
                part += " 🢁"
            parts.append(part)

        if title:
            parts.append(f"[{title}]({short_url})")

        # Описание объявления (сокращённое до 250 символов)
        description = (getattr(ad, "description", "") or "").strip()
        if description:
            if len(description) > 250:
                description = description[:250] + "…"
            parts.append(escape_markdown_v2(description))

        if seller:
            parts.append(f"Продавец: {seller}")

        rating = getattr(ad, "seller_rating", None)
        if rating is not None:
            reviews = getattr(ad, "seller_reviews", None)
            text = f"⭐ Рейтинг: {rating}"
            if reviews is not None:
                text += f" · {reviews} оценок"
            parts.append(escape_markdown_v2(text))

        return "\n".join(parts)
