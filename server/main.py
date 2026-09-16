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
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field

from db_service import SQLiteDBHandler
from load_config import load_avito_config
from server import store

store.init_db()

try:
    _CONFIG = load_avito_config("config.toml")
except Exception:
    _CONFIG = None

_ADMIN_PASSWORD = (_CONFIG.admin_password or "").strip() if _CONFIG else ""
_WEB_PORT = _CONFIG.web_server_port if _CONFIG else 3000
_CORS_EXTRA = list(_CONFIG.cors_origins or []) if _CONFIG else []

if _ADMIN_PASSWORD in ("", "admin"):
    logger.warning(
        "ВНИМАНИЕ: admin_password пуст или слабый ('admin'). Задайте сильный пароль в config.toml"
    )

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


app = FastAPI(title="Avito Parser API")

_cors_origins = set(_CORS_EXTRA)
_cors_origins.update({f"http://localhost:{_WEB_PORT}", f"http://127.0.0.1:{_WEB_PORT}"})
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


def current_actor(authorization: str | None = Header(default=None)) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if _ADMIN_PASSWORD and token and token == _ADMIN_TOKEN:
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
        _ADMIN_PASSWORD
        and req.username.strip().lower() == "admin"
        and req.password == _ADMIN_PASSWORD
    ):
        _ADMIN_TOKEN = secrets.token_hex(32)
        return {"token": _ADMIN_TOKEN, "username": "admin", "is_admin": True}
    token = store.login(req.username, req.password)
    if token is None:
        _auth_fail(key)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    return {"token": token, "username": req.username, "is_admin": False}


@app.get("/api/links")
def list_links(actor: dict = Depends(current_actor)):
    if actor["is_admin"]:
        return store.list_all_links()
    return store.list_links(actor["id"])


@app.post("/api/links", status_code=201)
def create_link(req: LinkRequest, actor: dict = Depends(current_actor)):
    if actor["is_admin"]:
        raise HTTPException(
            status_code=403, detail="Админ не создаёт ссылки — добавляйте от имени пользователя"
        )
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
def list_ads(url: str, actor: dict = Depends(current_actor)):
    """Запарсенные объявления по исходной ссылке (из базы парсера)."""
    return SQLiteDBHandler().list_ads(url)


# Раздача собранного фронтенда (production, python run.py без --dev)
_WEB_DIST = Path("web-server/dist")
if _WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=_WEB_DIST, html=True), name="web")
