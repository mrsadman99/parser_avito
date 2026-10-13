"""Точка входа uvicorn: `uvicorn server.main:app`.

REST API: регистрация, авторизация, управление ссылками, раздача фронтенда.
Сборка приложения — в server.app.create_app(), маршруты — в server.routers.*.
"""
from server.app import create_app

app = create_app()
