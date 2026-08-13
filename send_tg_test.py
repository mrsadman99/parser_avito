"""
Отправка тестового сообщения в Telegram боту.

Берёт tg_token и tg_chat_id из config.toml (а также proxy_notifier, если задан).
Запуск:
    python send_tg_test.py "Текст сообщения"     # свой текст
    python send_tg_test.py                        # по умолчанию «Тест от Avito Parser»
"""
import sys

import requests

from load_config import load_avito_config


def get_proxy(proxy: str):
    if proxy:
        return {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    return None


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "Тест от Avito Parser ✅"

    try:
        config = load_avito_config("config.toml")
    except Exception as err:
        print(f"❌ Не удалось загрузить config.toml: {err}")
        return

    if not config.tg_token:
        print("❌ В config.toml не заполнен tg_token")
        return
    if not config.tg_chat_id:
        print("❌ В config.toml не заполнен tg_chat_id")
        return

    proxies = get_proxy(config.proxy_notifier)
    if proxies:
        print(f"📡 Использую прокси для TG: {config.proxy_notifier}")

    url = f"https://api.telegram.org/bot{config.tg_token}/sendMessage"
    ok = True

    for chat_id in config.tg_chat_id:
        try:
            resp = requests.post(
                url,
                json={"chat_id": chat_id, "text": text},
                proxies=proxies,
                timeout=30,
            )
            data = resp.json()
            if data.get("ok"):
                print(f"✅ Отправлено в chat_id={chat_id}")
            else:
                print(f"❌ Ошибка для chat_id={chat_id}: {data.get('description')}")
                ok = False
        except Exception as err:
            print(f"❌ Ошибка сети/таймаут для chat_id={chat_id}: {err}")
            ok = False

    print("🎉 Готово" if ok else "⚠️ Были ошибки — проверьте токен/чат/прокси")


if __name__ == "__main__":
    main()
