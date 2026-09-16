from typing import List

from loguru import logger

from dto import AvitoConfig
from models import Item


class AdsFilter:
    def __init__(self, config: AvitoConfig, is_viewed_fn=None):
        self.config = config
        self.is_viewed_fn = is_viewed_fn

    def apply(self, ads: List[Item], min_price=None, max_price=None,
              white_list=None, black_list=None) -> List[Item]:
        """Применяет все фильтры по порядку (можно задать цену/слова на конкретную ссылку)."""
        self._min_price = self.config.min_price if min_price is None else min_price
        self._max_price = self.config.max_price if max_price is None else max_price
        self._white_list = white_list or self.config.white_list
        self._black_list = black_list or self.config.black_list
        filters = [
            self._filter_viewed,
            self._filter_by_price_range,
            self._filter_by_black_keywords,
            self._filter_by_white_keyword,
            self._filter_by_address,
            self._filter_by_seller,
            self._filter_by_recent_time,
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
        if not self._min_price and not self._max_price:
            return ads
        try:
            return [ad for ad in ads if self._min_price <= ad.priceDetailed.value <= self._max_price]
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
        if not self.config.geo:
            return ads
        return [ad for ad in ads if self.config.geo in getattr(ad, "geo", {}).get("formattedAddress", "")]

    def _filter_by_seller(self, ads: List[Item]) -> List[Item]:
        if not self.config.seller_black_list:
            return ads
        return [ad for ad in ads if not getattr(ad, "sellerId", None) or ad.sellerId not in self.config.seller_black_list]

    def _filter_by_recent_time(self, ads: List[Item]) -> List[Item]:
        if not self.config.max_age:
            return ads
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        filtered = []
        for ad in ads:
            published = datetime.utcfromtimestamp(ad.sortTimeStamp / 1000)
            if (now - published) <= timedelta(seconds=self.config.max_age):
                filtered.append(ad)
        return filtered

    def _filter_by_reserve(self, ads: List[Item]) -> List[Item]:
        if not self.config.ignore_reserv:
            return ads
        return [ad for ad in ads if not getattr(ad, "isReserved", False)]

    def _filter_by_promotion(self, ads: List[Item]) -> List[Item]:
        if not self.config.ignore_promotion:
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
