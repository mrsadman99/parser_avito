"""Выдача результатов парсинга по подписке/URL."""
from fastapi import APIRouter, Depends, HTTPException

from domain.config import web_link_key
from persistence import store
from persistence.ads import SQLiteDBHandler
from server.routers.auth import current_actor

router = APIRouter()


@router.get("/api/ads")
def list_ads(url: str | None = None, link_id: int | None = None,
             actor: dict = Depends(current_actor)):
    """Результаты конкретной подписки с проверкой её владельца."""
    if link_id is not None:
        link = store.get_link(link_id)
        if link is None or (not actor["is_admin"] and link["user_id"] != actor["id"]):
            raise HTTPException(status_code=404, detail="Ссылка не найдена")
        return SQLiteDBHandler().list_ads(link["url"], source_keys=[web_link_key(link_id, link["url"])])
    if not url:
        raise HTTPException(status_code=422, detail="Укажите link_id или url")
    if actor["is_admin"]:
        # URL используется для ссылок из TOML и старых записей без владельца.
        return SQLiteDBHandler().list_ads(url)
    keys = [web_link_key(link["id"], link["url"]) for link in store.list_links(actor["id"])
            if link["url"] == url]
    if not keys:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    return SQLiteDBHandler().list_ads(url, source_keys=keys)
