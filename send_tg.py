#!/usr/bin/env python3
"""Отправка произвольного текста и/или фото в Telegram-бот.

Использует те же настройки, что и парсер (из config.toml):
  tg_token, tg_chat_id, proxy_notifier (прокси для Telegram).

Фото можно указать локальным путём или URL.
Текст по умолчанию отправляется как есть; с флагом --markdown применяется
MarkdownV2 с экранированием (как в парсере).

Примеры:
    python send_tg.py "Привет!"
    python send_tg.py --text "Смотри какое фото" --photo /path/to/photo.jpg
    python send_tg.py --text "Смотри" --photo https://example.com/photo.jpg --markdown
    python send_tg.py --text "Только в один чат" --chat-id 123456789
"""

import argparse
import sys

import requests

from integrations.notifications.transport import send_with_retries
from integrations.notifications.utils import escape_markdown_v2
from load_config import load_avito_config
from proxy_helpers import build_proxies_dict


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _body(chat_id: str, text: str, markdown: bool, **extra) -> dict:
    body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True, **extra}
    if markdown:
        body["parse_mode"] = "MarkdownV2"
    return body


def _send_text(token, chat_id, text, proxies, markdown):
    def _send():
        return requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=_body(chat_id, text, markdown),
            proxies=proxies,
            timeout=30,
        )

    return send_with_retries(_send)


def _send_photo_url(token, chat_id, caption, photo_url, proxies, markdown):
    def _send():
        return requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            json={
                "chat_id": chat_id,
                "caption": caption,
                "photo": photo_url,
                "disable_web_page_preview": True,
                **({"parse_mode": "MarkdownV2"} if markdown else {}),
            },
            proxies=proxies,
            timeout=30,
        )

    return send_with_retries(_send)


def _send_photo_bytes(token, chat_id, caption, image_bytes, filename, proxies, markdown):
    data = {"chat_id": chat_id, "caption": caption}
    if markdown:
        data["parse_mode"] = "MarkdownV2"

    def _send():
        return requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data=data,
            files={"photo": (filename, image_bytes, "image/jpeg")},
            proxies=proxies,
            timeout=30,
        )

    return send_with_retries(_send)


def send_to_chat(token, chat_id, text, photo, proxies, markdown):
    """Отправляет сообщение (текст и/или фото) в один чат."""
    caption = text or ""

    if not photo:
        _send_text(token, chat_id, text, proxies, markdown)
        return

    if _is_url(photo):
        try:
            _send_photo_url(token, chat_id, caption, photo, proxies, markdown)
        except requests.HTTPError as err:
            resp = getattr(err, "response", None)
            if resp is not None and resp.status_code == 400:
                print("  (URL фото отклонён Telegram, пробую скачать и отправить байтами)")
                img = requests.get(photo, proxies=proxies, timeout=15)
                img.raise_for_status()
                _send_photo_bytes(
                    token, chat_id, caption, img.content, "photo.jpg", proxies, markdown
                )
            else:
                raise
    else:
        with open(photo, "rb") as f:
            _send_photo_bytes(token, chat_id, caption, f.read(), photo, proxies, markdown)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Отправка текста и/или фото в Telegram-бот (настройки из config.toml)"
    )
    parser.add_argument("text", nargs="?", default=None, help="Текст сообщения")
    parser.add_argument("--text", dest="text_opt", default=None, help="Текст сообщения")
    parser.add_argument("--photo", default=None, help="Фото: локальный путь или URL")
    parser.add_argument("--chat-id", dest="chat_ids", action="append", default=None,
                        help="chat_id получателя (можно несколько раз; по умолчанию из config.toml)")
    parser.add_argument("--markdown", action="store_true",
                        help="Применить MarkdownV2 с экранированием (как в парсере)")
    args = parser.parse_args(argv)

    text = args.text_opt or args.text
    if not text and not args.photo:
        parser.error("укажите текст (позиционно или --text) и/или --photo")

    try:
        config = load_avito_config("config.toml")
    except Exception as err:
        print(f"❌ Не удалось загрузить config.toml: {err}")
        return 1

    if not config.messengers.tg_token:
        print("❌ В config.toml не заполнен tg_token")
        return 1

    chat_ids = args.chat_ids or config.messengers.tg_chat_id
    if not chat_ids:
        print("❌ Не указан chat_id (ни в config.toml, ни через --chat-id)")
        return 1

    proxies = build_proxies_dict(config.messengers.proxy_notifier)
    if proxies:
        print(f"📡 Использую прокси для TG: {config.messengers.proxy_notifier}")

    if args.markdown and text:
        text = escape_markdown_v2(text)

    ok = True
    for chat_id in chat_ids:
        try:
            send_to_chat(
                token=config.messengers.tg_token,
                chat_id=chat_id,
                text=text,
                photo=args.photo,
                proxies=proxies,
                markdown=args.markdown,
            )
            print(f"✅ Отправлено в chat_id={chat_id}")
        except Exception as err:
            print(f"❌ Ошибка для chat_id={chat_id}: {err}")
            ok = False

    print("🎉 Готово" if ok else "⚠️ Были ошибки — проверьте токен/чат/прокси")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
