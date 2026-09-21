import tomllib
from dataclasses import fields
from pathlib import Path

import tomli_w

from dto import (
    AvitoConfig,
    LinkConfig,
    CamoufoxConfig,
    SshConfig,
    OwnMobileProxyConfig,
    ExternalMobileProxyConfig,
    MessengersConfig,
    ServerConfig,
)


# Переименование старых полей -> новые
_FIELD_RENAMES = {
    "keys_word_white_list": "white_list",
    "keys_word_black_list": "black_list",
    "parse_full_description": "open_full_ad",
}


def _rename_keys(raw: dict, renames: dict) -> dict:
    """Возвращает копию dict с переименованными ключами (старый -> новый)."""
    result = dict(raw)
    for old, new in renames.items():
        if old in result and new not in result:
            result[new] = result.pop(old)
    return result


def _coerce(dataclass_type, raw):
    """Преобразует сырой dict в экземпляр dataclass (только известные поля)."""
    if isinstance(raw, dataclass_type):
        return raw
    if not isinstance(raw, dict):
        raw = {}
    allowed = {f.name for f in fields(dataclass_type)}
    return dataclass_type(**{k: v for k, v in raw.items() if k in allowed})


def _coerce_own_mobile_proxy(raw) -> OwnMobileProxyConfig:
    """Приводит сырой dict своего мобильного прокси к OwnMobileProxyConfig (с вложенным ssh)."""
    if isinstance(raw, OwnMobileProxyConfig):
        return raw
    if not isinstance(raw, dict):
        raw = {}
    allowed = {f.name for f in fields(OwnMobileProxyConfig) if f.name != "ssh"}
    config = OwnMobileProxyConfig(**{k: v for k, v in raw.items() if k in allowed})
    config.ssh = _coerce(SshConfig, raw.get("ssh"))
    return config


def _coerce_external_mobile_proxy(raw) -> ExternalMobileProxyConfig:
    """Приводит сырой dict внешнего мобильного прокси к ExternalMobileProxyConfig.

    Старое одиночное поле `change_url` подмешивается в начало `change_urls`.
    """
    if isinstance(raw, ExternalMobileProxyConfig):
        return raw
    if not isinstance(raw, dict):
        raw = {}
    allowed = {f.name for f in fields(ExternalMobileProxyConfig)}
    values = {k: v for k, v in raw.items() if k in allowed}
    urls = list(values.get("change_urls") or [])
    legacy = raw.get("change_url")
    if legacy and legacy not in urls:
        urls.insert(0, legacy)
    values["change_urls"] = urls
    return ExternalMobileProxyConfig(**values)


def _parse_links(raw) -> dict:
    """Приводит сырую мапу links (dict) к {url: LinkConfig}."""
    result = {}
    for url, cfg in (raw or {}).items():
        if isinstance(cfg, LinkConfig):
            result[url] = cfg
        elif isinstance(cfg, dict):
            result[url] = _coerce(LinkConfig, _rename_keys(cfg, _FIELD_RENAMES))
        else:
            result[url] = LinkConfig()
    return result


