from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


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
class AvitoConfig:
    urls: List[str]
    proxy_string: Optional[str] = None
    proxy_change_url: Optional[str] = None
    keys_word_white_list: List[str] = field(default_factory=list)
    keys_word_black_list: List[str] = field(default_factory=list)
    seller_black_list: List[str] = field(default_factory=list)
    count: int = 1
    tg_token: Optional[str] = None
    tg_chat_id: List[str] = None
    vk_token: Optional[str] = None
    vk_user_id: List[str] = None
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
    proxy_notifier: str = None
    tg_only_text: bool = False
    retry_delay: int = 5
    timeout: int = 20
    block_threshold: int = 3
    # Повторный запуск при неудачном проходе
    retry_on_failure: bool = True
    retry_on_failure_delay: int = 30
    # Оценка через DeepSeek (цена/производительность)
    use_deepseek: bool = False
    deepseek_api_key: str = None
    deepseek_model: str = "deepseek-chat"
    deepseek_max_ads_per_run: int = 30
    deepseek_batch_size: int = 5
    deepseek_history_size: int = 10
    min_deepseek_score: int = 0
    parse_full_description: bool = False

