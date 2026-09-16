from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Proxy:
    proxy_string: str
    change_ip_link: str


@dataclass
class ProxySplit:
    ip_port: str
    login: str
    password: str
    change_ip_link: str


@dataclass
class LinkConfig:
    """Настройки отдельной ссылки (цена и ключевые слова опциональны)."""
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    white_list: List[str] = field(default_factory=list)
    black_list: List[str] = field(default_factory=list)


@dataclass
class CamoufoxConfig:
    """Camoufox — реальный браузер для запросов к поисковой выдаче."""
    use: bool = False
    os: str = "windows"          # windows / macos / linux (десктопный отпечаток)
    headless: bool = True
    humanize: bool = True
    geoip: bool = True


@dataclass
class AdbProxyConfig:
    """ADB-прокси: tinyproxy/microsocks на телефоне, проброс через adb forward."""
    use: bool = False
    device_serial: str = ""
    local_port: int = 1080
    remote_port: int = 1080
    rotate_ip: bool = True
    login: str = ""
    password: str = ""
    server: str = ""             # host:port для SPFA body proxy (пусто = 127.0.0.1:{local_port})


@dataclass
class MobileProxyConfig:
    """Мобильный прокси (используется вместо adb)."""
    proxy_string: Optional[str] = None
    change_url: Optional[str] = None
    change_urls: List[str] = field(default_factory=list)


@dataclass
class MessengersConfig:
    """Мессенджеры для отправки обработанных объявлений."""
    tg_token: Optional[str] = None
    tg_chat_id: List[str] = field(default_factory=list)
    vk_token: Optional[str] = None
    vk_user_id: List[str] = field(default_factory=list)
    proxy_notifier: Optional[str] = None


@dataclass
class AvitoConfig:
    links: Dict[str, LinkConfig] = field(default_factory=dict)
    camoufox: CamoufoxConfig = field(default_factory=CamoufoxConfig)
    adb_proxy: AdbProxyConfig = field(default_factory=AdbProxyConfig)
    mobile_proxy: MobileProxyConfig = field(default_factory=MobileProxyConfig)
    messengers: MessengersConfig = field(default_factory=MessengersConfig)
    white_list: List[str] = field(default_factory=list)
    black_list: List[str] = field(default_factory=list)
    seller_black_list: List[str] = field(default_factory=list)
    count: int = 1
    max_price: int = 999_999_999
    min_price: int = 0
    geo: Optional[str] = None
    max_age: int = 24 * 60 * 60
    debug_mode: int = 0
    pause_general: int = 60
    pause_between_links: int = 5
    max_count_of_retry: int = 5
    ignore_reserv: bool = True
    ignore_promotion: bool = False
    one_time_start: bool = False
    one_file_for_link: bool = False
    parse_views: bool = False
    save_xlsx: bool = True
    use_webdriver: bool = True
    use_bypass_api: bool = False
    cookies_api_key: str = None
    purchase_cooldown: int = 600
    output_dir: Path = Path("result")
    use_own_cookies: bool = False
    parse_phone: bool = False
    retry_delay: int = 5
    timeout: int = 20
    block_threshold: int = 3
    retry_on_failure: bool = True
    retry_on_failure_delay: int = 30
    parse_full_description: bool = False
    # Веб-приложение (server/ + web-server/)
    server_port: int = 8000            # порт REST API
    web_server_port: int = 3000        # порт React dev-сервера
    admin_password: str = ""           # пароль админки (логин: admin)
