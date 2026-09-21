#!/usr/bin/env python3
"""Обновление старых объявлений из их detail-страниц (миграция на актуальную версию).

Для каждого уже распарсенного объявления (ad_url из таблицы viewed):
  * запрашивает detail-страницу тем же стеком, что и парсер — тот же прокси,
    cookies и общий throttle/очередь с задержкой min_delay..max_delay
    (через AvitoParse.fetch_data);
  * обновляет поля в таблице viewed: price, title, description, ad_url,
    photo_url, has_delivery, city, seller_rating, seller_reviews и дату
    парсинга (scanned_at);
  * если объявление удалено/не найдено — удаляет запись из БД.

Запуск:
    python scripts/refresh_ads.py                 # обновить все
    python scripts/refresh_ads.py --dry-run       # только показать, ничего не менять
    python scripts/refresh_ads.py --limit 50      # обработать первые N
    python scripts/refresh_ads.py --only-missing  # только там, где нет city/has_delivery
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db_service import SQLiteDBHandler
from load_config import load_avito_config
from parser.detail import parse_ad_html
from parser_cls import AvitoParse


def _report_proxy(config) -> None:
    """Сообщает, какой прокси будет использован (свой поднимает AvitoParse)."""
    if getattr(getattr(config, "own_mobile_proxy", None), "use", False):
        return
    proxy_string = (config.external_mobile_proxy.proxy_string or "").strip()
    if proxy_string:
        print("Свой мобильный прокси выключен — использую внешний мобильный/серверный прокси из config.toml")
    else:
        print("Прокси не задан — запросы пойдут напрямую")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _build_fields(parsed: dict, fallback_url: str) -> dict:
    """Поля для записи в БД (None не перезаписываем; scanned_at — всегда)."""
    fields = {
        "title": parsed.get("title"),
        "description": parsed.get("description"),
        "price": parsed.get("price"),
        "ad_url": parsed.get("ad_url") or fallback_url,
        "photo_url": parsed.get("photo_url"),
        "city": parsed.get("city"),
        "seller_rating": parsed.get("seller_rating"),
        "seller_reviews": parsed.get("seller_reviews"),
        "scanned_at": _now_iso(),
    }
    has_delivery = parsed.get("has_delivery")
    if has_delivery is not None:
        fields["has_delivery"] = 1 if has_delivery else 0
    return {key: value for key, value in fields.items() if value is not None}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Обновление старых объявлений из detail-страниц"
    )
    parser.add_argument("--config", default="config.toml", help="Путь к config.toml")
    parser.add_argument("--dry-run", action="store_true",
                        help="Ничего не менять, только показать")
    parser.add_argument("--limit", type=int, default=0,
                        help="Обработать не более N объявлений (0 — без ограничения)")
    parser.add_argument("--only-missing", action="store_true",
                        help="Только объявления без city/has_delivery")
    args = parser.parse_args(argv)

    config = load_avito_config(args.config)
    db = SQLiteDBHandler()
    ads = db.list_ads_for_refresh(only_missing=args.only_missing)
    if args.limit > 0:
        ads = ads[:args.limit]

    total = len(ads)
    print(f"К обновлению: {total} объявлений"
          + (" (dry-run)" if args.dry_run else ""))

    _report_proxy(config)
    avito = AvitoParse(config)  # тот же прокси/cookies/throttle, что и при парсинге

    updated = removed = skipped = 0
    for index, ad in enumerate(ads, 1):
        ad_id = ad.get("id")
        url = ad.get("ad_url")
        if not url:
            skipped += 1
            print(f"[{index}/{total}] id={ad_id}: нет ad_url — пропуск")
            continue

        # Запрос через общий throttle (задержка min_delay..max_delay, как при парсинге)
        html = avito.fetch_data(url)
        if not html:
            skipped += 1
            print(f"[{index}/{total}] id={ad_id}: запрос не удался — пропуск")
            continue

        parsed = parse_ad_html(html)

        if parsed.get("removed"):
            removed += 1
            print(f"[{index}/{total}] id={ad_id}: объявление удалено"
                  + (" (dry-run)" if args.dry_run else " → удаляю"))
            if not args.dry_run:
                db.delete_ad(ad_id)
            continue

        if not parsed.get("available"):
            skipped += 1
            print(f"[{index}/{total}] id={ad_id}: страница не распознана — пропуск")
            continue

        fields = _build_fields(parsed, fallback_url=url)
        updated += 1
        print(
            f"[{index}/{total}] id={ad_id}: обновляю"
            f" title={parsed.get('title')!r}"
            f" price={parsed.get('price')}"
            f" city={parsed.get('city')!r}"
            f" delivery={parsed.get('has_delivery')}"
            + (" (dry-run)" if args.dry_run else "")
        )
        if not args.dry_run:
            db.update_ad(ad_id, fields)

    print()
    print(f"Итог: обновлено {updated}, удалено {removed}, пропущено {skipped}"
          + (" (dry-run — изменения не сохранены)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
