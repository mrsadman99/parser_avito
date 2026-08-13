"""
Утилита для построения словаря proxies из строки прокси.

Строит словарь {http, socks5} (без https). Адрес всегда в формате
{login}:{password}@{address}:{port} (или {address}:{port} без авторизации).

Для SOCKS5 требуется установленный пакет PySocks (requests[socks]).
"""


def build_proxies_dict(proxy: str):
    """Строит словарь прокси: http + socks5 (без https).

    Адрес всегда передаётся в формате {login}:{password}@{address}:{port}
    (или просто {address}:{port} без авторизации). Если схему случайно указали,
    она отбрасывается — оба варианта строятся из одного адреса.

    Пример:
        "login:pass@127.0.0.1:5222"
        -> {
            "http":   "http://login:pass@127.0.0.1:5222",
            "socks5": "socks5://login:pass@127.0.0.1:5222",
        }
    """
    if not proxy:
        return None
    addr = proxy
    if "://" in addr:
        addr = addr.split("://", 1)[1]
    return {
        "http": f"http://{addr}",
        "socks5": f"socks5://{addr}",
    }
