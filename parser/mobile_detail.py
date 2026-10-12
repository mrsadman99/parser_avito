"""Нормализация API карточки в поля базы. Неизвестные значения не затирают старые."""
import json
import re
from urllib.parse import urlsplit

from parser.jsonutil import to_number


REMOVED_CODES = {'item_not_found', 'item_removed', 'item_deleted', 'item_expired', 'item_closed'}
REMOVED_MESSAGES = {
    'объявление не найдено', 'объявление удалено', 'объявление снято с публикации',
    'объявление больше не доступно', 'объявление снято',
}


def parse_mobile_detail(payload, expected_id):
    if not isinstance(payload, dict):
        raise ValueError('Карточка не является JSON-объектом')
    success = payload.get('success')
    mobile = success.get('mobile') if isinstance(success, dict) else None
    if not isinstance(mobile, dict):
        error = payload.get('error')
        code = error.get('code') if isinstance(error, dict) else error
        message = error.get('message', '') if isinstance(error, dict) else payload.get('message', '')
        if str(code).lower() in REMOVED_CODES or str(message).lower().strip(' .!') in REMOVED_MESSAGES:
            return {'removed': True}
        raise ValueError('API не вернул распознаваемую карточку или явный статус удаления')
    if to_number(mobile.get('id')) != expected_id:
        raise ValueError('ID в ответе карточки не совпадает с запрошенным')
    if mobile.get('isRemoved') is True or mobile.get('status') in ('removed', 'deleted', 'expired', 'closed', 'sold'):
        return {'removed': True}

    fields = {}
    for source, target in [('title', 'title'), ('description', 'description'), ('address', 'address')]:
        if isinstance(mobile.get(source), str):
            fields[target] = mobile[source]
    if not fields.get('title'):
        raise ValueError('В ответе нет названия карточки; старые данные сохранены')
    price = mobile.get('price') or {}
    value = to_number(price.get('value'))
    if value is not None:
        fields['price'] = value
    timestamp = to_number(mobile.get('time'))
    if timestamp is not None:
        fields['sort_time'] = timestamp * 1000
    seo = mobile.get('seo') or {}
    url = seo.get('canonicalUrl') or (mobile.get('sharing') or {}).get('url')
    if isinstance(url, str) and urlsplit(url).hostname in ('www.avito.ru', 'm.avito.ru', 'avito.ru'):
        fields['ad_url'] = url
    address = mobile.get('sellerAddressInfo') or {}
    city = (address.get('fullAddress') or {}).get('locality')
    if isinstance(city, str):
        fields['city'] = city
    if isinstance(address.get('isWithDelivery'), bool):
        fields['has_delivery'] = int(address['isWithDelivery'])
    seller = mobile.get('seller') or {}
    if isinstance(seller.get('domain'), str):
        fields['seller_id'] = seller['domain']
    rating = seller.get('rating') or {}
    score = to_number(rating.get('scoreFloat', rating.get('score')), floating=True)
    if score is not None:
        fields['seller_rating'] = score
    reviews = re.search(r'([\d\s\xa0]+)\s*(?:отзыв|оцен)', str(rating.get('text', '')))
    if reviews:
        fields['seller_reviews'] = to_number(reviews[1])
    images = mobile.get('images')
    if isinstance(images, list):
        fields['images_json'] = json.dumps(images, ensure_ascii=False)
        if images and isinstance(images[0], dict):
            sizes = [(int(w) * int(h), url) for key, url in images[0].items()
                     if (match := re.fullmatch(r'(\d+)x(\d+)', key))
                     for w, h in [match.groups()] if isinstance(url, str)]
            if sizes:
                fields['photo_url'] = max(sizes)[1]
    coords = mobile.get('coords')
    if isinstance(coords, dict):
        fields['coords_json'] = json.dumps(coords, ensure_ascii=False)
    for key, target in [('categoryId', 'category_id')]:
        value = to_number(mobile.get(key))
        if value is not None:
            fields[target] = value
    if 'nativeVideo' in mobile:
        fields['has_video'] = int(bool((mobile.get('nativeVideo') or {}).get('url')))
    # Объединённое reserved_or_out_of_stock=true НЕ доказывает наличие брони.
    reserved = mobile.get('isReserved')
    if not isinstance(reserved, bool):
        reservation = mobile.get('reservation') or {}
        reserved = reservation.get('isReserved') if isinstance(reservation, dict) else None
    if isinstance(reserved, bool):
        fields['is_reserved'] = int(reserved)
    elif mobile.get('status') == 'reserved':
        fields['is_reserved'] = 1
    else:
        combined = (((mobile.get('uxFeedbackConfig') or {}).get('attributes') or {}).get('boolAttrs') or {}).get('is_reserved_or_out_of_stock')
        if combined is False:
            fields['is_reserved'] = 0
    return {'removed': False, 'fields': fields}
