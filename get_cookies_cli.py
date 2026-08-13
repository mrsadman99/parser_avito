"""
Получение cookies для парсера ЧЕРЕЗ IP мобильного прокси.

Запуск:
    python get_cookies_cli.py

Что делает:
    1. Читает proxy_string / proxy_change_url из config.toml
    2. Запускает Playwright (chromium) ПОД IP мобильного прокси
    3. Открывает случайную страницу Avito и собирает cookies
    4. Сохраняет их в storage/own_cookies.json

После запуска в config.toml нужно включить:
    use_own_cookies = true

Важно: cookies привязаны к IP прокси, поэтому парсер должен работать
через тот же самый proxy_string (иначе Avito увидит рассинхрон IP/cookies).
"""
import asyncio
import json
import random
from pathlib import Path

from loguru import logger

from dto import Proxy
from get_cookies import PlaywrightClient
from load_config import load_avito_config

logger.add("logs/app.log", rotation="5 MB", retention="5 days", level="DEBUG")

OUTPUT_PATH = "storage/own_cookies.json"


async def main():
    config = load_avito_config("config.toml")

    if not (config.proxy_string and config.proxy_change_url):
        logger.error(
            "В config.toml не настроен мобильный прокси "
            "(нужны и proxy_string, и proxy_change_url)"
        )
        return

    proxy = Proxy(
        proxy_string=config.proxy_string,
        change_ip_link=config.proxy_change_url,
    )
    logger.info(f"Запускаю Playwright через прокси: {config.proxy_string}")

    client = PlaywrightClient(proxy=proxy, headless=True)
    ads_id = str(random.randint(1111111111, 9999999999))
    cookies = await client.get_cookies(f"https://www.avito.ru/{ads_id}")

    if not cookies:
        logger.error("Не удалось получить cookies (возможно, IP прокси заблокирован)")
        return

    path = Path(OUTPUT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cookies": cookies,
        "user_agent": client.user_agent,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.success(f"Cookies сохранены в {OUTPUT_PATH}: {len(cookies)} шт")
    logger.success("Теперь в config.toml поставьте use_own_cookies = true и запускайте парсер")


if __name__ == "__main__":
    asyncio.run(main())
