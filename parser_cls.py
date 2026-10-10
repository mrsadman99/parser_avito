import html as html_lib
import json
import random
import re
import threading
import multiprocessing
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from loguru import logger
from pydantic import ValidationError

from common_data import HEADERS
from db_service import SQLiteDBHandler, _now_iso
from dto import Proxy, AvitoConfig, ParseTarget
from filters.ads_filter import AdsFilter
from hide_private_data import log_config
from integrations.notifications.factory import build_notifier
from load_config import load_avito_config
from models import ItemsResponse, Item
from parser.cookies.factory import build_cookies_provider
from parser.cancellation import Cancellation, ParseCancelled, cancellable_lock
from parser.export.factory import build_result_storage
from parser.http.client import HttpClient
from parser.http.camoufox_client import CamoufoxClient
from parser.proxies.proxy_factory import build_proxy
from parser.proxies.proxy import ProxyRotationError
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

    def run(self, fn, *args, cancellation=None, **kwargs):
        cancellation = cancellation or Cancellation()
        with cancellable_lock(self._lock, cancellation):
            if not self._first:
                cancellation.wait(random.uniform(self.min_delay, self.max_delay))
            cancellation.checkpoint()
            self._first = False
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
        self._shutdown = threading.Event()
        self._fatal_error = None
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
        """Подписки из TOML и веба, каждая со своими фильтрами и историей."""
        links = {url: ParseTarget(url, config) for url, config in (self.config.links or {}).items()}
        if self.links_provider is not None:
            try:
                provider_links = self.links_provider()
                self._provider_links = {
                    key: value if isinstance(value, ParseTarget) else ParseTarget(key, value)
                    for key, value in (provider_links or {}).items()
                }
            except Exception as err:
                logger.warning(f"Не удалось получить ссылки из провайдера: {err}")
            # Ошибка чтения БД не означает удаление всех подписок.
            links.update(getattr(self, "_provider_links", {}))
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
        shutdown = getattr(self, "_shutdown", None)
        return ((shutdown is not None and shutdown.is_set())
                or (self.stop_event is not None and self.stop_event.is_set()))

    def _sleep_interruptible(self, seconds: float) -> None:
        """Спит указанное время, прерываясь по stop_event."""
        if seconds <= 0:
            return
        end = time.monotonic() + seconds
        while not self._is_stopped():
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    def _request(self, url: str, cancellation=None):
        """Единый запрос к Avito через общий троттлинг (общая случайная задержка)."""
        cancellation = cancellation or Cancellation(self._is_stopped)
        client = self.camoufox or self.http
        return self.throttle.run(
            lambda: client.request("GET", url, cancellation=cancellation),
            cancellation=cancellation,
        )

    def fetch_data(self, url: str, cancellation=None) -> str | None:
        if self._is_stopped():
            return None

        try:
            response = self._request(url, cancellation=cancellation)
            self.good_request_count += 1
            return response.text

        except (ParseCancelled, ProxyRotationError):
            raise
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

    def fetch_api_data(self, api_url: str, page: int, cancellation=None) -> dict | None:
        if self._is_stopped():
            return None

        page_url = self._api_url_for_page(api_url, page)
        try:
            response = self._request(page_url, cancellation=cancellation)
            self.good_request_count += 1
            return response.json()
        except (ParseCancelled, ProxyRotationError):
            raise
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

        notification_stop = threading.Event()
        threading.Thread(target=self._notification_cycle, args=(notification_stop,), daemon=True).start()
        try:
            # Шедулер не ждёт медленные отправки в мессенджеры.
            while not self._is_stopped():
                links = self._current_links()

                for source_key, target in links.items():
                    if source_key not in workers:
                        t = threading.Thread(
                            target=self._link_cycle,
                            args=(source_key, target),
                            daemon=True,
                        )
                        t.start()
                        workers[source_key] = t

                for source_key in list(workers):
                    if not workers[source_key].is_alive():
                        del workers[source_key]

                self._sleep_interruptible(3.0)
        finally:
            notification_stop.set()
            self._shutdown.set()

        if self._fatal_error is not None:
            raise self._fatal_error

        logger.info(
            f"Хорошие запросы: {self.good_request_count}шт, "
            f"плохие: {self.bad_request_count}шт"
        )

    def _link_cycle(self, source_key: str, target: ParseTarget):
        """Обход и пауза отменяются при изменении версии или удалении подписки."""
        while not self._is_stopped():
            current_links = self._current_links()
            if source_key not in current_links:
                logger.info(
                    f"🔗 Ссылка удалена, завершаю работу: {self._query_label(target.url)}"
                )
                return
            target = current_links[source_key]
            cancellation = Cancellation(
                lambda: self._is_stopped() or self._current_links().get(source_key) != target
            )
            try:
                api_url = self.url_converter.convert(target.url, cancellation=cancellation)
                self._process_link(target.url, target.config, api_url,
                                   source_key=source_key, cancellation=cancellation)
                logger.info(
                    f"Пауза до следующего цикла ссылки {self._query_label(target.url)}: "
                    f"{self.config.pause_general} сек."
                )
                cancellation.wait(self.config.pause_general)
            except ProxyRotationError as err:
                self._fatal_error = err
                self._shutdown.set()
                logger.critical(f"Все попытки смены IP неуспешны, завершаю парсер: {err}")
                return
            except ParseCancelled:
                logger.info(
                    f"Обход прерван: {self._query_label(target.url)}; "
                    "проверяю актуальные настройки ссылки"
                )
                # Без pause_general: новые фильтры начинают обход с первой страницы.
                continue
            except Exception as err:
                if self._is_stopped() or self._current_links().get(source_key) != target:
                    continue
                logger.exception(f"Ошибка обхода {self._query_label(target.url)}: {err}")
                return

    def _process_link(self, source_url: str, link_cfg, api_url: str, source_key: str | None = None,
                      cancellation: Cancellation | None = None):
        """Один полный обход ссылки: все страницы + фильтрация + сохранение."""
        query_label = self._query_label(source_url)
        cancellation = cancellation or Cancellation(self._is_stopped)
        cancellation.checkpoint()
        source_key = source_key if source_key is not None else source_url
        if link_cfg.min_price is not None or link_cfg.max_price is not None:
            lo = link_cfg.min_price if link_cfg.min_price is not None else 0
            hi = link_cfg.max_price if link_cfg.max_price is not None else "∞"
            logger.info(f"Ценовой диапазон ссылки: {lo} – {hi}")
        link_got_data = False
        ads_in_link = []

        logger.info(f"🔍 Сканирую ссылку: {query_label}")

        for page in range(1, self.config.count + 1):
            cancellation.checkpoint()
            logger.info(f"Ссылка {query_label}: page={page}")

            json_data = self.fetch_api_data(api_url=api_url, page=page, cancellation=cancellation)
            cancellation.checkpoint()
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
                source_key=source_key,
            )

            cancellation.checkpoint()
            filtered_ads = self.open_full_ad(ads=filtered_ads, cancellation=cancellation)

            filtered_ads = self.parse_phone(ads=filtered_ads)

            cancellation.checkpoint()
            if filtered_ads:
                self.__save_viewed(ads=filtered_ads, source_url=source_url, source_key=source_key)
                # Завершённая страница попадает в Excel даже при отмене следующей.
                self.result_storage.save(filtered_ads)
                ads_in_link.extend(filtered_ads)

        status = "✅ успешно" if link_got_data else "❌ не удалось"
        logger.info(
            f"📊 Сканирование: {query_label} | "
            f"объявлений: {len(ads_in_link)} | "
            f"статус: {status}"
        )

    def _notification_cycle(self, stop_event):
        while not stop_event.is_set() and not self._is_stopped():
            try:
                self._deliver_pending_notifications(stop_event)
            except Exception as err:
                logger.warning(f"Ошибка обработки очереди уведомлений: {err}")
            stop_event.wait(3.0)

    def _deliver_pending_notifications(self, stop_event=None):
        """Доставляет сохранённые объявления, повторяя только неудачные отправки."""
        targets = self.notifier.delivery_targets()
        for _ in range(100):
            if self._is_stopped() or (stop_event is not None and stop_event.is_set()):
                return
            entry = self.db_handler.claim_notification(list(targets))
            if entry is None:
                return
            try:
                ad = Item.model_validate_json(entry["payload"])
                targets[entry["recipient"]].notify(ad=ad)
            except Exception as err:
                logger.warning(f"Уведомление {entry['id']} не доставлено, повтор через 60 сек.: {err}")
                self.db_handler.finish_notification(entry["id"], success=False)
            else:
                self.db_handler.finish_notification(entry["id"], success=True)

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
                   ignore_reserv=True, ignore_promotion=False, source_key="") -> list[Item]:
        # Свежий экземпляр на вызов: AdsFilter.apply() хранит параметры ссылки
        # в self.*, поэтому общий экземпляр нельзя переиспользовать между потоками.
        ads_filter = AdsFilter(config=self.config, is_viewed_fn=lambda ad: self.is_viewed(ad, source_key))
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

    def open_full_ad(self, ads: list[Item], cancellation: Cancellation | None = None) -> list[Item]:
        """Открывает страницу каждого объявления и подтягивает ПОЛНОЕ описание.

        В выдаче API каталога описание обрезано (~250 символов), поэтому для
        полного текста делаем отдельный запрос на страницу объявления.
        """
        cancellation = cancellation or Cancellation(self._is_stopped)
        cancellation.checkpoint()
        if not self.config.open_full_ad:
            return ads

        logger.info("Начинаю парсинг полных описаний")
        for ad in ads:
            try:
                cancellation.checkpoint()
                html_code_full_page = self.fetch_data(url=f"https://www.avito.ru{ad.urlPath}",
                                                       cancellation=cancellation)
                cancellation.checkpoint()
                if not html_code_full_page:
                    continue
                full_description = self._extract_description(html=html_code_full_page)
                if full_description:
                    ad.description = full_description
                delay = random.uniform(0.1, 0.9)
                cancellation.wait(delay)
            except (ParseCancelled, ProxyRotationError):
                raise
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

    def is_viewed(self, ad: Item, source_key: str = "") -> bool:
        """Проверяет, смотрели мы это или нет"""
        return self.db_handler.record_exists(record_id=ad.id, price=ad.priceDetailed.value,
                                             source_key=source_key)

    def __save_viewed(self, ads: list[Item], source_url: str = None, source_key: str | None = None) -> None:
        """Сохраняет просмотренные объявления и ставит дату сканирования (UTC)."""
        now = _now_iso()
        for ad in ads:
            ad.scanned_at = now
        self.db_handler.add_record_from_page(
            ads=ads, source_url=source_url, source_key=source_key,
            recipients=list(self.notifier.delivery_targets()),
        )


if __name__ == "__main__":
    multiprocessing.freeze_support()
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

    parser = None
    try:
        parser = AvitoParse(config)
        parser.parse()
    except KeyboardInterrupt:
        logger.info("Парсинг остановлен")
    except Exception as err:
        logger.exception(err)
        raise SystemExit(1)
    finally:
        if parser is not None:
            parser.close()
