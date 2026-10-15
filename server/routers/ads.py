"""Выдача результатов парсинга по подписке/URL."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from domain.config import web_link_key
from persistence import store
from persistence.ads import SQLiteDBHandler
from server.routers.auth import current_actor

router = APIRouter()


def authorized_source(url: str | None, link_id: int | None, actor: dict):
    """Результаты конкретной подписки с проверкой её владельца."""
    if link_id is not None:
        link = store.get_link(link_id)
        if link is None or (not actor["is_admin"] and link["user_id"] != actor["id"]):
            raise HTTPException(status_code=404, detail="Ссылка не найдена")
        return link["url"], [web_link_key(link_id, link["url"])]
    if not url:
        raise HTTPException(status_code=422, detail="Укажите link_id или url")
    if actor["is_admin"]:
        # URL используется для ссылок из TOML и старых записей без владельца.
        return url, None
    keys = [web_link_key(link["id"], link["url"]) for link in store.list_links(actor["id"])
            if link["url"] == url]
    if not keys:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    return url, keys


@router.get("/api/ads")
def list_ads(url: str | None = None, link_id: int | None = None,
             actor: dict = Depends(current_actor)):
    """Совместимость с клиентами, ожидающими полный массив результатов."""
    source_url, keys = authorized_source(url, link_id, actor)
    return SQLiteDBHandler().list_ads(source_url, source_keys=keys)


@router.get("/api/ads/page")
def ads_page(
    url: str | None = None, link_id: int | None = None,
    page: int = Query(default=1, ge=1, le=1_000_000_000),
    page_size: int = Query(default=50, ge=1, le=200),
    sort: Literal["price", "scanned_at", "refreshed_at", "sort_time", "seller_reviews",
                  "seller_rating", "has_delivery", "city"] = "refreshed_at",
    direction: Literal["asc", "desc"] = "desc",
    delivery_only: bool = False,
    city: str = Query(default="", max_length=200),
    published_from: int | None = Query(default=None, ge=0, le=9_000_000_000_000_000),
    published_to: int | None = Query(default=None, ge=0, le=9_000_000_000_000_000),
    actor: dict = Depends(current_actor),
):
    if published_from is not None and published_to is not None and published_from > published_to:
        raise HTTPException(status_code=422, detail="Начало периода не должно быть позже окончания")
    source_url, keys = authorized_source(url, link_id, actor)
    return SQLiteDBHandler().list_ads_page(
        source_url, source_keys=keys, page=page, page_size=page_size,
        sort=sort, direction=direction, delivery_only=delivery_only, city=city,
        published_from=published_from, published_to=published_to,
    )
