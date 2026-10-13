"""Регистрация, авторизация и in-memory rate-limit."""
import secrets
import time
from collections import defaultdict

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from persistence import store
from server.app import _admin_password

router = APIRouter()

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


class AuthRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def current_actor(authorization: str | None = Header(default=None)) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if _admin_password() and token and token == _ADMIN_TOKEN:
        return {"id": None, "username": "admin", "is_admin": True}
    user = store.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return {"id": user["id"], "username": user["username"], "is_admin": False}


@router.post("/api/register")
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


@router.post("/api/login")
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
