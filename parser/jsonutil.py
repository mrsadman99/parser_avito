"""Рекурсивный поиск по JSON-деревьям и извлечение чисел.

Общие помощники для парсинга ответов Avito (каталог, карточка, детальная
страница): рекурсивный поиск значений по ключу и нормализация чисел.
"""
import re


def find_value(data, key):
    """Первое значение по ключу key (рекурсивно); None считается «не найдено»."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k == key:
                return v
            found = find_value(v, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_value(item, key)
            if found is not None:
                return found
    return None


def find_string(data, key, min_len: int = 0):
    """Первое строковое значение по ключу key длиной не меньше min_len."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k == key and isinstance(v, str) and len(v) >= min_len:
                return v
            found = find_string(v, key, min_len)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_string(item, key, min_len)
            if found is not None:
                return found
    return None


def find_dict_with(data, key):
    """Первый dict, лежащий под ключом key (рекурсивно)."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k == key and isinstance(v, dict):
                return v
            found = find_dict_with(v, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_dict_with(item, key)
            if found is not None:
                return found
    return None


def find_dict_containing(data, key):
    """Первый dict, содержащий ключ key (рекурсивно)."""
    if isinstance(data, dict):
        if key in data:
            return data
        for v in data.values():
            found = find_dict_containing(v, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_dict_containing(item, key)
            if found is not None:
                return found
    return None


def to_number(value, floating=False):
    """Число из строки/числа; None для bool/None.

    Понимает неразрывные пробелы (\xa0), обычные пробелы и запятую-десятичный.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
        return float(text) if floating else int(text)
    except (TypeError, ValueError):
        return None


def digits(value):
    """Только цифры из строки; None, если цифр нет."""
    if value is None:
        return None
    text = re.sub(r"[^\d]", "", str(value))
    return int(text) if text else None
