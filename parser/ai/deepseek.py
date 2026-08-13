"""
Оценка объявлений через DeepSeek (соотношение цена/производительность).

DeepSeek используется как «база» для анализа комплектующих по заголовку
и ПОЛНОМУ описанию объявления. Модель возвращает оценку 0-100 + краткое
обоснование. Для калибровки шкалы в промпт подмешиваются лучшие объявления
из истории предыдущих оценок (storage/ai_history.json).
"""
import json
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from loguru import logger

from models import Item

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
MAX_HISTORY = 2000

SYSTEM_PROMPT = (
    "Ты — эксперт по оценке объявлений о продаже компьютеров и комплектующих. "
    "Твоя задача — оценивать соотношение ЦЕНА/ПРОИЗВОДИТЕЛЬНОСТЬ каждого объявления "
    "по шкале от 0 до 100 (0 — очень плохо / явная переплата, 100 — отличная покупка). "
    "Учитывай: цену, конфигурацию, поколение компонентов (CPU/GPU/RAM/SSD), бренд, "
    "состояние, комплектность (монитор, периферия, лицензия ОС), адекватность цены рынку. "
    "Дополнительно извлеки из описания характеристики ПК (только то, что явно указано; "
    "чего нет — оставь пустой строкой): cpu, socket, ram (стандарт DDR), storage (SSD/HDD/NVMe), gpu. "
    "Отвечай строго одним JSON-объектом без пояснений: "
    "{\"score\": <0-100>, \"reason\": \"<краткое обоснование на русском, 1-2 предложения>\", "
    "\"specs\": {\"cpu\": \"...\", \"socket\": \"...\", \"ram\": \"...\", \"storage\": \"...\", \"gpu\": \"...\"}}"
)


