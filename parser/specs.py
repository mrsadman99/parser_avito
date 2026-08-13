"""
Извлечение характеристик ПК из текста объявления (заголовок + описание).

Ищет: процессор, сокет, стандарт памяти (DDR), накопитель, видеокарту.
Используется для подстановки в уведомления (Telegram/VK).
"""
import re

CPU_PATTERNS = [
    re.compile(r"\b(?:intel\s+core\s+)?i[3-9](?:\s*-?\s*\d{3,5}[a-z0-9]*)?", re.I),
    re.compile(r"\bryzen\s*(?:threadripper\s*)?[579](?:\s*\d{2,4}[a-z0-9]*)?", re.I),
]
SOCKET_PATTERNS = [
    re.compile(
        r"\b(?:socket\s*)?(?:lga\s*1[27]00|lga\s*1200|lga\s*1151|lga\s*1150|"
        r"lga\s*2011|lga\s*2066|am[45]|trx40|s?trx4|fm2\+?)\b",
        re.I,
    ),
]
DDR_PATTERNS = [
    re.compile(r"\bddr[345]\b", re.I),
]
STORAGE_PATTERNS = [
    re.compile(
        r"\b(?:ssd|hdd|nvme|m\.2|m2)\s*(?:nvme)?\s*[\d.,]+\s*(?:тб|tb|gb|гб)\b",
        re.I,
    ),
    re.compile(
        r"\b[\d.,]+\s*(?:тб|tb|gb|гб)\s*(?:ssd|hdd|nvme)\b",
        re.I,
    ),
]
GPU_PATTERNS = [
    re.compile(
        r"\b(?:rtx|gtx|rx|gt|quadro|radeon)\s*\d{3,4}(?:\s*(?:ti|super|xt|xtx))?\b",
        re.I,
    ),
    re.compile(
        r"\b(?:geforce|radeon)\s+(?:rtx|gtx|rx|gt)?\s*\d{3,4}[a-z0-9]*",
        re.I,
    ),
]

_LABELS = {
    "cpu": "CPU",
    "socket": "Сокет",
    "ram": "Память",
    "storage": "Накопитель",
    "gpu": "GPU",
}


def _find_first(patterns, text: str):
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(0).strip()
    return None


def extract_specs(text: str) -> dict:
    """Возвращает словарь характеристик ПК (пустые ключи опущены)."""
    specs = {}
    if not text:
        return specs

    cpu = _find_first(CPU_PATTERNS, text)
    if cpu:
        specs["cpu"] = cpu

    socket = _find_first(SOCKET_PATTERNS, text)
    if socket:
        specs["socket"] = socket.replace("socket ", "").strip().upper()

    ddr = _find_first(DDR_PATTERNS, text)
    if ddr:
        specs["ram"] = ddr.upper()

    storage = _find_first(STORAGE_PATTERNS, text)
    if storage:
        specs["storage"] = storage

    gpu = _find_first(GPU_PATTERNS, text)
    if gpu:
        specs["gpu"] = gpu

    return specs


def format_specs_line(specs: dict) -> str:
    """Собирает компактную строку характеристик для уведомления."""
    parts = []
    for key, label in _LABELS.items():
        if key in specs:
            parts.append(f"{label}: {specs[key]}")
    return " • ".join(parts)


def format_specs_lines(specs: dict) -> list:
    """Возвращает список строк характеристик — по одной на каждый параметр."""
    lines = []
    for key, label in _LABELS.items():
        value = (specs or {}).get(key)
        if value:
            lines.append(f"🔧 {label}: {value}")
    return lines
