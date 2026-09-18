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
    """Настройки отдельной ссылки (всё опционально)."""
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    white_list: List[str] = field(default_factory=list)
    black_list: List[str] = field(default_factory=list)
    geo: Optional[str] = None                 # город (фильтр по региону)
    start_date: Optional[str] = None          # дата "YYYY-MM-DD", с которой искать объявления
    ignore_reserv: bool = True                # пропускать «Зарезервировано»
    ignore_promotion: bool = False            # пропускать продвигаемые


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
class ServerConfig:
    """Настройки веб-приложения (server/ + web-server/, запуск: python run.py)."""
    server_port: int = 8000            # порт REST API + фронтенд
    web_server_port: int = 3000        # порт React dev-сервера (только run.py --dev)
    admin_password: str = ""           # пароль админки (логин: admin)
    server_host: str = "127.0.0.1"     # интерфейс API (0.0.0.0 — слушать наружу)
    cors_origins: List[str] = field(default_factory=list)  # доп. разрешённые origins


@dataclass
class AvitoConfig:
    links: Dict[str, LinkConfig] = field(default_factory=dict)
    camoufox: CamoufoxConfig = field(default_factory=CamoufoxConfig)
    adb_proxy: AdbProxyConfig = field(default_factory=AdbProxyConfig)
    mobile_proxy: MobileProxyConfig = field(default_factory=MobileProxyConfig)
    messengers: MessengersConfig = field(default_factory=MessengersConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    seller_black_list: List[str] = field(default_factory=list)
    count: int = 1
    debug_mode: int = 0
    detached_mode: bool = False  # true — фоновые процессы вместо tmux (proxy/parser/api)
    pause_general: int = 60
    min_delay: float = 1.0      # мин. задержка между запросами к Avito, сек
    max_delay: float = 3.0      # макс. задержка между запросами к Avito, сек
    max_count_of_retry: int = 5
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
    open_full_ad: bool = False
