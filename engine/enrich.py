"""Обогащение объявлений данными из каталога и детальной страницы.

Чистые функции без состояния: продавец (slug), признак «Продвинуто», рейтинг
продавца с числом оценок, полное описание со страницы объявления.
"""
import html as html_lib
import json
import re

from bs4 import BeautifulSoup

from domain.item import Item
from engine.jsonutil import digits, find_string


def extract_seller_slug(data) -> str | None:
    match = re.search(r"/brands/([^/?#]+)", str(data))
    if match:
        return match.group(1)
    return None


def add_seller_to_ads(ads: list[Item]) -> list[Item]:
    for ad in ads:
        if seller_id := extract_seller_slug(ad):
            ad.sellerId = seller_id
    return ads


def add_promotion_to_ads(ads: list[Item]) -> list[Item]:
    for ad in ads:
        ad.isPromotion = ad.is_promotion()
    return ads


def add_seller_rating(ads: list[Item]) -> list[Item]:
    """Достаёт рейтинг продавца и количество оценок из каталога (rating.score/summary)."""
    for ad in ads:
        rating = getattr(ad, "rating", None)
        if rating is None:
            continue
        if rating.score is not None:
            ad.seller_rating = float(rating.score)
        if rating.summary:
            reviews = digits(rating.summary)
            if reviews:
                ad.seller_reviews = reviews
    return ads


def extract_description(html: str) -> str | None:
    """Достаёт полное описание со страницы объявления (несколько стратегий)."""
    soup = BeautifulSoup(html, "html.parser")

    # 1) HTML-маркер блока описания
    marker = soup.select_one('[data-marker="item-view/item-description"]')
    if marker:
        text = marker.get_text("\n", strip=True)
        if text and len(text) > 50:
            return text

    # 2) JSON-LD (schema.org) — поле description
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        found = find_string(data, "description", min_len=50)
        if found:
            return found

    # 3) mfe-state JSON внутри страницы — рекурсивный поиск description
    for script in soup.select('script[data-mfe-state="true"]'):
        try:
            data = json.loads(html_lib.unescape(script.text))
        except (ValueError, TypeError):
            continue
        found = find_string(data, "description", min_len=50)
        if found:
            return found

    return None
