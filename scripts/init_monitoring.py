#!/usr/bin/env python3
"""Создаёт локальные настройки мониторинга со случайным паролем Grafana."""
import os
from pathlib import Path
import secrets


def main():
    root = Path(__file__).resolve().parent.parent
    destination = root / "monitoring" / ".env"
    template = destination.with_name(".env.example").read_text(encoding="utf-8")
    content = template.replace("GRAFANA_ADMIN_PASSWORD=\n",
                               f"GRAFANA_ADMIN_PASSWORD={secrets.token_urlsafe(32)}\n")
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("monitoring/.env уже существует; настройки и пароль сохранены.")
        return
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)
    (root / "logs").mkdir(exist_ok=True)
    print("Создан monitoring/.env. Логин и пароль Grafana находятся в этом файле.")


if __name__ == "__main__":
    main()
