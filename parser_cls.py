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
from db_service import SQLiteDBHandler
from dto import Proxy, AvitoConfig
from filters.ads_filter import AdsFilter
from hide_private_data import log_config
from integrations.notifications.factory import build_notifier
from load_config import load_avito_config
from models import ItemsResponse, Item
from parser.ai.deepseek import DeepSeekEvaluator
from parser.cookies.factory import build_cookies_provider
from parser.export.factory import build_result_storage
from parser.http.client import HttpClient
from parser.proxies.proxy_factory import build_proxy
from parser.url_converter import AvitoUrlConverter
from utils.parse_phone import ParsePhone
from version import VERSION

DEBUG_MODE = False

logger.add("logs/app.log", rotation="5 MB", retention="5 days", level="DEBUG")


class AvitoParse:
    def __init__(
            self,
            config: AvitoConfig,
            stop_event=None
    ):
        self.config = config
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
        self.ads_filter = AdsFilter(config=config, is_viewed_fn=self.is_viewed)
        self.deepseek = None
        if config.use_deepseek and config.deepseek_api_key:
            self.deepseek = DeepSeekEvaluator(
                api_key=config.deepseek_api_key,
                model=config.deepseek_model,
                history_size=config.deepseek_history_size,
            )
            logger.info("DeepSeek-оценка включена")
        log_config(config=self.config, version=VERSION)

    @property
    def run_failed(self) -> bool:
        """Проход считается неудачным, если все запросы завершились ошибкой/блокировкой."""
        return self.bad_request_count > 0 and self.good_request_count == 0

    def get_proxy_obj(self) -> Proxy | None:
        if all([self.config.proxy_string, self.config.proxy_change_url]):
            return Proxy(
                proxy_string=self.config.proxy_string,
                change_ip_link=self.config.proxy_change_url
            )
        logger.info("Работаем без прокси")
        return None

    def fetch_data(self, url: str) -> str | None:
        if self.stop_event and self.stop_event.is_set():
            return None

        try:
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
    def parse(self):
        if not self.config.one_file_for_link:
            self.result_storage = build_result_storage(config=self.config)

        current_ip = self.http.get_current_ip()
        if current_ip:
            if self.config.proxy_string:
                logger.info(f"🌐 IP (через прокси): {current_ip}")
            else:
                logger.info(f"🌐 Текущий IP: {current_ip}")
        else:
            logger.warning("Не удалось определить текущий IP")


        api_urls = {}
        for source_url in self.config.urls:
            if self.stop_event and self.stop_event.is_set():
                return
            try:
                api_urls[source_url] = self.url_converter.convert(source_url)
            except Exception as err:
                logger.error(
                    f"Не удалось преобразовать ссылку Avito в API URL "
                    f"{source_url}: {err}"
                )

        for link_index, source_url in enumerate(self.config.urls):
            api_url = api_urls.get(source_url)
            if not api_url:
                continue

            if self.config.one_file_for_link:
                self.result_storage = build_result_storage(
                    config=self.config,
                    link_index=link_index,
                )

            ads_in_link = []
            for page in range(1, self.config.count + 1):
                logger.info(f"page={page}")
                if self.stop_event and self.stop_event.is_set():
                    return

                json_data = self.fetch_api_data(api_url=api_url, page=page)
                if not json_data:
                    logger.warning(
                        f"Не удалось получить данные API для {source_url}, "
                        f"повтор через {self.config.pause_between_links} сек."
                    )
                    time.sleep(self.config.pause_between_links)
                    continue

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

                if not ads:
                    logger.info(
                        "Объявления закончились, завершаю работу с данной ссылкой"
                    )
                    break

                filtered_ads = self.filter_ads(ads=ads)

                # --- Оценка через DeepSeek (цена/производительность) ---
                if self.deepseek and filtered_ads:
                    filtered_ads = self.parse_full_description(ads=filtered_ads)
                    filtered_ads = self.rate_ads(ads=filtered_ads)
                else:
                    filtered_ads = self.parse_full_description(ads=filtered_ads)

                self.notifier.notify_many(ads=filtered_ads)
                filtered_ads = self.parse_views(ads=filtered_ads)
                filtered_ads = self.parse_phone(ads=filtered_ads)

                if filtered_ads:
                    self.__save_viewed(ads=filtered_ads)
                    ads_in_link.extend(filtered_ads)

                logger.info(f"Пауза {self.config.pause_between_links} сек.")
                time.sleep(self.config.pause_between_links)

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


    def filter_ads(self, ads: list[Item]) -> list[Item]:
        return self.ads_filter.apply(ads)

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
        if not (self.config.parse_full_description or self.config.use_deepseek):
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

    def rate_ads(self, ads: list[Item]) -> list[Item]:
        """Оценивает объявления через DeepSeek, фильтрует по порогу и сортирует.

        Результат: список отсортирован по убыванию оценки цена/производительность.
        Лучшие объявления сохраняются в историю для калибровки последующих оценок.
        Оценка идёт пакетами по deepseek_batch_size (один запрос = пачка).
        """
        batch_ads = ads[: self.config.deepseek_max_ads_per_run]
        batch_size = max(1, self.config.deepseek_batch_size)
        logger.info(
            f"Оцениваю {len(batch_ads)} из {len(ads)} объявлений через DeepSeek "
            f"(пакетами по {batch_size})"
        )
        for start in range(0, len(batch_ads), batch_size):
            if self.stop_event and self.stop_event.is_set():
                break
            chunk = batch_ads[start : start + batch_size]
            self.deepseek.evaluate_batch(chunk)

        rated = [ad for ad in ads if ad.ai_score >= self.config.min_deepseek_score]
        rated.sort(key=lambda ad: ad.ai_score, reverse=True)

        for ad in rated[: self.config.deepseek_history_size]:
            self.deepseek.add_to_history(ad)

        logger.info(f"После оценки осталось {len(rated)} объявлений")
        return rated

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

    def __save_viewed(self, ads: list[Item]) -> None:
        """Сохраняет просмотренные объявления"""
        try:
            self.db_handler.add_record_from_page(ads=ads)
        except Exception as err:
            logger.info(f"При сохранении в БД ошибка {err}")


if __name__ == "__main__":
    try:
        config = load_avito_config("config.toml")
    except Exception as err:
        logger.error(f"Ошибка загрузки конфига: {err}")
        exit(1)

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
