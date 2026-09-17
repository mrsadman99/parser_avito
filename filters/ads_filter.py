from datetime import datetime
from typing import List

from loguru import logger

from dto import AvitoConfig
from models import Item


class AdsFilter:
    def __init__(self, config: AvitoConfig, is_viewed_fn=None):
        self.config = config
        self.is_viewed_fn = is_viewed_fn

    def apply(self, ads: List[Item], min_price=None, max_price=None,
              white_list=None, black_list=None, geo=None, start_date=None,
              ignore_reserv=True, ignore_promotion=False) -> List[Item]:
        """Применяет все фильтры по порядку (настройки задаются на конкретную ссылку)."""
        self._min_price = min_price
        self._max_price = max_price
        self._white_list = white_list or []
        self._black_list = black_list or []
        self._geo = geo
        self._start_date = start_date
        self._ignore_reserv = ignore_reserv
        self._ignore_promotion = ignore_promotion
        filters = [
            self._filter_viewed,
            self._filter_by_price_range,
            self._filter_by_black_keywords,
            self._filter_by_white_keyword,
            self._filter_by_address,
            self._filter_by_seller,
            self._filter_by_start_date,
            self._filter_by_reserve,
            self._filter_by_promotion,
        ]

        for filter_fn in filters:
            ads = filter_fn(ads)
            logger.info(f"После фильтрации {filter_fn.__name__} осталось {len(ads)}")
            if not ads:
                return ads
        return ads

    def _filter_viewed(self, ads: List[Item]) -> List[Item]:
        if self.is_viewed_fn:
            return [ad for ad in ads if not self.is_viewed_fn(ad)]
        return ads

    def _filter_by_price_range(self, ads: List[Item]) -> List[Item]:
        if self._min_price is None and self._max_price is None:
            return ads
        lo = self._min_price if self._min_price is not None else float("-inf")
        hi = self._max_price if self._max_price is not None else float("inf")
        try:
            return [ad for ad in ads if lo <= ad.priceDetailed.value <= hi]
        except Exception:
            return ads

    def _filter_by_black_keywords(self, ads: List[Item]) -> List[Item]:
        if not self._black_list:
            return ads
        return [ad for ad in ads if not self._is_phrase_in_ads(ad, self._black_list)]

    def _filter_by_white_keyword(self, ads: List[Item]) -> List[Item]:
        if not self._white_list:
            return ads
        return [ad for ad in ads if self._is_phrase_in_ads(ad, self._white_list)]

    def _filter_by_address(self, ads: List[Item]) -> List[Item]:
        """Фильтр по городу: совпадение с location.name / namePrepositional / formattedAddress."""
        if not self._geo:
            return ads
        geo = self._geo.lower()
        result = []
        for ad in ads:
            location = getattr(ad, "location", None)
            location_name = getattr(location, "name", "") or ""
            location_prep = getattr(location, "namePrepositional", "") or ""
            formatted = getattr(getattr(ad, "geo", None), "formattedAddress", "") or ""
            if geo in location_name.lower() or geo in location_prep.lower() or geo in formatted.lower():
                result.append(ad)
        return result

    def _filter_by_seller(self, ads: List[Item]) -> List[Item]:
        if not self.config.seller_black_list:
            return ads
        return [ad for ad in ads if not getattr(ad, "sellerId", None) or ad.sellerId not in self.config.seller_black_list]

    def _filter_by_start_date(self, ads: List[Item]) -> List[Item]:
        """Оставляет объявления, опубликованные не раньше start_date (YYYY-MM-DD)."""
        if not self._start_date:
            return ads
        try:
            start = datetime.fromisoformat(self._start_date).date()
        except ValueError:
            return ads
        result = []
        for ad in ads:
            if not ad.sortTimeStamp:
                continue
            published = datetime.utcfromtimestamp(ad.sortTimeStamp / 1000).date()
            if published >= start:
                result.append(ad)
        return result

    def _filter_by_reserve(self, ads: List[Item]) -> List[Item]:
        if not self._ignore_reserv:
            return ads
        return [ad for ad in ads if not getattr(ad, "isReserved", False)]

    def _filter_by_promotion(self, ads: List[Item]) -> List[Item]:
        if not self._ignore_promotion:
            return ads
        for ad in ads:
            ad.isPromotion = any(
                v.get("title") == "Продвинуто"
                for step in (ad.iva or {}).get("DateInfoStep", [])
                for v in step.payload.get("vas", [])
            )
        return [ad for ad in ads if not ad.isPromotion]

    @staticmethod
    def _is_phrase_in_ads(ad: Item, phrases: list) -> bool:
        full_text = ((ad.title or "") + (ad.description or "")).lower()
        return any(phrase.lower() in full_text for phrase in phrases)
