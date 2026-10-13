"""REST API сервер: регистрация, авторизация, управление ссылками, раздача фронтенда.

Единые ручки: /api/links и /api/links/{id}. Админ (логин admin) видит/правит все ссылки.
В production-режиме (python run.py) раздаёт собранный фронтенд web-server/dist на "/".

Безопасность:
  - CORS ограничен списком (dev-origin + config.cors_origins);
  - rate-limit на /api/login и /api/register (in-memory);
  - фронтенд в production раздаётся как статика (без dev-сервера Vite).

Запуск (в составе python run.py или отдельно):
    uvicorn server.main:app --host 127.0.0.1 --port 8000
"""

import secrets
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field

from persistence.ads import SQLiteDBHandler
from domain.config import web_link_key
from load_config import load_avito_config
from persistence import store

_config = None


def get_config():
    """Загружает config.toml один раз и кэширует (None, если не удалось)."""
    global _config
    if _config is None:
        try:
            _config = load_avito_config("config.toml")
        except Exception:
            _config = None
    return _config


def _admin_password() -> str:
    config = get_config()
    return (config.server.admin_password or "").strip() if config else ""


def _web_port() -> int:
    config = get_config()
    return config.server.web_server_port if config else 3000


def _cors_extra() -> list:
    config = get_config()
    return list(config.server.cors_origins or []) if config else []


@asynccontextmanager
async def lifespan(app):
    store.init_db()
    if _admin_password() in ("", "admin"):
        logger.warning(
            "ВНИМАНИЕ: admin_password пуст или слабый ('admin'). Задайте сильный пароль в config.toml"
        )
    yield


_ADMIN_TOKEN = None

# Простейший in-memory rate-limit для входа/регистрации
_AUTH_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_AUTH_MAX = 10
_AUTH_WINDOW = 60.0


def _auth_limited(key: str) -> bool:
    now = time.time()
    _AUTH_ATTEMPTS[key] = [t for t in _AUTH_ATTEMPTS[key] if now - t < _AUTH_WINDOW]
    return len(_AUTH_ATTEMPTS[key]) >= _AUTH_MAX


def _auth_fail(key: str) -> None:
    _AUTH_ATTEMPTS[key].append(time.time())


app = FastAPI(title="Avito Parser API", lifespan=lifespan)

_cors_origins = set(_cors_extra())
_cors_origins.update({f"http://localhost:{_web_port()}", f"http://127.0.0.1:{_web_port()}"})
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


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


def current_actor(authorization: str | None = Header(default=None)) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if _admin_password() and token and token == _ADMIN_TOKEN:
        return {"id": None, "username": "admin", "is_admin": True}
    user = store.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return {"id": user["id"], "username": user["username"], "is_admin": False}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/register")
def register(req: AuthRequest, request: Request):
    key = f"reg:{request.client.host if request.client else 'unknown'}"
    if _auth_limited(key):
        raise HTTPException(status_code=429, detail="Слишком много попыток, попробуйте позже")
    if req.username.strip().lower() == "admin":
        _auth_fail(key)
        raise HTTPException(status_code=409, detail="Имя пользователя занято")
    user = store.register(req.username, req.password)
    if user is None:
        _auth_fail(key)
        raise HTTPException(status_code=409, detail="Имя пользователя уже занято")
    token = store.login(req.username, req.password)
    return {"token": token, "username": user["username"], "is_admin": False}


@app.post("/api/login")
def login(req: AuthRequest, request: Request):
    global _ADMIN_TOKEN
    key = f"login:{request.client.host if request.client else 'unknown'}"
    if _auth_limited(key):
        raise HTTPException(status_code=429, detail="Слишком много попыток, попробуйте позже")
    if (
        _admin_password()
        and req.username.strip().lower() == "admin"
        and req.password == _admin_password()
    ):
        _ADMIN_TOKEN = secrets.token_hex(32)
        return {"token": _ADMIN_TOKEN, "username": "admin", "is_admin": True}
    token = store.login(req.username, req.password)
    if token is None:
        _auth_fail(key)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    return {"token": token, "username": req.username, "is_admin": False}


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


@app.get("/api/links")
def list_links(actor: dict = Depends(current_actor)):
    if actor["is_admin"]:
        db_links = store.list_all_links()
        return _config_links() + db_links
    return store.list_links(actor["id"])


@app.post("/api/links", status_code=201)
def create_link(req: LinkRequest, actor: dict = Depends(current_actor)):
    if actor["is_admin"]:
        link = store.create_link_any(req.model_dump())
        if link is None:
            raise HTTPException(status_code=400, detail="Укажите логин владельца и ссылку")
        return link
    return store.create_link(actor["id"], req.model_dump())


@app.put("/api/links/{link_id}")
def update_link(link_id: int, req: LinkRequest, actor: dict = Depends(current_actor)):
    if actor["is_admin"]:
        link = store.update_link_any(link_id, req.model_dump())
    else:
        link = store.update_link(actor["id"], link_id, req.model_dump())
    if link is None:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    return link


@app.delete("/api/links/{link_id}")
def delete_link(link_id: int, actor: dict = Depends(current_actor)):
    if actor["is_admin"]:
        ok = store.delete_link_any(link_id)
    else:
        ok = store.delete_link(actor["id"], link_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    return {"ok": True}


@app.get("/api/ads")
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


# Раздача собранного фронтенда (production, python run.py без --dev)
_WEB_DIST = Path("web-server/dist")
if _WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=_WEB_DIST, html=True), name="web")
