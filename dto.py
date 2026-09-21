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
class SshConfig:
    """SSH-подключение к телефону (Termux sshd) для запуска своего мобильного прокси."""
    host: str = ""               # IP-адрес телефона
    port: int = 8022             # порт SSH (у Termux sshd по умолчанию 8022)
    user: str = ""               # пользователь SSH (в Termux — имя из `whoami`)
    password: str = ""


@dataclass
class OwnMobileProxyConfig:
    """Свой мобильный прокси: tinyproxy на телефоне, запуск/остановка по SSH (без adb)."""
    use: bool = False
    port: int = 8888             # порт tinyproxy на телефоне
    rotate_ip: bool = True       # смена IP (airplane mode) при блокировке
    login: str = ""
    password: str = ""
    server: str = ""             # адрес прокси (host или host:port) для парсера и SPFA; пусто = ssh.host
    ssh: SshConfig = field(default_factory=SshConfig)


@dataclass
class ExternalMobileProxyConfig:
    """Внешний мобильный прокси (платный сервис, напр. mobileproxy.rent)."""
    proxy_string: Optional[str] = None
    change_urls: List[str] = field(default_factory=list)  # ссылки смены IP, по порядку


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
    own_mobile_proxy: OwnMobileProxyConfig = field(default_factory=OwnMobileProxyConfig)
    external_mobile_proxy: ExternalMobileProxyConfig = field(default_factory=ExternalMobileProxyConfig)
    messengers: MessengersConfig = field(default_factory=MessengersConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    seller_black_list: List[str] = field(default_factory=list)
    count: int = 1
    debug_mode: int = 0
    detached_mode: bool = False  # true — фоновые процессы вместо tmux (parser/api/web)
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