class DeepSeekEvaluator:
    """Оценивает объявления через DeepSeek и хранит историю оценок."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        history_path: str = "storage/ai_history.json",
        history_size: int = 10,
        timeout: int = 60,
    ):
        self.api_key = api_key
        self.model = model
        self.history_path = Path(history_path)
        self.history_size = history_size
        self.timeout = timeout
        self._history = self._load_history()

    # ------------------------------------------------------------------ #
    # История оценок (для калибровки шкалы)
    # ------------------------------------------------------------------ #
    def _load_history(self) -> List[dict]:
        if not self.history_path.exists():
            return []
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save_history(self) -> None:
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            self.history_path.write_text(
                json.dumps(self._history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as err:
            logger.warning(f"[DeepSeek] Не удалось сохранить историю оценок: {err}")

    def _top_history(self) -> List[dict]:
        """Лучшие объявления из истории — эталон для калибровки шкалы."""
        return sorted(
            self._history, key=lambda h: h.get("score", 0), reverse=True
        )[: self.history_size]

    def add_to_history(self, ad: Item) -> None:
        if not ad.id or not ad.ai_score:
            return
        self._history.append(
            {
                "id": str(ad.id),
                "title": ad.title or "",
                "description": (ad.description or "")[:500],
                "price": ad.priceDetailed.value if ad.priceDetailed else None,
                "score": ad.ai_score,
                "reason": ad.ai_reason,
                "rated_at": time.time(),
            }
        )
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]
        self._save_history()

    # ------------------------------------------------------------------ #
    # Вызов API DeepSeek (совместим с OpenAI)
    # ------------------------------------------------------------------ #
    def _call(self, messages: list) -> str:
        resp = httpx.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 300,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _parse_score(text: str) -> Tuple[Optional[float], Optional[str], Optional[dict]]:
        """Достаёт score/reason/specs из ответа модели (JSON в ``` или голый)."""
        text = text.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None, None, None
        try:
            data = json.loads(match.group(0))
        except ValueError:
            return None, None, None
        try:
            score = float(data.get("score"))
        except (TypeError, ValueError):
            score = None
        specs = data.get("specs") if isinstance(data.get("specs"), dict) else None
        return score, data.get("reason"), specs

    def _build_messages(self, ad: Item) -> list:
        history = self._top_history()
        ref_block = ""
        if history:
            lines = [
                f"- \"{h.get('title', '')}\" | цена: {h.get('price', '?')}₽ "
                f"| оценка: {h.get('score', 0)} | причина: {h.get('reason', '')}"
                for h in history
            ]
            ref_block = (
                "Вот примеры ранее оценённых объявлений (используй их как калибровку "
                "шкалы — новая оценка должна быть сопоставима с ними):\n"
                + "\n".join(lines)
                + "\n\n"
            )

        price = ad.priceDetailed.value if ad.priceDetailed else "?"
        user_prompt = (
            f"{ref_block}Оцени соотношение цена/производительность этого объявления.\n\n"
            f"Заголовок: {ad.title or ''}\n"
            f"Описание: {ad.description or ''}\n"
            f"Цена: {price} ₽\n\n"
            'Верни строго JSON: {"score": <0-100>, "reason": "<краткое обоснование на русском>", '
            '"specs": {"cpu": "...", "socket": "...", "ram": "...", "storage": "...", "gpu": "..."}}'
        )
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    def evaluate(self, ad: Item) -> None:
        """Оценивает одно объявление, заполняет ad.ai_score и ad.ai_reason."""
        try:
            text = self._call(self._build_messages(ad))
            score, reason, specs = self._parse_score(text)
            if score is None:
                logger.warning(
                    f"[DeepSeek] Не удалось распарсить ответ для {ad.id}: {text[:200]!r}"
                )
                return
            ad.ai_score = round(score, 1)
            ad.ai_reason = (reason or "")[:500]
            ad.ai_specs = self._clean_specs(specs)
            logger.info(
                f"[DeepSeek] id={ad.id} оценка={ad.ai_score} ({ad.ai_reason})"
            )
        except Exception as err:
            logger.warning(f"[DeepSeek] Ошибка оценки объявления {ad.id}: {err}")

    # ------------------------------------------------------------------ #
    # Пакетная оценка (несколько объявлений за один запрос к API)
    # ------------------------------------------------------------------ #
    def _build_batch_messages(self, ads: list) -> list:
        history = self._top_history()
        ref_block = ""
        if history:
            lines = [
                f"- \"{h.get('title', '')}\" | цена: {h.get('price', '?')}₽ "
                f"| оценка: {h.get('score', 0)} | причина: {h.get('reason', '')}"
                for h in history
            ]
            ref_block = (
                "Вот примеры ранее оценённых объявлений (используй их как калибровку "
                "шкалы — новые оценки должны быть сопоставимы с ними):\n"
                + "\n".join(lines)
                + "\n\n"
            )

        ads_block = []
        for i, ad in enumerate(ads, start=1):
            price = ad.priceDetailed.value if ad.priceDetailed else "?"
            ads_block.append(
                f"{i}) Заголовок: {ad.title or ''}\n"
                f"   Описание: {ad.description or ''}\n"
                f"   Цена: {price} ₽"
            )

        user_prompt = (
            f"{ref_block}Оцени соотношение цена/производительность для КАЖДОГО "
            f"объявления из списка ниже.\n\n"
            + "\n\n".join(ads_block)
            + f"\n\nВерни строго JSON-массив из {len(ads)} элементов в том же порядке, "
            "без пояснений:\n"
            '[{"score": <0-100>, "reason": "<краткое обоснование на русском>", '
            '"specs": {"cpu": "...", "socket": "...", "ram": "...", "storage": "...", "gpu": "..."}}, ...]'
        )
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _parse_batch(text: str, count: int):
        """Достаёт список (score, reason) из пакетного ответа модели."""
        text = text.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return None
        try:
            items = json.loads(match.group(0))
        except ValueError:
            return None
        if not isinstance(items, list):
            return None
        result = []
        for item in items[:count]:
            if not isinstance(item, dict):
                result.append((None, None, None))
                continue
            try:
                score = float(item.get("score"))
            except (TypeError, ValueError):
                score = None
            specs = item.get("specs") if isinstance(item.get("specs"), dict) else None
            result.append((score, item.get("reason"), specs))
        return result

    @staticmethod
    def _clean_specs(specs) -> Optional[dict]:
        """Оставляет только заполненные характеристики."""
        if not isinstance(specs, dict):
            return None
        cleaned = {
            k: str(v).strip()
            for k, v in specs.items()
            if v is not None and str(v).strip()
        }
        return cleaned or None

    def evaluate_batch(self, ads: list) -> None:
        """Оценивает пачку объявлений одним запросом к DeepSeek."""
        if not ads:
            return
        try:
            text = self._call(self._build_batch_messages(ads))
            parsed = self._parse_batch(text, len(ads))
            if parsed is None:
                logger.warning(
                    f"[DeepSeek] Не удалось распарсить пакетный ответ: {text[:200]!r}"
                )
                return
            for ad, (score, reason, specs) in zip(ads, parsed):
                if score is None:
                    continue
                ad.ai_score = round(score, 1)
                ad.ai_reason = (reason or "")[:500]
                ad.ai_specs = self._clean_specs(specs)
            rated = sum(1 for a in ads if a.ai_score)
            logger.info(f"[DeepSeek] Оценено {rated} из {len(ads)} объявлений")
        except Exception as err:
            logger.warning(f"[DeepSeek] Ошибка пакетной оценки: {err}")
