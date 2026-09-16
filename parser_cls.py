import html as html_lib
import json
import random
import re
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from loguru import logger
from pydantic import ValidationError

from common_data import HEADERS
from db_service import SQLiteDBHandler, _now_iso
from dto import Proxy, AvitoConfig
from filters.ads_filter import AdsFilter
from hide_private_data import log_config
from integrations.notifications.factory import build_notifier
from load_config import load_avito_config
from models import ItemsResponse, Item
from parser.cookies.factory import build_cookies_provider
from parser.export.factory import build_result_storage
from parser.http.client import HttpClient
from parser.http.camoufox_client import CamoufoxClient
from parser.proxies.proxy_factory import build_proxy
from parser.url_converter import AvitoUrlConverter
from utils.parse_phone import ParsePhone
from version import VERSION
from lang import SPFA_PROXY_REQUIRED

DEBUG_MODE = False

logger.add("logs/app.log", rotation="5 MB", retention="5 days", level="DEBUG")


class AvitoParse:
    def __init__(
            self,
            config: AvitoConfig,
            stop_event=None,
            links_provider=None
    ):
        self.config = config
        self.links_provider = links_provider
        self.proxy = build_proxy(self.config)
        self.cookies_provider = build_cookies_provider(config=config, proxy=self.proxy)
        self.db_handler = SQLiteDBHandler()
        self.notifier = build_notifier(config=config)
        self.result_storage = None
        self.url_converter = AvitoUrlConverter()
        self.stop_event = stop_event
        self.headers = HEADERS
        self.good_request_count = 0
        self.bad_request_count = 0
        self.http = HttpClient(
            proxy=self.proxy,
            cookies=self.cookies_provider,
            timeout=config.timeout,
            max_retries=self.config.max_count_of_retry,
            retry_delay=config.retry_delay,
            block_threshold=config.block_threshold
        )
        self.camoufox = None
        if config.camoufox.use:
            self.camoufox = CamoufoxClient(
                proxy=self.proxy,
                os=config.camoufox.os,
                headless=config.camoufox.headless,
                humanize=config.camoufox.humanize,
                geoip=config.camoufox.geoip,
                timeout=config.timeout,
                max_retries=config.max_count_of_retry,
                retry_delay=config.retry_delay,
                block_threshold=config.block_threshold,
            )
            logger.info("Camoufox включён для запросов к поиску")
        self.ads_filter = AdsFilter(config=config, is_viewed_fn=self.is_viewed)
        log_config(config=self.config, version=VERSION)

    @property
    def run_failed(self) -> bool:
        """Проход считается неудачным, если все запросы завершились ошибкой/блокировкой."""
        return self.bad_request_count > 0 and self.good_request_count == 0

    def _current_links(self):
        """Актуальный набор ссылок: из внешнего провайдера (веб), иначе из конфига."""
        if self.links_provider is not None:
            try:
                links = self.links_provider()
                if links:
                    return links
            except Exception as err:
                logger.warning(f"Не удалось получить ссылки из провайдера: {err}")
        return self.config.links

    def get_proxy_obj(self) -> Proxy | None:
        if all([self.config.mobile_proxy.proxy_string, self.config.mobile_proxy.change_url]):
            return Proxy(
                proxy_string=self.config.mobile_proxy.proxy_string,
                change_ip_link=self.config.mobile_proxy.change_url
            )
        logger.info("Работаем без прокси")
        return None

    def fetch_data(self, url: str) -> str | None:
        if self.stop_event and self.stop_event.is_set():
            return None

        try:
            if self.camoufox:
                response = self.camoufox.request("GET", url)
            else:
                response = self.http.request("GET", url)
            self.good_request_count += 1
            return response.text

        except Exception as err:
            self.bad_request_count += 1
            logger.warning(f"Ошибка при запросе {url}: {err}")
            return None

    @staticmethod
    def _api_url_for_page(api_url: str, page: int) -> str:
        parts = urlsplit(api_url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        page_key = next(
            (key for key, _ in query if key in {"p", "page"}),
            "p",
        )
        query = [(key, value) for key, value in query if key not in {"p", "page"}]
        query.append(("page", str(page)))
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    def fetch_api_data(self, api_url: str, page: int) -> dict | None:
        if self.stop_event and self.stop_event.is_set():
            return None

        page_url = self._api_url_for_page(api_url, page)
        try:
            if self.camoufox:
                response = self.camoufox.request("GET", page_url)
            else:
                response = self.http.request("GET", page_url)
            self.good_request_count += 1
            return response.json()
        except Exception as err:
            self.bad_request_count += 1
            logger.warning(f"Ошибка при запросе API {page_url}: {err}")
            return None

    @staticmethod
    def _extract_api_catalog(payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {}

        result = payload.get("result")
        candidates = [
            payload.get("catalog"),
            result.get("catalog") if isinstance(result, dict) else None,
            result,
            payload,
        ]
        return next(
            (
                candidate
                for candidate in candidates
                if isinstance(candidate, dict)
                and isinstance(candidate.get("items"), list)
            ),
            {},
        )
    @staticmethod
    def _query_label(url: str) -> str:
        """Извлекает поисковую строку (q=) из ссылки Avito для логов."""
        try:
            query = dict(parse_qsl(urlsplit(url).query))
            q = query.get("q")
            if q:
                return q
        except Exception:
            pass
        return url

    def parse(self):
        links = self._current_links()

        if not self.config.one_file_for_link:
            self.result_storage = build_result_storage(config=self.config)

        current_ip = self.http.get_current_ip()
        if current_ip:
            if self.config.mobile_proxy.proxy_string:
                logger.info(f"🌐 IP (через прокси): {current_ip}")
            else:
                logger.info(f"🌐 Текущий IP: {current_ip}")
        else:
            logger.warning("Не удалось определить текущий IP")


        api_urls = {}
        for source_url in links:
            if self.stop_event and self.stop_event.is_set():
                return
            try:
                api_urls[source_url] = self.url_converter.convert(source_url)
            except Exception as err:
                logger.error(
                    f"Не удалось преобразовать ссылку Avito в API URL "
                    f"{source_url}: {err}"
                )

        for link_index, (source_url, link_cfg) in enumerate(links.items()):
            api_url = api_urls.get(source_url)
            if not api_url:
                logger.warning(f"⚠️ Не удалось получить API-адрес для ссылки: {source_url}")
                continue

            if self.config.one_file_for_link:
                self.result_storage = build_result_storage(
                    config=self.config,
                    link_index=link_index,
                )

            query_label = self._query_label(source_url)
            if link_cfg.min_price is not None or link_cfg.max_price is not None:
                lo = link_cfg.min_price if link_cfg.min_price is not None else 0
                hi = link_cfg.max_price if link_cfg.max_price is not None else "∞"
                logger.info(f"Ценовой диапазон ссылки: {lo} – {hi}")
            blocks_before = self.http.block_count
            errors_before = self.http.error_count
            link_got_data = False
            ads_in_link = []

            logger.info(f"🔍 Сканирую ссылку: {query_label}")

            for page in range(1, self.config.count + 1):
                logger.info(f"page={page}")
                if self.stop_event and self.stop_event.is_set():
                    return

                json_data = self.fetch_api_data(api_url=api_url, page=page)
                if not json_data:
                    logger.warning(
                        f"Не удалось получить данные API для {query_label}, "
                        f"повтор через {self.config.pause_between_links} сек."
                    )
                    time.sleep(self.config.pause_between_links)
                    continue

                link_got_data = True
                catalog = self._extract_api_catalog(json_data)
                try:
                    ads_models = ItemsResponse(**catalog)
                except ValidationError as err:
                    logger.error(
                        f"При валидации объявлений произошла ошибка: {err}"
                    )
                    continue

                ads = self._clean_null_ads(ads=ads_models.items)
                logger.info(f"Объявлений перед фильтрацией {len(ads)}")
                ads = self._add_seller_to_ads(ads=ads)
                ads = self._add_promotion_to_ads(ads=ads)
                ads = self._add_seller_rating(ads=ads)

                if not ads:
                    logger.info(
                        "Объявления закончились, завершаю работу с данной ссылкой"
                    )
                    break

                filtered_ads = self.filter_ads(
                    ads=ads,
                    min_price=link_cfg.min_price,
                    max_price=link_cfg.max_price,
                    white_list=link_cfg.white_list,
                    black_list=link_cfg.black_list,
                )

                filtered_ads = self.parse_full_description(ads=filtered_ads)

                try:
                    self.notifier.notify_many(ads=filtered_ads)
                except Exception as err:
                    logger.warning(f"Ошибка при отправке уведомлений: {err}")

                filtered_ads = self.parse_views(ads=filtered_ads)
                filtered_ads = self.parse_phone(ads=filtered_ads)

                if filtered_ads:
                    self.__save_viewed(ads=filtered_ads, source_url=source_url)
                    ads_in_link.extend(filtered_ads)

                logger.info(f"Пауза {self.config.pause_between_links} сек.")
                time.sleep(self.config.pause_between_links)

            # --- Итог сканирования ссылки ---
            blocks = self.http.block_count - blocks_before
            errors = self.http.error_count - errors_before
            if link_got_data:
                status = "✅ успешно"
            elif blocks > 0:
                status = "🚫 заблокирован"
            else:
                status = "❌ не удалось"
            logger.info(
                f"📊 Сканирование: {query_label} | "
                f"объявлений: {len(ads_in_link)} | "
                f"статус: {status} | "
                f"блокировок: {blocks} | ошибок: {errors}"
            )

            if ads_in_link:
                logger.info(f"Сохраняю {len(ads_in_link)} объявлений")
                self.result_storage.save(ads_in_link)
            else:
                logger.info("Сохранять нечего")

        logger.info(
            f"Хорошие запросы: {self.good_request_count}шт, "
            f"плохие: {self.bad_request_count}шт"
        )

        if self.config.one_time_start:
            self.notifier.notify(
                message="Парсинг Авито завершён. Все ссылки обработаны"
            )
            self.stop_event = True

    def close(self):
        """Освобождает ресурсы (Camoufox-браузер)."""
        if self.camoufox is not None:
            try:
                self.camoufox.close()
            except Exception as err:
                logger.warning(f"Ошибка при закрытии Camoufox: {err}")
            self.camoufox = None

    @staticmethod
    def _clean_null_ads(ads: list[Item]) -> list[Item]:
        return [ad for ad in ads if ad.id]

    @staticmethod
    def find_json_on_page(html_code, data_type: str = "mime") -> dict:
        import html as html_lib
        html_code = BeautifulSoup(html_code, "html.parser")
        try:
            for _script in html_code.select('script'):

                script_type = _script.get('type')

                if data_type == 'mime':
                    for script in html_code.select('script'):
                        if script.get('type') == 'mime/invalid' and script.get('data-mfe-state') == 'true' and 'sandbox' not in script.text:
                            data = json.loads(html_lib.unescape(script.text))
                            if data.get('i18n', {}).get('hasMessages'):
                                return data.get('loaderData', {}).get("data", {})

        except Exception as err:
            logger.error(f"Ошибка при поиске информации на странице: {err}")
        logger.warning("not found json")
        return {}


    def filter_ads(self, ads: list[Item], min_price=None, max_price=None,
                   white_list=None, black_list=None) -> list[Item]:
        return self.ads_filter.apply(
            ads,
            min_price=min_price,
            max_price=max_price,
            white_list=white_list,
            black_list=black_list,
        )

    def _add_seller_to_ads(self, ads: list[Item]) -> list[Item]:
        for ad in ads:
            if seller_id := self._extract_seller_slug(data=ad):
                ad.sellerId = seller_id
        return ads

    @staticmethod
    def _add_promotion_to_ads(ads: list[Item]) -> list[Item]:
        for ad in ads:
            ad.isPromotion = any(
                v.get("title") == "Продвинуто"
                for step in (ad.iva or {}).get("DateInfoStep", [])
                for v in step.payload.get("vas", [])
            )
        return ads

    @staticmethod
    def _add_seller_rating(ads: list[Item]) -> list[Item]:
        """Достаёт рейтинг продавца и количество оценок из каталога (rating.score/summary)."""
        for ad in ads:
            rating = getattr(ad, "rating", None)
            if rating is None:
                continue
            if rating.score is not None:
                ad.seller_rating = float(rating.score)
            if rating.summary:
                digits = "".join(ch for ch in str(rating.summary) if ch.isdigit())
                if digits:
                    ad.seller_reviews = int(digits)
        return ads

    def parse_views(self, ads: list[Item]) -> list[Item]:
        if not self.config.parse_views:
            return ads

        logger.info("Начинаю парсинг просмотров")

        for ad in ads:
            try:
                html_code_full_page = self.fetch_data(url=f"https://www.avito.ru{ad.urlPath}")
                if not html_code_full_page:
                    continue
                ad.total_views, ad.today_views = self._extract_views(html=html_code_full_page)
                delay = random.uniform(0.1, 0.9)
                time.sleep(delay)
            except Exception as err:
                logger.warning(f"Ошибка при парсинге {ad.urlPath}: {err}")
                continue

        return ads

    def parse_full_description(self, ads: list[Item]) -> list[Item]:
        """Открывает страницу каждого объявления и подтягивает ПОЛНОЕ описание.

        В выдаче API каталога описание обрезано (~250 символов), поэтому для
        полного текста делаем отдельный запрос на страницу объявления.
        """
        if not self.config.parse_full_description:
            return ads

        logger.info("Начинаю парсинг полных описаний")
        for ad in ads:
            try:
                if self.stop_event and self.stop_event.is_set():
                    break
                html_code_full_page = self.fetch_data(url=f"https://www.avito.ru{ad.urlPath}")
                if not html_code_full_page:
                    continue
                full_description = self._extract_description(html=html_code_full_page)
                if full_description:
                    ad.description = full_description
                delay = random.uniform(0.1, 0.9)
                time.sleep(delay)
            except Exception as err:
                logger.warning(f"Ошибка при парсинге описания {ad.urlPath}: {err}")
                continue
        return ads

    @staticmethod
    def _extract_description(html: str) -> str | None:
        """Достаёт полное описание со страницы объявления (несколько стратегий)."""
        soup = BeautifulSoup(html, "html.parser")

        # 1) HTML-маркер блока описания
        marker = soup.select_one('[data-marker="item-view/item-description"]')
        if marker:
            text = marker.get_text("\n", strip=True)
            if text and len(text) > 50:
                return text

        # 2) JSON-LD (schema.org) — поле description
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
            except (ValueError, TypeError):
                continue
            found = AvitoParse._find_json_value(data, "description", min_len=50)
            if found:
                return found

        # 3) mfe-state JSON внутри страницы — рекурсивный поиск description
        for script in soup.select('script[data-mfe-state="true"]'):
            try:
                data = json.loads(html_lib.unescape(script.text))
            except (ValueError, TypeError):
                continue
            found = AvitoParse._find_json_value(data, "description", min_len=50)
            if found:
                return found

        return None

    @staticmethod
    def _find_json_value(data, key: str, min_len: int = 0):
        """Рекурсивно ищет первое строковое значение по ключу в JSON-дереве."""
        if isinstance(data, dict):
            for k, v in data.items():
                if k == key and isinstance(v, str) and len(v) >= min_len:
                    return v
                found = AvitoParse._find_json_value(v, key, min_len)
                if found:
                    return found
        elif isinstance(data, list):
            for item in data:
                found = AvitoParse._find_json_value(item, key, min_len)
                if found:
                    return found
        return None

    def parse_phone(self, ads: list[Item]) -> list[Item]:
        if not self.config.parse_phone or self.config.parse_phone:
            # future feat, not ready yet
            return ads

        try:
            return ParsePhone(ads=ads, config=self.config).parse_phones()
        except Exception as err:
            logger.warning(f"Ошибка при парсинге телефонов: {err}")
            return ads

    @staticmethod
    def _extract_views(html: str) -> tuple:
        soup = BeautifulSoup(html, "html.parser")

        def extract_digits(element):
            return int(''.join(filter(str.isdigit, element.get_text()))) if element else None

        total = extract_digits(soup.select_one('[data-marker="item-view/total-views"]'))
        today = extract_digits(soup.select_one('[data-marker="item-view/today-views"]'))

        return total, today

    @staticmethod
    def _extract_seller_slug(data):
        match = re.search(r"/brands/([^/?#]+)", str(data))
        if match:
            return match.group(1)
        return None

    def is_viewed(self, ad: Item) -> bool:
        """Проверяет, смотрели мы это или нет"""
        return self.db_handler.record_exists(record_id=ad.id, price=ad.priceDetailed.value)

    @staticmethod
    def _is_recent(timestamp_ms: int, max_age_seconds: int) -> bool:
        now = datetime.utcnow()
        published_time = datetime.utcfromtimestamp(timestamp_ms / 1000)
        return (now - published_time) <= timedelta(seconds=max_age_seconds)

    def __save_viewed(self, ads: list[Item], source_url: str = None) -> None:
        """Сохраняет просмотренные объявления и ставит дату сканирования (UTC)."""
        try:
            now = _now_iso()
            for ad in ads:
                ad.scanned_at = now
            self.db_handler.add_record_from_page(ads=ads, source_url=source_url)
        except Exception as err:
            logger.info(f"При сохранении в БД ошибка {err}")


if __name__ == "__main__":
    try:
        config = load_avito_config("config.toml")
    except Exception as err:
        logger.error(f"Ошибка загрузки конфига: {err}")
        exit(1)

    if config.use_bypass_api and not (config.proxy_string or "").strip():
        logger.critical(f"SPFA не будет работать без прокси. {SPFA_PROXY_REQUIRED}")
        exit(1)

    if config.use_bypass_api and not config.proxy_change_url:
        logger.warning(
            "SPFA запущен с серверным (статическим) прокси. Если будет много ошибок - установить большие "
            "pause_between_links и pause_general, чтобы снизить риск блокировок."
        )

    while True:
        try:
            parser = AvitoParse(config)
            parser.parse()
            if config.one_time_start:
                logger.info("Парсинг завершен т.к. включён one_time_start в настройках")
                break
            if config.retry_on_failure and parser.run_failed:
                logger.info(
                    f"Парсинг не удался ({parser.bad_request_count} ошибок, "
                    f"{parser.good_request_count} успешных). Повтор через "
                    f"{config.retry_on_failure_delay} сек (без pause_general)"
                )
                time.sleep(config.retry_on_failure_delay)
                continue
            logger.info(f"Парсинг завершен. Пауза {config.pause_general} сек")
            time.sleep(config.pause_general)
        except Exception as err:
            logger.exception(err)
            logger.error(f"Произошла ошибка {err}. Будет повторный запуск через 30 сек.")
            time.sleep(30)
