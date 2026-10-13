"""Сборка FastAPI-приложения: конфигурация, CORS, lifespan, статика."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from load_config import load_avito_config
from persistence import store

_CONFIG_UNSET = object()
_config = _CONFIG_UNSET


def get_config():
    """Загружает config.toml один раз и кэширует (None, если не удалось)."""
    global _config
    if _config is _CONFIG_UNSET:
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


class ConfiguredCORSMiddleware(CORSMiddleware):
    """Читает конфиг при сборке ASGI middleware, а не при импорте приложения."""

    def __init__(self, app):
        origins = set(_cors_extra())
        port = _web_port()
        origins.update({f"http://localhost:{port}", f"http://127.0.0.1:{port}"})
        super().__init__(
            app,
            allow_origins=list(origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )


@asynccontextmanager
async def lifespan(app):
    store.init_db()
    if _admin_password() in ("", "admin"):
        logger.warning(
            "ВНИМАНИЕ: admin_password пуст или слабый ('admin'). Задайте сильный пароль в config.toml"
        )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Avito Parser API", lifespan=lifespan)

    app.add_middleware(ConfiguredCORSMiddleware)

    from server.routers import ads, auth, links
    app.include_router(auth.router)
    app.include_router(links.router)
    app.include_router(ads.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # Раздача собранного фронтенда (production, python run.py без --dev)
    web_dist = Path("web-server/dist")
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    return app
