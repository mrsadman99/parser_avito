"""Ограниченная схема ответа: без значений и произвольных имён полей."""
import json


# Неизвестные ключи тоже могут содержать ID, URL, токен или имя человека.
# Сохраняем только имена из известного словаря API, остальные нумеруем.
SAFE_KEYS = frozenset('''
    success mobile error errors code message status result results data payload
    id title description address price value time seo canonicalUrl sharing url
    seller sellerAddressInfo fullAddress locality isWithDelivery domain rating
    scoreFloat score text images coords categoryId nativeVideo isReserved
    reservation uxFeedbackConfig attributes boolAttrs is_reserved_or_out_of_stock
    isRemoved items item type name details captcha challenge validationErrors
    redirect redirectUrl location meta reason ok content components widgets
'''.split())


def json_structure(payload) -> str:
    """До 100 узлов, 5 уровней, 20 полей/3 элементов; значения не выводятся."""
    remaining = 100

    def describe(value, depth=0):
        nonlocal remaining
        if remaining <= 0:
            return 'truncated'
        remaining -= 1
        if isinstance(value, dict):
            result = {'type': 'object', 'count': len(value)}
            if depth < 5:
                fields = {}
                for index, (key, child) in enumerate(value.items()):
                    if index >= 20 or remaining <= 0:
                        break
                    label = key if key in SAFE_KEYS else f'<field_{index + 1}>'
                    fields[label] = describe(child, depth + 1)
                result['fields'] = fields
            return result
        if isinstance(value, list):
            result = {'type': 'array', 'count': len(value)}
            if depth < 5:
                result['items'] = [describe(child, depth + 1) for child in value[:3] if remaining > 0]
            return result
        if value is None:
            return 'null'
        if isinstance(value, bool):
            return 'boolean'
        if isinstance(value, (int, float)):
            return 'number'
        if isinstance(value, str):
            return 'string'
        return 'unknown'

    return json.dumps(describe(payload), ensure_ascii=False, separators=(',', ':'))
