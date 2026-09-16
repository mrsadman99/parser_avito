import asyncio
import threading
import time
import os
from pathlib import Path

import flet as ft
from loguru import logger

from dto import AvitoConfig, MessengersConfig
from integrations.notifications.factory import build_notifier
from lang import *
from load_config import save_avito_config, load_avito_config
from parser_cls import AvitoParse
from utils import prompt_user_login
from version import VERSION


def main(page: ft.Page):
    page.title = f'Parser Avito v {VERSION}'
    page.window.icon = str(Path(__file__).parent / "assets" / "logo.ico")
    page.theme_mode = ft.ThemeMode.DARK
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.window.width = 1000
    page.window.height = 980
    page.window.min_width = 650
    page.window.min_height = 500
    page.padding = 20

    page.window.maximized = True

    is_run = False
    stop_event = threading.Event()
    prev_links = {}

    def set_up():
        """Загружает настройки из config.toml и применяет к интерфейсу"""
        nonlocal prev_links
        try:
            config = load_avito_config("config.toml")
        except Exception as err:
            logger.error(f"Ошибка при загрузке конфига: {err}")
            return

        prev_links = config.links
        url_input.value = "\n".join(config.links.keys())
        tg_chat_id.value = "\n".join(config.messengers.tg_chat_id or [])
        tg_token.value = config.messengers.tg_token or ""
        vk_token.value = config.messengers.vk_token or ""
        vk_user_id.value = "\n".join(config.messengers.vk_user_id or [])
        count_page.value = str(config.count)
        white_list.value = "\n".join(config.white_list or [])
        black_list.value = "\n".join(config.black_list or [])
        max_price.value = str(config.max_price)
        min_price.value = str(config.min_price)
        geo.value = config.geo or ""
        proxy.value = config.mobile_proxy.proxy_string or ""
        proxy_change_ip.value = config.mobile_proxy.change_url or ""
        pause_general.value = config.pause_general or 60
        pause_between_links.value = config.pause_between_links or 5
        max_age.value = config.max_age or 0
        seller_black_list.value = "\n".join(config.seller_black_list or [])
        ignore_ads_in_reserv.value = config.ignore_reserv
        ignore_promote_ads.value = config.ignore_promotion
        max_count_of_retry.value = config.max_count_of_retry or 5
        one_time_start.value = config.one_time_start
        one_file_for_link.value = config.one_file_for_link
        parse_views.value = config.parse_views
        save_xlsx.value = config.save_xlsx
        use_webdriver.value = config.use_webdriver
        use_bypass_api.value = config.use_bypass_api
        cookies_api_key.value = config.cookies_api_key
        purchase_cooldown.value = str(config.purchase_cooldown)
        use_own_account.value = config.use_own_cookies
        parse_phone.value = config.parse_phone
        proxy_notifier.value = config.messengers.proxy_notifier
        retry_delay.value = config.retry_delay
        timeout.value = config.timeout
        block_threshold.value = config.block_threshold
        retry_on_failure.value = config.retry_on_failure
        retry_on_failure_delay.value = str(config.retry_on_failure_delay)
        parse_full_description.value = config.parse_full_description
        use_camoufox.value = config.camoufox.use
        camoufox_os.value = config.camoufox.os or "windows"
        camoufox_headless.value = config.camoufox.headless
        camoufox_humanize.value = config.camoufox.humanize
        camoufox_geoip.value = config.camoufox.geoip
        use_adb_proxy.value = config.adb_proxy.use
        adb_device_serial.value = config.adb_proxy.device_serial or ""
        adb_local_port.value = str(config.adb_proxy.local_port)
        adb_remote_port.value = str(config.adb_proxy.remote_port)
        adb_rotate_ip.value = config.adb_proxy.rotate_ip
        adb_proxy_login.value = config.adb_proxy.login or ""
        adb_proxy_password.value = config.adb_proxy.password or ""
        adb_proxy_server.value = config.adb_proxy.server or ""

        page.update()

    def to_int_safe(value, default=0):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def save_config():
        """Сохраняет настройки в TOML"""
        nonlocal prev_links
        link_urls = [u.strip() for u in (url_input.value or "").splitlines() if u.strip()]
        links = {}
        for u in link_urls:
            prev = prev_links.get(u)
            if prev is not None:
                cfg = {}
                if prev.min_price is not None:
                    cfg["min_price"] = prev.min_price
                if prev.max_price is not None:
                    cfg["max_price"] = prev.max_price
                if prev.white_list:
                    cfg["white_list"] = prev.white_list
                if prev.black_list:
                    cfg["black_list"] = prev.black_list
                links[u] = cfg
            else:
                links[u] = {}

        config = {"avito": {
            "links": links,
            "messengers": {
                "tg_token": tg_token.value or "",
                "tg_chat_id": tg_chat_id.value.splitlines() if tg_chat_id.value else [],
                "vk_token": vk_token.value or "",
                "vk_user_id": vk_user_id.value.splitlines() if vk_user_id.value else [],
                "proxy_notifier": proxy_notifier.value or "",
            },
            "camoufox": {
                "use": use_camoufox.value,
                "os": camoufox_os.value or "windows",
                "headless": camoufox_headless.value,
                "humanize": camoufox_humanize.value,
                "geoip": camoufox_geoip.value,
            },
            "adb_proxy": {
                "use": use_adb_proxy.value,
                "device_serial": adb_device_serial.value or "",
                "local_port": to_int_safe(adb_local_port.value, 1080),
                "remote_port": to_int_safe(adb_remote_port.value, 1080),
                "rotate_ip": adb_rotate_ip.value,
                "login": adb_proxy_login.value or "",
                "password": adb_proxy_password.value or "",
                "server": adb_proxy_server.value or "",
            },
            "mobile_proxy": {
                "proxy_string": proxy.value or "",
                "change_url": proxy_change_ip.value or "",
            },
            "count": to_int_safe(count_page.value, 1),
            "white_list": white_list.value.splitlines() if white_list.value else [],
            "black_list": black_list.value.splitlines() if black_list.value else [],
            "seller_black_list": seller_black_list.value.splitlines() if seller_black_list.value else [],
            "max_price": to_int_safe(max_price.value, 99999999),
            "min_price": to_int_safe(min_price.value, 0),
            "geo": geo.value or "",
            "pause_general": to_int_safe(pause_general.value, 3),
            "pause_between_links": to_int_safe(pause_between_links.value, 1),
            "max_age": to_int_safe(max_age.value, 0),
            "max_count_of_retry": to_int_safe(max_count_of_retry.value, 5),
            "ignore_reserv": ignore_ads_in_reserv.value,
            "ignore_promotion": ignore_promote_ads.value,
            "one_time_start": one_time_start.value,
            "one_file_for_link": one_file_for_link.value,
            "parse_views": parse_views.value,
            "save_xlsx": save_xlsx.value,
            "use_webdriver": use_webdriver.value,
            "use_bypass_api": use_bypass_api.value,
            "cookies_api_key": cookies_api_key.value,
            "purchase_cooldown": to_int_safe(purchase_cooldown.value, 600),
            "use_own_cookies": use_own_account.value,
            "parse_phone": parse_phone.value,
            "retry_delay": to_int_safe(retry_delay.value, 5),
            "timeout": to_int_safe(timeout.value, 20),
            "block_threshold": to_int_safe(block_threshold.value, 3),
            "retry_on_failure": retry_on_failure.value,
            "retry_on_failure_delay": to_int_safe(retry_on_failure_delay.value, 30),
            "parse_full_description": parse_full_description.value,
        }}

        save_avito_config(config)
        logger.debug("Настройки сохранены в config.toml")

    def close_dlg(e):
        dlg_modal_proxy.open = False
        page.update()

    def logger_console_init():
        logger.add(logger_console_widget, format="{time:HH:mm:ss} - {message}")

    def logger_console_widget(message):
        MAX_LOG_LINES = 500
        console_widget.controls.append(
            ft.Text(
                message.rstrip(),
                size=12,
                color=ft.colors.GREEN,
            )
        )

        # удаляем старые логи
        if len(console_widget.controls) > MAX_LOG_LINES:
            console_widget.controls.pop(0)

        page.update()

    def telegram_log_test(e):
        """Тестирование отправки уведомлений"""
        logger.info("Проверка настроек уведомлений")

        try:
            config = AvitoConfig(
                messengers=MessengersConfig(
                    tg_token=tg_token.value,
                    tg_chat_id=tg_chat_id.value.split(),
                    proxy_notifier=proxy_notifier.value,
                ),
            )

            notifier = build_notifier(config=config)
            notifier.notify(message="✅ Это тестовое сообщение")

        except Exception as err:
            logger.error(f"Ошибка при проверке Telegram: {err}")

    def vk_log_test(e):
        """Тестирование отправки уведомлений VK"""
        logger.info("Проверка настроек VK")

        try:
            config = AvitoConfig(
                messengers=MessengersConfig(
                    vk_token=vk_token.value,
                    vk_user_id=vk_user_id.value.splitlines(),
                ),
            )

            notifier = build_notifier(config=config)
            notifier.notify(message="✅ Это тестовое сообщение от парсера Avito")

        except Exception as err:
            logger.error(f"Ошибка при проверке VK: {err}")

    dlg_modal_proxy = ft.AlertDialog(
        modal=True,
        title=ft.Text("Помощь по разделу:"),
        content=ft.Container(
            content=ft.Text(PROXY_PANEL_HELP, size=14),
            width=600,
            height=600,
            padding=10
        ),
        actions=[
            ft.TextButton("Купить прокси",
                          on_click=lambda e: page.launch_url(
                              PROXY_LINK)),
            ft.TextButton("Зарегистрироваться на spfa.pro",
                          on_click=lambda e: page.launch_url(
                              SPFA_LINK)),
            ft.TextButton("Отмена", on_click=close_dlg),

        ],
        actions_alignment=ft.MainAxisAlignment.END,
        on_dismiss=lambda e: print("Modal dialog dismissed!"),
    )


    def open_dlg_modal(e):
        page.overlay.append(dlg_modal_proxy)
        dlg_modal_proxy.open = True
        page.update()

    def on_click_use_own_cookies(e):
        cookies_exist = os.path.exists("storage/own_cookies.json")

        account_login_btn.text = (
            "Cookies уже есть" if cookies_exist else
            "Войти в аккаунт (обязательно)" if use_own_account.value else
            "Войти в аккаунт (опционально)"
        )
        page.update()

    async def btn_prompt_user_login_handler(e):
        await prompt_user_login.wrapper()
        page.update()
        await asyncio.sleep(2)
        on_click_use_own_cookies(None)
        logger.info("update")


    def start_parser(e):
        nonlocal is_run
        result_proxy = check_string()
        result_own_cookies = check_own_cookies()
        if not result_proxy or not result_own_cookies:
            return
        logger.info("Старт")
        stop_event.clear()
        save_config()
        console_widget.height = 700
        start_btn.visible = False
        stop_btn.visible = True
        is_run = True
        page.update()
        while is_run and not stop_event.is_set():
            parser = run_process()
            if not is_run:
                return

            # при неудачном проходе не ждём pause_general, повторяем быстрее
            wait_secs = int(pause_general.value if pause_general.value else 300)
            if retry_on_failure.value and parser.run_failed:
                wait_secs = to_int_safe(retry_on_failure_delay.value, 30)
                logger.info(f"Парсинг не удался — повтор через {wait_secs} сек (без pause_general)")

            logger.info(f"Пауза между повторами: {wait_secs} сек")
            for _ in range(wait_secs):
                time.sleep(1)
                if not is_run:
                    logger.info("Завершено")
                    start_btn.text = "Старт"
                    start_btn.disabled = False
                    page.update()
                    return
            if one_time_start.value:
                stop_event.set()
                page.window.close()

    def stop_parser(e):
        nonlocal is_run
        stop_event.set()
        logger.debug("Стоп")
        is_run = False
        console_widget.height = 100
        stop_btn.visible = False
        start_btn.visible = True
        start_btn.text = "Останавливаюсь..."
        start_btn.disabled = True
        page.update()

    def check_own_cookies():
        if use_own_account.value and not os.path.exists("storage/own_cookies.json"):
            dlg_modal = ft.AlertDialog(
                modal=True,
                title=ft.Text("Не найден cookies"),
                content=ft.Text(NOT_FOUND_OWN_COOKIES),
                actions=[
                    ft.TextButton("Понятно", on_click=lambda e: page.close(dlg_modal)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
                on_dismiss=lambda e: print("Окно закрыто"),
            )
            page.open(dlg_modal)
            return False
        return True

    def check_string():
        if use_bypass_api.value and not (proxy.value or "").strip():
            dlg_modal = ft.AlertDialog(
                modal=True,
                title=ft.Text("Для spfa.pro требуется прокси"),
                content=ft.Text(SPFA_PROXY_REQUIRED),
                actions=[
                    ft.TextButton("Купить прокси",
                                  on_click=lambda e: page.launch_url(
                                      PROXY_LINK)),
                    ft.TextButton("Понятно", on_click=lambda e: page.close(dlg_modal)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.open(dlg_modal)
            return False
        if proxy.value and ("proxy.site" not in proxy.value or "@" not in proxy.value):
            dlg_modal = ft.AlertDialog(
                modal=True,
                title=ft.Text("Проблемы с прокси"),
                content=ft.Text(UNSUPPORT_PROXY),
                actions=[
                    ft.TextButton("Купить совместимые прокси",
                                  on_click=lambda e: page.launch_url(
                                      PROXY_LINK)),
                    ft.TextButton("Понятно", on_click=lambda e: page.close(dlg_modal)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
                on_dismiss=lambda e: print("Окно закрыто"),
            )
            page.open(dlg_modal)
            return False
        return True

    def check_api_key_exist(e):
        if parse_phone.value and not cookies_api_key.value:
            parse_phone.value = False
            dlg_modal = ft.AlertDialog(
                modal=True,
                title=ft.Text("Не заполнен api ключ"),
                content=ft.Text(NEED_TO_INSERT_API_KEY),
                actions=[
                    ft.TextButton("Зарегистрироваться на spfa",
                                  on_click=lambda e: page.launch_url(
                                      SPFA_LINK)),
                    ft.TextButton("Понятно", on_click=lambda e: page.close(dlg_modal)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
                on_dismiss=lambda e: print("Окно закрыто"),
            )
            page.open(dlg_modal)
            return False
        return True

    def run_process():
        config = load_avito_config("config.toml")
        parser = AvitoParse(config, stop_event=stop_event)
        parsing_thread = threading.Thread(target=parser.parse)
        parsing_thread.start()
        parsing_thread.join()
        parser.close()
        start_btn.disabled = False
        start_btn.text = "Старт"
        page.update()
        return parser


    def panel(title: str, content: list[ft.Control], expanded=False):
        panel_ref = ft.Ref[ft.ExpansionPanel]()

        def toggle(e):
            panel_ref.current.expanded = not panel_ref.current.expanded
            page.update()

        return ft.ExpansionPanel(
            ref=panel_ref,
            header=ft.Container(
                content=ft.ListTile(
                    title=ft.Text(title, weight=ft.FontWeight.BOLD),
                ),
                on_click=toggle,
            ),
            content=ft.Container(
                content=ft.Column(content, spacing=10),
                padding=15
            ),
            expanded=expanded
        )

    url_input = ft.TextField(
        label="Вставьте начальную ссылку или ссылки. Используйте Enter между значениями",
        multiline=True,
        min_lines=3,
        max_lines=100,
        expand=True,
        tooltip=URL_INPUT_HELP,
        text_size=12,
        height=70,

    )
    min_price = ft.TextField(label="Минимальная цена", width=300, expand=True, text_size=12, height=40,
                             tooltip=MIN_PRICE_HELP)
    max_price = ft.TextField(label="Максимальная цена", width=300, expand=True, text_size=12, height=40,
                             tooltip=MAX_PRICE_HELP)
    white_list = ft.TextField(
        label="Ключевые слова (через Enter)",
        multiline=True,
        min_lines=1,
        max_lines=50,
        width=400,
        expand=True,
        tooltip=KEYWORD_INPUT_HELP,
        text_size=12, height=60,
    )
    black_list = ft.TextField(
        label="Черный список ключевых слов (через Enter)",
        multiline=True,
        min_lines=1,
        max_lines=50,
        width=400,
        expand=True,
        tooltip=KEYWORD_BLACK_INPUT_HELP,
        text_size=12, height=60,
    )
    count_page = ft.TextField(label="Количество страниц", width=450, expand=True, tooltip=COUNT_PAGE_HELP, text_size=12,
                              height=40, )


    max_age = ft.TextField(label="Макс. возраст объявления (в сек.)", width=400, text_size=12, height=40, expand=True,
                           tooltip=MAX_AGE_HELP)

    tg_token = ft.TextField(label="Token telegram", width=400, text_size=12, height=50, expand=True,
                            tooltip=TG_TOKEN_HELP)
    tg_chat_id = ft.TextField(label="Chat id telegram. Можно несколько через Enter", width=400,
                              multiline=True, expand=True, text_size=12, height=50, tooltip=TG_CHAT_ID_HELP)
    proxy_notifier = ft.TextField(label="Прокси для tg", width=400,
                              multiline=False, expand=True, text_size=12, height=50, tooltip=PROXY_NOTIFIER_HELP)
    btn_test_tg = ft.ElevatedButton(text="Проверить tg", disabled=False, on_click=telegram_log_test, expand=True,
                                    tooltip=BTN_TEST_TG_HELP)
    vk_token = ft.TextField(label="Token VK (сообщества)", width=400, text_size=12, height=50, expand=True,
                            tooltip="Токен доступа VK API от имени сообщества")
    vk_user_id = ft.TextField(label="User ID VK. Можно несколько через Enter", width=400,
                              multiline=True, expand=True, text_size=12, height=50,
                              tooltip="ID пользователей VK для отправки сообщений")
    btn_test_vk = ft.ElevatedButton(text="Проверить VK", disabled=False, on_click=vk_log_test, expand=True,
                                    tooltip="Отправить тестовое сообщение в VK")
    proxy = ft.TextField(label="Прокси в формате username:password@mproxy.site:port", width=400, expand=True,
                         tooltip=PROXY_HELP,
                         password=True,
                         can_reveal_password=True,
                         )
    proxy_change_ip = ft.TextField(
        label="Ссылка для изменения IP, в формате https://changeip.mobileproxy.rent/?proxy_key=*** (только для мобильных прокси)", width=400,
        expand=True, tooltip=PROXY_CHANGE_IP_HELP)
    proxy_btn_panel_help = ft.FilledButton(text="Помощь (если ничего непонятно)", on_click=open_dlg_modal, expand=True,
                                       tooltip=PROXY_BTN_HELP_HELP)

    proxy_help_icon = ft.IconButton(
        icon=ft.icons.HELP_OUTLINE,
        tooltip="Cправка по прокси:\n\n"
                "• Если есть мобильный прокси — заполните оба поля\n"
                "• Если это серверный прокси — только первое поле\n"
                "• Не знаете, что это вообще такое - кликайте <Помощь> ниже\n",
        icon_size=20,
    )

    cookies_api_key = ft.TextField(
        label="API ключ сервиса обхода блокировок spfa.pro (опционально)",
        password=True,
        can_reveal_password=True,
        expand=True,
    )
    purchase_cooldown = ft.TextField(
        label="Пауза между покупками cookies (сек.)",
        value="600",
        width=250,
        text_size=12,
        height=40,
        tooltip="Минимальное время между покупками новых cookies через spfa.pro (чтобы не сжечь баланс)",
    )
    use_bypass_api = ft.Checkbox("Использовать spfa сервис", value=False)
    bypass_api_key_help_icon = ft.IconButton(
        icon=ft.icons.HELP_OUTLINE,
        tooltip="api-key:\n\n"
                "• Зарегистрируйтесь на spfa.pro, чтобы его получить\n"
                "• Данный ключ поможет в обходе блокировок\n",
        icon_size=20,
    )

    use_own_account = ft.Checkbox("Использовать свой аккаунт", value=False, on_change=on_click_use_own_cookies)

    if os.path.exists("storage/own_cookies.json"):
        btn_text = "🔐 Cookies уже есть (если нужно заменить - кликни)"
    else:
        if use_own_account.value:
            btn_text = "🔐 Войти в аккаунт (опционально)"
        else:
            btn_text = "🔐 Войти в аккаунт (обязательно)"

    account_login_btn = ft.ElevatedButton(
        text=btn_text,
        icon=ft.icons.LOGIN,
        on_click=btn_prompt_user_login_handler, expand=True,
        tooltip=PROMPT_USER_LOGIN_HELP
    )
    account_login_btn_help_icon = ft.IconButton(
        icon=ft.icons.HELP_OUTLINE,
        tooltip="Можно использовать свой аккаунт:\n\n"
                "• Такой способ будет стабильно работать\n"
                "• Есть риск блокировки этого аккаунта\n",
        icon_size=20,
    )

    geo = ft.TextField(label="Ограничение по городу", width=400, expand=True, text_size=12, height=40,
                       tooltip=GEO_HELP)
    seller_black_list = ft.TextField(
        label="Черный список продавцов (через Enter)",
        multiline=True,
        min_lines=1,
        max_lines=100,
        expand=True,
        tooltip=BLACK_LIST_OF_SELLER_HELP,
        text_size=12,
        height=50,
    )
    start_btn = ft.FilledButton(
        "Старт",
        on_click=start_parser,
        expand=True
    )

    stop_btn = ft.OutlinedButton(
        "Стоп",
        on_click=stop_parser,
        visible=False,
        style=ft.ButtonStyle(bgcolor=ft.colors.RED_400),
        expand=True
    )
    console_widget = ft.ListView(
        expand=True,
        spacing=2,
        auto_scroll=True,
    )

    buy_me_coffe_btn = ft.TextButton("Продвинуть разработку",
                                     on_click=lambda e: page.launch_url(DONAT_LINK),
                                     style=ft.ButtonStyle(color=ft.colors.GREEN_300), expand=True,
                                     tooltip=BUY_ME_COFFE_BTN_HELP)
    report_issue_btn = ft.TextButton("Сообщить о проблеме", on_click=lambda e: page.launch_url(
        "https://github.com/Duff89/parser_avito/issues"), style=ft.ButtonStyle(color=ft.colors.GREY), expand=True,
                                     tooltip=REPORT_ISSUE_BTN_HELP)
    ignore_ads_in_reserv = ft.Checkbox(label="Игнор-ть резервы", value=True, tooltip=IGNORE_RESERV_HELP)
    ignore_promote_ads = ft.Checkbox(label="Игнор-ть продвинутые", value=False)
    one_time_start = ft.Checkbox(label="Выключить после завершения работы", value=False, tooltip=ONE_TIME_START_HELP)
    one_file_for_link = ft.Checkbox(label="Отдельный файл для каждой ссылки", value=False,
                                    tooltip=ONE_FILE_FOR_LINK_HELP)
    parse_views = ft.Checkbox(label="Парсить просмотры", value=False,
                                    tooltip=PARSE_VIEWS_HELP)
    parse_phone = ft.Checkbox(label="Парсить телефоны", value=False, on_change=check_api_key_exist,
                              tooltip=PARSE_PHONE_HELP)

    save_xlsx = ft.Checkbox(label="Сохранять в Excel", value=True,
                              tooltip=SAVE_XLSX_HELP)

    # Паузы и повторы
    pause_general = ft.TextField(label="Пауза в секундах между повторами", width=400, expand=True, text_size=12,
                                 height=40, tooltip=PAUSE_GENERAL_HELP)
    pause_between_links = ft.TextField(label="Пауза в секундах между каждой ссылкой", width=400, text_size=12,
                                       height=40, expand=True, tooltip=PAUSE_BETWEEN_LINKS_HELP)
    max_count_of_retry = ft.TextField(label="Макс. кол-во повторов", width=300, text_size=12, height=40, expand=True,
                                      tooltip=MAX_COUNT_OF_RETRY_HELP)
    retry_delay = ft.TextField(label="Пауза между неудачными повторами", width=300, text_size=12, height=40, expand=True,
                                      tooltip=RETRY_DELAY_HELP)
    timeout = ft.TextField(label="Таймаут для запросов", width=300, text_size=12, height=40, expand=True,
                                      tooltip=TIMEOUT_HELP)
    block_threshold = ft.TextField(label="Попыток перед разблокировкой", width=300, text_size=12, height=40, expand=True,
                                      tooltip=BLOCK_THRESHOLD_HELP)

    retry_on_failure = ft.Checkbox("Быстрый повтор при неудачном проходе", value=True,
                                   tooltip="Если парсинг завершился ошибками — не ждать pause_general, а повторить раньше")
    retry_on_failure_delay = ft.TextField(label="Пауза перед быстрым повтором (сек)", value="30", width=250,
                                          text_size=12, height=40,
                                          tooltip="Сколько ждать перед повторным запуском, если проход не удался")

    # Полное описание объявлений
    parse_full_description = ft.Checkbox("Открывать страницы и брать ПОЛНОЕ описание", value=False,
                                         tooltip="Дополнительно открывать каждое объявление для полного описания "
                                                 "(в выдаче API описание обрезано ~250 символов)")

    # Camoufox (реальный браузер для запросов к поиску)
    use_camoufox = ft.Checkbox("Поиск через Camoufox (антидетект-браузер)", value=False,
                               tooltip="Запросы к поисковой выдаче Avito через Camoufox "
                                       "(реальный браузер с десктопным отпечатком) вместо curl_cffi")
    camoufox_os = ft.Dropdown(label="ОС отпечатка", value="windows", width=180, text_size=12, height=40,
                              options=[ft.dropdown.Option("windows"), ft.dropdown.Option("macos"),
                                       ft.dropdown.Option("linux")])
    camoufox_headless = ft.Checkbox("Без окна (headless)", value=True)
    camoufox_humanize = ft.Checkbox("Человеческие движения", value=True)
    camoufox_geoip = ft.Checkbox("Гео под IP прокси", value=True)

    # ADB-прокси (microsocks на телефоне)
    use_adb_proxy = ft.Checkbox("ADB-прокси (microsocks на телефоне)", value=False,
                                tooltip="Трафик через телефон: http -> adb forward -> microsocks -> мобильная сеть")
    adb_device_serial = ft.TextField(label="Серийник устройства (необязательно)", width=250, text_size=12, height=40)
    adb_local_port = ft.TextField(label="Локальный порт", value="1080", width=120, text_size=12, height=40)
    adb_remote_port = ft.TextField(label="Порт microsocks", value="1080", width=120, text_size=12, height=40)
    adb_rotate_ip = ft.Checkbox("Смена IP (airplane mode)", value=True)
    adb_proxy_login = ft.TextField(label="Логин HTTP", value="", width=150, text_size=12, height=40)
    adb_proxy_password = ft.TextField(label="Пароль HTTP", value="", password=True,
                                      can_reveal_password=True, width=150, text_size=12, height=40)
    adb_proxy_server = ft.TextField(label="Адрес для SPFA (host:port)", value="", width=220, text_size=12, height=40,
                                    tooltip="Какой адрес прокси передавать в тело SPFA. Пусто = 127.0.0.1:{adb_local_port}")


    accordion = ft.ExpansionPanelList(
        expand_icon_color=ft.colors.GREEN_300,
        elevation=2,
        divider_color=ft.colors.GREY_700,
        controls=[
            panel(
                "🔴 Основные параметры",
                [
                    url_input,
                    ft.Row([min_price, max_price]),
                    count_page,
                ],
                expanded=True
            ),

            panel(
                "🟡 Фильтрация",
                [
                    ft.Row([white_list, black_list]),
                    seller_black_list,
                    ft.Row([geo,max_age]),
                    ft.Row([ignore_ads_in_reserv, ignore_promote_ads]),
                ]
            ),

            panel(
                "📨 Уведомления",
                [
                    ft.Text("Telegram", weight=ft.FontWeight.BOLD),
                    ft.Row([tg_token, tg_chat_id]),
                    ft.Row([proxy_notifier, ]),
                    ft.Row([btn_test_tg]),

                    ft.Divider(),

                    ft.Text("VK", weight=ft.FontWeight.BOLD),
                    ft.Row([vk_token, vk_user_id]),
                    btn_test_vk
                ]
            ),

            panel(
                "🌐 Прокси и обход блокировок",
                [
                    ft.Container(
                        content=ft.Column([
                            # Карточка 1: Сторонний сервис
                            ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        ft.Icon(ft.icons.CLOUD, color=ft.colors.BLUE_400),
                                        ft.Text("Сторонний сервис (spfa.pro)", size=14, weight=ft.FontWeight.W_500),
                                    ]),
                                    ft.Container(
                                        content=ft.Column([
                                            ft.Row([use_bypass_api, cookies_api_key, bypass_api_key_help_icon]),
                                            purchase_cooldown,
                                        ]),
                                        margin=ft.margin.only(left=25, top=5),
                                    ),
                                ]),
                                padding=10,
                                border=ft.border.all(1, ft.colors.GREY_700),
                                border_radius=8,
                                margin=ft.margin.only(bottom=8),
                                ink=True,
                            ),

                            # Карточка 2: Мобильные прокси
                            ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        ft.Icon(ft.icons.PHONE_ANDROID, color=ft.colors.GREEN_400),
                                        ft.Text("Мобильные/серверные прокси", size=14, weight=ft.FontWeight.W_500),
                                    ]),
                                    ft.Container(
                                        content=ft.Column([
                                            ft.Row([proxy, proxy_change_ip, proxy_help_icon]),
                                        ]),
                                        margin=ft.margin.only(left=25, top=5),
                                    ),
                                ]),
                                padding=10,
                                border=ft.border.all(1, ft.colors.GREY_700),
                                border_radius=8,
                                margin=ft.margin.only(bottom=8),
                                ink=True,
                            ),

                            # Карточка 3: Свой аккаунт
                            ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        ft.Icon(ft.icons.PERSON, color=ft.colors.PURPLE_400),
                                        ft.Text("Свой аккаунт", size=14, weight=ft.FontWeight.W_500),
                                    ]),
                                    ft.Container(
                                        content=ft.Row(
                                            [use_own_account, account_login_btn, account_login_btn_help_icon]),
                                        margin=ft.margin.only(left=25, top=5),
                                    ),
                                ]),
                                padding=10,
                                border=ft.border.all(1, ft.colors.GREY_700),
                                border_radius=8,
                                margin=ft.margin.only(bottom=8),
                                ink=True,
                            ),

                            # Карточка 4: Camoufox + ADB-прокси
                            ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        ft.Icon(ft.icons.SHIELD, color=ft.colors.ORANGE_400),
                                        ft.Text("Camoufox + ADB-прокси", size=14, weight=ft.FontWeight.W_500),
                                    ]),
                                    ft.Container(
                                        content=ft.Column([
                                            use_camoufox,
                                            ft.Row([camoufox_os, camoufox_headless, camoufox_humanize, camoufox_geoip]),
                                            ft.Divider(),
                                            use_adb_proxy,
                                            ft.Row([adb_local_port, adb_remote_port, adb_rotate_ip]),
                                            ft.Row([adb_proxy_login, adb_proxy_password]),
                                            adb_proxy_server,
                                            adb_device_serial,
                                        ]),
                                        margin=ft.margin.only(left=25, top=5),
                                    ),
                                ]),
                                padding=10,
                                border=ft.border.all(1, ft.colors.GREY_700),
                                border_radius=8,
                                margin=ft.margin.only(bottom=8),
                                ink=True,
                            ),

                            # Кнопка помощи
                            ft.Container(
                                content=ft.Row(
                                    [proxy_btn_panel_help],
                                    alignment=ft.MainAxisAlignment.CENTER,
                                ),
                                margin=ft.margin.only(top=5),
                            ),
                        ]),
                        padding=5,
                    )
                ]
            ),

            panel(
                "⚙️ Поведение парсера",
                [
                    ft.Row([pause_general, pause_between_links, block_threshold]),
                    ft.Row([max_count_of_retry, retry_delay, timeout]),
                    ft.Row([one_time_start, one_file_for_link]),
                    ft.Row([retry_on_failure, retry_on_failure_delay]),
                    ft.Row([parse_views,
                            #parse_phone,
                            save_xlsx]),
                    parse_full_description,
                ]
            ),

            panel(
                "▶️ Запуск",
                [
                    console_widget,
                    start_btn,
                    stop_btn,
                ]
            ),
        ]
    )

    use_webdriver = ft.Checkbox(label="Использовать браузер", value=True,
                            tooltip=USE_WEBDRIVER_HELP)


    other_btn = ft.Row(
        [buy_me_coffe_btn, report_issue_btn],
        alignment=ft.MainAxisAlignment.CENTER
    )

    def start_page():
        page.add(
            ft.Column(
                [
                    other_btn,
                    accordion,
                ],
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=20
            )
        )

    set_up()
    start_page()
    logger_console_init()


ft.app(
    target=main,
    assets_dir="assets",
)
