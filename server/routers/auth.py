"""Регистрация, авторизация и in-memory rate-limit."""
import secrets
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from persistence import store
from server.app import _admin_password

router = APIRouter()


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
    actor = store.session_actor(token, _admin_password())
    if actor is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return actor


@router.get("/api/me")
def me(actor: dict = Depends(current_actor)):
    return actor


@router.post("/api/logout")
def logout(authorization: str | None = Header(default=None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    store.revoke_session(token)
    return {"ok": True}


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
    key = f"login:{request.client.host if request.client else 'unknown'}"
    if _auth_limited(key):
        raise HTTPException(status_code=429, detail="Слишком много попыток, попробуйте позже")
    if (
        _admin_password()
        and req.username.strip().lower() == "admin"
        and secrets.compare_digest(req.password.encode(), _admin_password().encode())
    ):
        token = store.create_admin_session(_admin_password())
        return {"token": token, "username": "admin", "is_admin": True}
    token = store.login(req.username, req.password)
    if token is None:
        _auth_fail(key)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    return {"token": token, "username": req.username, "is_admin": False}
