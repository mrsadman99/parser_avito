"""Извлечение данных объявления из HTML детальной страницы Avito.

Источники (по приоритету):
  1. JSON-LD (schema.org Product) — title/description/price/url/sku/image;
  2. window.__staticRouterHydrationData — город, адрес, доставка, рейтинг/отзывы, фото;
  3. HTML-маркеры (data-marker / itemprop) — фолбэк.
"""
import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

# Признаки страницы «объявление удалено/не найдено»
REMOVED_MARKERS = (
    "объявление не найдено",
    "объявление удалено",
    "снято с публикации",
    "объявление заблокировано",
    "больше не доступно",
    "объявление снято",
)


def _clean(value: Any) -> Optional[str]:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def _digits(value: Any) -> Optional[int]:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else None


def _json_ld_product(soup: BeautifulSoup) -> Optional[dict]:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        nodes = data.get("@graph") if isinstance(data, dict) else None
        nodes = nodes if isinstance(nodes, list) else [data]
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") == "Product":
                return node
    return None


def _hydration_data(html: str) -> Optional[Any]:
    """Парсит window.__staticRouterHydrationData = JSON.parse("...")."""
    match = re.search(
        r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("(.*?)"\)\s*;',
        html,
        re.S,
    )
    if not match:
        return None
    try:
        inner = json.loads('"' + match.group(1) + '"')
        return json.loads(inner)
    except (ValueError, TypeError):
        return None


def _find_value(data: Any, key: str) -> Any:
    """Первое значение по ключу key (рекурсивно)."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k == key:
                return v
            found = _find_value(v, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_value(item, key)
            if found is not None:
                return found
    return None


def _find_dict_with(data: Any, key: str) -> Optional[dict]:
    """Первый dict-значение по ключу key (рекурсивно)."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k == key and isinstance(v, dict):
                return v
            found = _find_dict_with(v, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_dict_with(item, key)
            if found is not None:
                return found
    return None


def _find_dict_containing(data: Any, key: str) -> Optional[dict]:
    """Первый dict, содержащий ключ key (рекурсивно)."""
    if isinstance(data, dict):
        if key in data:
            return data
        for v in data.values():
            found = _find_dict_containing(v, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_dict_containing(item, key)
            if found is not None:
                return found
    return None


def parse_ad_html(html: str) -> dict:
    """Возвращает поля объявления из HTML детальной страницы.

    Ключи: id, title, description, price, ad_url, city, address,
           has_delivery, photo_url, seller_rating, seller_reviews,
           available, removed.
    """
    result = {
        "id": None,
        "title": None,
        "description": None,
        "price": None,
        "ad_url": None,
        "city": None,
        "address": None,
        "has_delivery": None,
        "photo_url": None,
        "seller_rating": None,
        "seller_reviews": None,
    }
    soup = BeautifulSoup(html, "html.parser")

    # 1) JSON-LD (Product)
    product = _json_ld_product(soup)
    if product:
        result["title"] = _clean(product.get("name"))
        result["description"] = _clean(product.get("description"))
        offers = product.get("offers")
        if isinstance(offers, dict):
            result["price"] = _to_int(offers.get("price"))
            result["ad_url"] = _clean(offers.get("url"))
        result["id"] = _to_int(product.get("sku"))
        images = product.get("image")
        if isinstance(images, list) and images:
            result["photo_url"] = _clean(images[0])

    # 2) Гидратация (window.__staticRouterHydrationData)
    data = _hydration_data(html)
    if data is not None:
        full = _find_dict_with(data, "fullAddress")
        if isinstance(full, dict):
            result["city"] = _clean(full.get("locality"))
        geo = _find_dict_with(data, "geo")
        if isinstance(geo, dict):
            result["city"] = result["city"] or _clean(geo.get("name"))
            result["address"] = _clean(geo.get("address"))

        for key in ("deliveryButtonEnabled", "isDelivery", "isWithDelivery"):
            value = _find_value(data, key)
            if value is True:
                result["has_delivery"] = True
                break
        if result["has_delivery"] is None:
            value = _find_value(data, "deliveryButtonEnabled")
            if value is not None:
                result["has_delivery"] = bool(value)

        rating = _find_dict_containing(data, "scoreFloat")
        if isinstance(rating, dict):
            score = rating.get("scoreFloat")
            if isinstance(score, (int, float)):
                result["seller_rating"] = float(score)
            reviews = rating.get("useStarsReviewCount")
            result["seller_reviews"] = reviews if isinstance(reviews, int) else _digits(rating.get("summary"))

        # реальное фото из галереи приоритетнее share-картинки из JSON-LD
        sizes = _find_dict_containing(data, "1280x960")
        if isinstance(sizes, dict):
            photo = _clean(sizes.get("1280x960"))
            if photo:
                result["photo_url"] = photo

    # 3) HTML-фолбэки
    if result["description"] is None:
        marker = soup.select_one('[data-marker="item-view/item-description"]')
        if marker:
            result["description"] = _clean(marker.get_text("\n", strip=True))
    if result["price"] is None:
        marker = soup.select_one('[data-marker="item-view/item-price"]')
        if marker:
            result["price"] = _digits(marker.get_text())
    if result["seller_rating"] is None:
        meta = soup.select_one('meta[itemprop="ratingValue"]')
        if meta and meta.get("content"):
            try:
                result["seller_rating"] = float(meta["content"])
            except ValueError:
                pass
    if result["photo_url"] is None:
        img = soup.select_one('img[src*="img.avito.st/image"]')
        if img:
            result["photo_url"] = _clean(img.get("src"))

    result["available"] = bool(
        result["title"] or result["price"] or result["description"]
    )
    result["removed"] = _is_removed_page(soup, result["available"])
    return result


def _is_removed_page(soup: BeautifulSoup, available: bool) -> bool:
    if available:
        return False
    text = soup.get_text(" ", strip=True).lower()
    return any(marker in text for marker in REMOVED_MARKERS)
