"""REST API сервер: регистрация, авторизация, управление ссылками парсинга.

Единые ручки: /api/links и /api/links/{id}. Если запрос сделан с админ-токеном —
видны/редактируются все ссылки всех пользователей; с обычным токеном — только свои.
Логин админа: POST /api/login с username = "admin" и паролем из config.admin_password.

Запуск (в составе python run.py или отдельно):
    uvicorn server.main:app --host 0.0.0.0 --port 8000
"""

import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from load_config import load_avito_config
from db_service import SQLiteDBHandler
from server import store

store.init_db()

try:
    _ADMIN_PASSWORD = (load_avito_config("config.toml").admin_password or "").strip()
except Exception:
    _ADMIN_PASSWORD = ""

_ADMIN_TOKEN = None

app = FastAPI(title="Avito Parser API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    """Возвращает {id, username, is_admin}: админ (id=None) или пользователь."""
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
def register(req: AuthRequest):
    if req.username.strip().lower() == "admin":
        raise HTTPException(status_code=409, detail="Имя пользователя занято")
    user = store.register(req.username, req.password)
    if user is None:
        raise HTTPException(status_code=409, detail="Имя пользователя уже занято")
    token = store.login(req.username, req.password)
    return {"token": token, "username": user["username"], "is_admin": False}


@app.post("/api/login")
def login(req: AuthRequest):
    global _ADMIN_TOKEN
    if (
        _ADMIN_PASSWORD
        and req.username.strip().lower() == "admin"
        and req.password == _ADMIN_PASSWORD
    ):
        _ADMIN_TOKEN = secrets.token_hex(32)
        return {"token": _ADMIN_TOKEN, "username": "admin", "is_admin": True}
    token = store.login(req.username, req.password)
    if token is None:
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
