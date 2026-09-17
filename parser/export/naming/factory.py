from dto import AvitoConfig

from parser.export.naming.single_file import SingleFileNamingStrategy


def build_naming_strategy(config: AvitoConfig):
    """Строит стратегию именования результатов на основе конфига.

    Результаты всегда сохраняются в один файл (result.xlsx).
    """
    return SingleFileNamingStrategy(path=str(config.output_dir / "result.xlsx"))

