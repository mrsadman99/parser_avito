import html as html_lib
import json
import random
import re
import threading
import time
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
from utils.own_mobile_proxy import ensure_own_mobile_proxy
from version import VERSION
from lang import SPFA_PROXY_REQUIRED

DEBUG_MODE = False

logger.add("logs/app.log", rotation="5 MB", retention="5 days", level="DEBUG")


class RequestThrottle:
    """Сериализует все запросы к Avito общей случайной задержкой между ними.

    Запросы от разных ссылок/потоков встают в очередь на блокировке; перед
    каждым следующим запросом выдерживается случайная пауза в [min_delay, max_delay].
    Пауза запускается только после того, как предыдущий запрос полностью обработался.
    """

    def __init__(self, min_delay: float, max_delay: float):
        self.min_delay = max(0.0, float(min_delay))
        self.max_delay = max(self.min_delay, float(max_delay))
        self._lock = threading.Lock()
        self._first = True

    def run(self, fn, *args, **kwargs):
        with self._lock:
            if self._first:
                self._first = False
            else:
                time.sleep(random.uniform(self.min_delay, self.max_delay))
            return fn(*args, **kwargs)


class AvitoParse:
    def __init__(
            self,
            config: AvitoConfig,
            stop_event=None,
            links_provider=None
    ):
        self.config = config
        self.links_provider = links_provider
        ensure_own_mobile_proxy(self.config)
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
        self.throttle = RequestThrottle(config.min_delay, config.max_delay)
        log_config(config=self.config, version=VERSION)

    def _current_links(self):
        """Актуальный набор ссылок: из конфига + из внешнего провайдера (веб).

        При совпадении URL приоритет у провайдера (ссылки, управляемые через веб).
        """
        links = dict(self.config.links or {})
        if self.links_provider is not None:
            try:
                provider_links = self.links_provider()
                if provider_links:
                    links.update(provider_links)
            except Exception as err:
                logger.warning(f"Не удалось получить ссылки из провайдера: {err}")
        return links

    def get_proxy_obj(self) -> Proxy | None:
        if all([self.config.external_mobile_proxy.proxy_string,
                self.config.external_mobile_proxy.change_urls]):
            return Proxy(
                proxy_string=self.config.external_mobile_proxy.proxy_string,
                change_ip_link=self.config.external_mobile_proxy.change_urls[0]
            )
        logger.info("Работаем без прокси")
        return None

    def _is_stopped(self) -> bool:
        return self.stop_event is not None and self.stop_event.is_set()

    def _sleep_interruptible(self, seconds: float) -> None:
        """Спит указанное время, прерываясь по stop_event."""
        if seconds <= 0:
            return
        if self.stop_event is None:
            time.sleep(seconds)
            return
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_event.is_set():
                return
            time.sleep(min(1.0, end - time.time()))

    def _request(self, url: str):
        """Единый запрос к Avito через общий троттлинг (общая случайная задержка)."""
        if self.camoufox:
            return self.throttle.run(self.camoufox.request, "GET", url)
        return self.throttle.run(self.http.request, "GET", url)

    def fetch_data(self, url: str) -> str | None:
        if self._is_stopped():
            return None

        try:
            response = self._request(url)
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
        if self._is_stopped():
            return None

        page_url = self._api_url_for_page(api_url, page)
        try:
            response = self._request(page_url)
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
        self.result_storage = build_result_storage(config=self.config)

        current_ip = self.http.get_current_ip()
        if current_ip:
            if self.config.external_mobile_proxy.proxy_string or self.config.own_mobile_proxy.use:
                logger.info(f"🌐 IP (через прокси): {current_ip}")
            else:
                logger.info(f"🌐 Текущий IP: {current_ip}")
        else:
            logger.warning("Не удалось определить текущий IP")

        workers: dict[str, threading.Thread] = {}

        # Шедулер: следит за активными ссылками, запускает/убирает воркеры.
        while not self._is_stopped():
            links = self._current_links()

            for source_url, link_cfg in links.items():
                if source_url not in workers:
                    t = threading.Thread(
                        target=self._link_cycle,
                        args=(source_url, link_cfg),
                        daemon=True,
                    )
                    t.start()
                    workers[source_url] = t

            for source_url in list(workers):
                if not workers[source_url].is_alive():
                    del workers[source_url]

            self._sleep_interruptible(3.0)

        logger.info(
            f"Хорошие запросы: {self.good_request_count}шт, "
            f"плохие: {self.bad_request_count}шт"
        )

    def _link_cycle(self, source_url: str, link_cfg):
        """Цикл обработки одной ссылки: полный обход, затем пауза pause_general.

        После каждого цикла ссылка перечитывается: если её удалили — воркер
        завершается, если настройки поменялись — применяются новые.
        """
        try:
            api_url = self.url_converter.convert(source_url)
        except Exception as err:
            logger.error(
                f"Не удалось преобразовать ссылку Avito в API URL "
                f"{source_url}: {err}"
            )
            return

        while not self._is_stopped():
            current_links = self._current_links()
            if source_url not in current_links:
                logger.info(
                    f"🔗 Ссылка удалена, завершаю работу: {self._query_label(source_url)}"
                )
                return
            link_cfg = current_links[source_url]

            self._process_link(source_url, link_cfg, api_url)

            if self._is_stopped():
                return
            logger.info(
                f"Пауза до следующего цикла ссылки {self._query_label(source_url)}: "
                f"{self.config.pause_general} сек."
            )
            self._sleep_interruptible(self.config.pause_general)

    def _process_link(self, source_url: str, link_cfg, api_url: str):
        """Один полный обход ссылки: все страницы + фильтрация + сохранение."""
        query_label = self._query_label(source_url)
        if link_cfg.min_price is not None or link_cfg.max_price is not None:
            lo = link_cfg.min_price if link_cfg.min_price is not None else 0
            hi = link_cfg.max_price if link_cfg.max_price is not None else "∞"
            logger.info(f"Ценовой диапазон ссылки: {lo} – {hi}")
        link_got_data = False
        ads_in_link = []

        logger.info(f"🔍 Сканирую ссылку: {query_label}")

        for page in range(1, self.config.count + 1):
            logger.info(f"page={page}")
            if self._is_stopped():
                return

            json_data = self.fetch_api_data(api_url=api_url, page=page)
            if not json_data:
                logger.warning(f"Не удалось получить данные API для {query_label}")
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
                geo=link_cfg.geo,
                start_date=link_cfg.start_date,
                ignore_reserv=link_cfg.ignore_reserv,
                ignore_promotion=link_cfg.ignore_promotion,
            )

            filtered_ads = self.open_full_ad(ads=filtered_ads)

            try:
                self.notifier.notify_many(ads=filtered_ads)
            except Exception as err:
                logger.warning(f"Ошибка при отправке уведомлений: {err}")

            filtered_ads = self.parse_phone(ads=filtered_ads)

            if filtered_ads:
                self.__save_viewed(ads=filtered_ads, source_url=source_url)
                ads_in_link.extend(filtered_ads)

        status = "✅ успешно" if link_got_data else "❌ не удалось"
        logger.info(
            f"📊 Сканирование: {query_label} | "
            f"объявлений: {len(ads_in_link)} | "
            f"статус: {status}"
        )

        if ads_in_link:
            logger.info(f"Сохраняю {len(ads_in_link)} объявлений")
            self.result_storage.save(ads_in_link)
        else:
            logger.info("Сохранять нечего")

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
                   white_list=None, black_list=None, geo=None, start_date=None,
                   ignore_reserv=True, ignore_promotion=False) -> list[Item]:
        # Свежий экземпляр на вызов: AdsFilter.apply() хранит параметры ссылки
        # в self.*, поэтому общий экземпляр нельзя переиспользовать между потоками.
        ads_filter = AdsFilter(config=self.config, is_viewed_fn=self.is_viewed)
        return ads_filter.apply(
            ads,
            min_price=min_price,
            max_price=max_price,
            white_list=white_list,
            black_list=black_list,
            geo=geo,
            start_date=start_date,
            ignore_reserv=ignore_reserv,
            ignore_promotion=ignore_promotion,
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

    def open_full_ad(self, ads: list[Item]) -> list[Item]:
        """Открывает страницу каждого объявления и подтягивает ПОЛНОЕ описание.

        В выдаче API каталога описание обрезано (~250 символов), поэтому для
        полного текста делаем отдельный запрос на страницу объявления.
        """
        if not self.config.open_full_ad:
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
    def _extract_seller_slug(data):
        match = re.search(r"/brands/([^/?#]+)", str(data))
        if match:
            return match.group(1)
        return None

    def is_viewed(self, ad: Item) -> bool:
        """Проверяет, смотрели мы это или нет"""
        return self.db_handler.record_exists(record_id=ad.id, price=ad.priceDetailed.value)

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

    has_spfa_proxy = bool(
        (config.external_mobile_proxy.proxy_string or "").strip()
        or config.own_mobile_proxy.use
    )
    if config.use_bypass_api and not has_spfa_proxy:
        logger.critical(f"SPFA не будет работать без прокси. {SPFA_PROXY_REQUIRED}")
        exit(1)

    if config.use_bypass_api and not config.external_mobile_proxy.change_urls:
        logger.warning(
            "SPFA запущен с серверным (статическим) прокси. Если будет много ошибок - установить большие "
            "min_delay/max_delay и pause_general, чтобы снизить риск блокировок."
        )

    try:
        AvitoParse(config).parse()
    except KeyboardInterrupt:
        logger.info("Парсинг остановлен")
    except Exception as err:
        logger.exception(err)
