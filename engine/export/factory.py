from pathlib import Path

from domain.config import AvitoConfig

from engine.export.base import ResultStorage
from engine.export.excel import ExcelStorage


def build_result_storage(config: AvitoConfig) -> ResultStorage:
    """Всегда сохраняет результаты в единый Excel-файл (result/avito.xlsx)."""
    base_dir = Path(config.output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    return ExcelStorage(base_dir / "avito.xlsx")
