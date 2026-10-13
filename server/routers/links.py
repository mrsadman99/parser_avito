"""CRUD ссылок-подписок (web-БД) + read-only ссылки из config.toml."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from load_config import load_avito_config
from persistence import store
from server.routers.auth import current_actor

router = APIRouter()


class LinkRequest(BaseModel):
    url: str = Field(min_length=1)
    min_price: int | None = None
    max_price: int | None = None
    white_list: list[str] = []
    black_list: list[str] = []
    geo: str | None = None
    start_date: str | None = None
    ignore_reserv: bool | None = None
    ignore_promotion: bool | None = None
    username: str | None = None


def _config_links() -> list[dict]:
    """Ссылки из config.toml ([avito.links]) — только для чтения в админке."""
    try:
        config = load_avito_config("config.toml")
    except Exception:
        return []
    result = []
    for url, lc in (config.links or {}).items():
        result.append(
            {
                "id": None,
                "url": url,
                "min_price": lc.min_price,
                "max_price": lc.max_price,
                "white_list": list(lc.white_list or []),
                "black_list": list(lc.black_list or []),
                "geo": lc.geo,
                "start_date": lc.start_date,
                "ignore_reserv": lc.ignore_reserv,
                "ignore_promotion": lc.ignore_promotion,
                "username": "config",
                "readonly": True,
            }
        )
    return result


@router.get("/api/links")
def list_links(actor: dict = Depends(current_actor)):
    if actor["is_admin"]:
        db_links = store.list_all_links()
        return _config_links() + db_links
    return store.list_links(actor["id"])


@router.post("/api/links", status_code=201)
def create_link(req: LinkRequest, actor: dict = Depends(current_actor)):
    if actor["is_admin"]:
        link = store.create_link_any(req.model_dump())
        if link is None:
            raise HTTPException(status_code=400, detail="Укажите логин владельца и ссылку")
        return link
    return store.create_link(actor["id"], req.model_dump())


@router.put("/api/links/{link_id}")
def update_link(link_id: int, req: LinkRequest, actor: dict = Depends(current_actor)):
    if actor["is_admin"]:
        link = store.update_link_any(link_id, req.model_dump())
    else:
        link = store.update_link(actor["id"], link_id, req.model_dump())
    if link is None:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    return link


@router.delete("/api/links/{link_id}")
def delete_link(link_id: int, actor: dict = Depends(current_actor)):
    if actor["is_admin"]:
        ok = store.delete_link_any(link_id)
    else:
        ok = store.delete_link(actor["id"], link_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    return {"ok": True}
