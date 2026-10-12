from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import hashlib
import math


def web_link_key(link_id: int, url: str) -> str:
    """История подписки начинается заново при изменении её URL."""
    return f"web:{link_id}:{hashlib.sha256(url.encode()).hexdigest()}"


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
class ParseTarget:
    """Независимая подписка: URL и фильтры конкретной записи ссылки."""
    url: str
    config: LinkConfig
    revision: int = 0


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
    """Tinyproxy на телефоне; TCP-трафик всегда проходит через ADB."""
    use: bool = False
    port: int = 8888             # устаревшее поле; используется adb_forward[1]
    rotate_ip: bool = True       # смена IP через выбранный транспорт при блокировке
    adb_serial: str = ""         # серийник для adb (пусто — adb без -s)
    login: str = ""
    password: str = ""
    server: str = ""             # host или host:port прокси; без порта — adb_forward[0], пусто = localhost
    ssh: SshConfig = field(default_factory=SshConfig)
    transport: str = "ssh"  # управление: ssh или adb (run-as Termux; root для режима полёта)
    adb_forward: List[int] = field(default_factory=lambda: [8888, 8888])

    def __post_init__(self):
        if self.transport not in ("ssh", "adb"):
            raise ValueError("own_mobile_proxy.transport должен быть ssh или adb")
        if (not isinstance(self.adb_forward, (list, tuple)) or len(self.adb_forward) != 2
                or any(type(port) is not int or not 1 <= port <= 65535 for port in self.adb_forward)):
            raise ValueError("own_mobile_proxy.adb_forward должен быть [порт сервера, порт tinyproxy], оба от 1 до 65535")
        self.adb_forward = list(self.adb_forward)
        self.port = self.adb_forward[1]  # старое поле port: совместимость с GUI/старыми конфигами


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
    pause_general: float = 60.0  # общий перерыв между раундами всех поисковых ссылок, сек
    ad_refresh_interval: float = 3600.0  # сек. от последней проверки каждого объявления; 0 — отключить
    min_delay: float = 1.0      # мин. задержка между запросами к Avito, сек
    max_delay: float = 3.0      # макс. задержка между запросами к Avito, сек
    max_count_of_retry: int = 5
    use_bypass_api: bool = False
    cookies_api_key: str = None
    purchase_cooldown: int = 600
    output_dir: Path = Path("result")
    own_cookies: bool = False   # true — свои cookies, получаются GET к Avito через прокси (fetch_cookies)
    parse_phone: bool = False
    retry_delay: int = 5
    timeout: int = 20
    block_threshold: int = 3
    ip_rotation_attempts: int = 3
    ip_rotation_timeout: float = 90.0  # вся попытка, включая ADB/SSH, сек
    ip_rotation_retry_delay: float = 5.0
    open_full_ad: bool = False

    def __post_init__(self):
        if (isinstance(self.pause_general, bool)
                or not isinstance(self.pause_general, (int, float))
                or not math.isfinite(self.pause_general) or self.pause_general < 0):
            raise ValueError("pause_general должен быть конечным числом >= 0")
        if (isinstance(self.ad_refresh_interval, bool)
                or not isinstance(self.ad_refresh_interval, (int, float))
                or not math.isfinite(self.ad_refresh_interval) or self.ad_refresh_interval < 0):
            raise ValueError("ad_refresh_interval должен быть конечным числом >= 0")
        if type(self.ip_rotation_attempts) is not int or self.ip_rotation_attempts < 1:
            raise ValueError("ip_rotation_attempts должен быть целым числом >= 1")
        for name, minimum in (("ip_rotation_timeout", 0), ("ip_rotation_retry_delay", 0)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} должен быть конечным числом")
            if value < minimum or (name == "ip_rotation_timeout" and value == 0):
                raise ValueError(f"Некорректное значение {name}: {value}")
