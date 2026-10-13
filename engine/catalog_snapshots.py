"""Полные ответы выдачи на диске; в Loki отправляется только указатель и счётчики."""
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from loguru import logger


def extract_catalog(payload):
    if not isinstance(payload, dict):
        return {}
    result = payload.get("result")
    candidates = [
        payload.get("catalog"),
        result.get("catalog") if isinstance(result, dict) else None,
        result,
        payload,
    ]
    return next((value for value in candidates
                 if isinstance(value, dict) and isinstance(value.get("items"), list)), {})


def save_catalog_response(payload, *, url, page, status_code,
                          directory="logs/catalog_responses"):
    """Сохраняет каждый успешный JSON до валидации/фильтрации, включая пустой.

    Ошибка диска не превращает полученную страницу в неуспешный HTTP-запрос.
    Временный файл не доступен через шлюз Grafana; публикация — атомарный rename.
    Cookies и заголовки запроса сюда не передаются.
    """
    if not isinstance(status_code, int) or not 200 <= status_code < 300:
        return None
    temporary = None
    log = logger.bind(log_category="scanning")
    try:
        now = datetime.now(timezone.utc)
        relative = f"{now:%Y-%m-%d}/{now:%H%M%S%f}_{uuid4().hex}.json"
        destination = Path(directory) / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        # Docker nginx runs under a different uid; the containing directory is
        # exposed only inside the monitoring network, behind Grafana's login.
        temporary.chmod(0o644)
        temporary.replace(destination)

        items = extract_catalog(payload).get("items")
        count = len(items) if items is not None else None
        ads = sum(isinstance(item, dict) and bool(item.get("id")) for item in items) if items is not None else None
        root = payload if isinstance(payload, dict) else {}
        query = parse_qs(urlsplit(url).query)
        counters = {key: root.get(key) if isinstance(root.get(key), (int, float)) else None
                    for key in ("count", "totalCount", "mainCount")}
        log.bind(
            catalog_snapshot=relative, catalog_url=url, catalog_page=page,
            catalog_query=query.get("query", query.get("q", [""]))[0],
            catalog_status=status_code, catalog_items=count, catalog_ads=ads,
            catalog_count=counters["count"], catalog_total_count=counters["totalCount"],
            catalog_main_count=counters["mainCount"],
        ).info(
            "JSON выдачи сохранён: query={} | page={} | HTTP={} | items={} | ads={} | "
            "count={} | totalCount={} | mainCount={} | catalog_snapshot={} | URL={}",
            query.get("query", query.get("q", [""]))[0], page, status_code, count, ads,
            counters["count"], counters["totalCount"], counters["mainCount"], relative, url,
        )
        return destination
    except Exception as error:
        log.warning("Не удалось сохранить JSON выдачи: page={} | URL={} | {}", page, url, error)
        return None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
