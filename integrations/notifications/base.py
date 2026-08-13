from abc import ABC, abstractmethod

from integrations.notifications.utils import escape_markdown_v2, get_price
from models import Item
from parser.specs import extract_specs, format_specs_lines


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

        # Оценка DeepSeek (цена/производительность)
        ai_score = getattr(ad, "ai_score", 0) or 0
        if ai_score:
            parts.append(f"🤖 Оценка: *{ai_score}/100*")
            ai_reason = (getattr(ad, "ai_reason", "") or "").strip()
            if ai_reason:
                parts.append(f"_{escape_markdown_v2(ai_reason)}_")

        # Характеристики ПК (сначала от DeepSeek, иначе — из текста)
        specs = getattr(ad, "ai_specs", None) or {}
        if not specs:
            specs = extract_specs(
                f"{getattr(ad, 'title', '') or ''} {getattr(ad, 'description', '') or ''}"
            )
        for line in format_specs_lines(specs):
            parts.append(escape_markdown_v2(line))

        # Описание объявления (сокращённое до 250 символов)
        description = (getattr(ad, "description", "") or "").strip()
        if description:
            if len(description) > 250:
                description = description[:250] + "…"
            parts.append(escape_markdown_v2(description))

        if seller:
            parts.append(f"Продавец: {seller}")

        return "\n".join(parts)
