"""CRUD ссылок-подписок (web-БД) + read-only ссылки из config.toml."""
from datetime import date
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from load_config import load_avito_config
from persistence import store
from server.routers.auth import current_actor

router = APIRouter()


class LinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)
    min_price: int | None = Field(default=None, ge=0, le=9_000_000_000_000_000)
    max_price: int | None = Field(default=None, ge=0, le=9_000_000_000_000_000)
    white_list: list[str] = Field(default_factory=list, max_length=100)
    black_list: list[str] = Field(default_factory=list, max_length=100)
    geo: str | None = None
    start_date: str | None = None
    ignore_reserv: bool | None = None
    ignore_promotion: bool | None = None
    username: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        value = value.strip()
        try:
            parsed = urlsplit(value)
            host = (parsed.hostname or "").lower()
            valid = (
                parsed.scheme in {"http", "https"}
                and (host == "avito.ru" or host.endswith(".avito.ru"))
                and parsed.username is None and parsed.password is None
                and parsed.port in {None, 80, 443}
                and not any(c.isspace() or ord(c) < 32 for c in value)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Укажите корректную ссылку http(s) на avito.ru")
        return value

    @field_validator("start_date")
    @classmethod
    def validate_date(cls, value):
        if not value or not value.strip():
            return None
        value = value.strip()
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value:
                raise ValueError
        except ValueError:
            raise ValueError("Дата должна быть в формате ГГГГ-ММ-ДД")
        return value

    @field_validator("white_list", "black_list")
    @classmethod
    def normalize_words(cls, values):
        words = list(dict.fromkeys(word.strip() for word in values if word.strip()))
        if any(len(word) > 200 for word in words):
            raise ValueError("Ключевое слово не должно превышать 200 символов")
        return words

    @model_validator(mode="after")
    def validate_prices(self):
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("Минимальная цена не должна превышать максимальную")
        return self


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
