from parser.cookies.base import CookiesProvider
from parser.cookies.external_api import ExternalApiCookiesProvider
from parser.cookies.fetch_own import FetchOwnCookiesProvider

def build_cookies_provider(config, proxy=None) -> CookiesProvider | None:
    if config.own_cookies:
        return FetchOwnCookiesProvider(config, proxy=proxy)
    if config.use_bypass_api:
        return ExternalApiCookiesProvider(config, proxy=proxy)

    return None