def _migrate_legacy(avito: dict, flat: dict) -> None:
    """Заполняет вложенные блоки из старых плоских полей, если блоки не заданы."""
    if not avito.get("camoufox"):
        flat["camoufox"] = CamoufoxConfig(
            use=avito.get("use_camoufox", False),
            os=avito.get("camoufox_os", "windows"),
            headless=avito.get("camoufox_headless", True),
            humanize=avito.get("camoufox_humanize", True),
            geoip=avito.get("camoufox_geoip", True),
        )

    if not avito.get("own_mobile_proxy") and not avito.get("adb_proxy"):
        own = OwnMobileProxyConfig(
            use=avito.get("use_adb_proxy", False),
            port=avito.get("own_mobile_proxy_port", avito.get("adb_remote_port", 8888)),
            rotate_ip=avito.get("adb_rotate_ip", True),
            login=avito.get("adb_proxy_login", ""),
            password=avito.get("adb_proxy_password", ""),
            server=avito.get("adb_proxy_server", ""),
        )
        own.ssh = _coerce(
            SshConfig,
            avito.get("ssh") or {
                "host": avito.get("ssh_host", ""),
                "port": avito.get("ssh_port", 8022),
                "user": avito.get("ssh_user", ""),
                "password": avito.get("ssh_password", ""),
            },
        )
        flat["own_mobile_proxy"] = own

    if not avito.get("external_mobile_proxy") and not avito.get("mobile_proxy"):
        flat["external_mobile_proxy"] = _coerce_external_mobile_proxy({
            "proxy_string": avito.get("proxy_string"),
            "change_urls": avito.get("proxy_change_urls", []),
            "change_url": avito.get("proxy_change_url"),
        })

    if not avito.get("messengers"):
        flat["messengers"] = MessengersConfig(
            tg_token=avito.get("tg_token"),
            tg_chat_id=avito.get("tg_chat_id") or [],
            vk_token=avito.get("vk_token"),
            vk_user_id=avito.get("vk_user_id") or [],
            proxy_notifier=avito.get("proxy_notifier"),
        )

    if not avito.get("server"):
        flat["server"] = ServerConfig(
            server_port=avito.get("server_port", 8000),
            web_server_port=avito.get("web_server_port", 3000),
            admin_password=avito.get("admin_password", ""),
            server_host=avito.get("server_host", "127.0.0.1"),
            cors_origins=avito.get("cors_origins", []),
        )


def load_avito_config(path: str = "config.toml") -> AvitoConfig:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    avito = data["avito"]

    # переименование старых полей
    avito = _rename_keys(avito, _FIELD_RENAMES)

    allowed = {field.name for field in fields(AvitoConfig)}
    flat = {key: value for key, value in avito.items() if key in allowed}

    # миграция старого формата: urls (список) -> links (мапа url -> {})
    if not flat.get("links") and avito.get("urls"):
        flat["links"] = {url: {} for url in avito["urls"]}

    flat["links"] = _parse_links(flat.get("links", {}))
    flat["camoufox"] = _coerce(CamoufoxConfig, avito.get("camoufox"))
    flat["own_mobile_proxy"] = _coerce_own_mobile_proxy(
        avito.get("own_mobile_proxy") or avito.get("adb_proxy")
    )
    flat["external_mobile_proxy"] = _coerce_external_mobile_proxy(
        avito.get("external_mobile_proxy") or avito.get("mobile_proxy")
    )
    flat["messengers"] = _coerce(MessengersConfig, avito.get("messengers"))
    flat["server"] = _coerce(ServerConfig, avito.get("server"))

    _migrate_legacy(avito, flat)

    return AvitoConfig(**flat)


def _toml_inline(value) -> str:
    """Компактное TOML-представление значения (для inline-объектов links)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_inline(v) for v in value) + "]"
    raise TypeError(f"Неподдерживаемый тип для TOML: {type(value)!r}")


def _format_links(links: dict) -> str:
    """Формирует секцию [avito.links] с inline-объектами по каждой ссылке."""
    lines = ["[avito.links]"]
    for url, cfg in (links or {}).items():
        cfg = cfg or {}
        parts = []

        def add(key, value):
            parts.append(f"{key} = {_toml_inline(value)}")

        for key in ("min_price", "max_price"):
            value = cfg.get(key)
            if value is not None:
                add(key, value)
        for key in ("white_list", "black_list"):
            value = cfg.get(key)
            if value:
                add(key, value)
        for key in ("geo", "start_date"):
            value = cfg.get(key)
            if value:
                add(key, value)
        if cfg.get("ignore_reserv") is False:
            add("ignore_reserv", False)
        if cfg.get("ignore_promotion") is True:
            add("ignore_promotion", True)

        lines.append(f'{_toml_inline(url)} = {{ {", ".join(parts)} }}')
    return "\n".join(lines)


def save_avito_config(config: dict):
    avito = dict(config.get("avito", {}))
    links = avito.pop("links", None)
    body = tomli_w.dumps({"avito": avito})
    if links:
        body = body.rstrip("\n") + "\n\n" + _format_links(links) + "\n"
    Path("config.toml").write_text(body, encoding="utf-8")
