from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class UnblockState:
    deadline: float  # monotonic clock, not wall time
    check_interval: float


class CookiesProvider(ABC):

    def poll_unblock(self, timeout: float) -> bool:
        """Проверить готовность cookies у провайдера, без запросов к Avito."""
        raise NotImplementedError

    def get_unblock_state(self) -> UnblockState | None:
        return None

    def expire_unblock(self) -> None:
        """Завершить локальное ожидание после истечения срока."""

    @abstractmethod
    def get(self) -> Dict[str, str]:
        pass

    def update(self, response) -> None:
        """
        Обновить cookies после запроса.
        По умолчанию — ничего не делать.
        """
        pass

    def get_user_agent(self) -> str | None:
        """Return the user agent associated with the current cookies, if any."""
        return None

    def get_fingerprint(self) -> dict | None:
        """Return the HTTP client profile associated with the current cookies."""
        return None

    @abstractmethod
    def handle_block(self):
        """
        Что делать, если cookies заблокированы
        """
        pass

    def handle_ip_change(self):
        """
        Вызывается после смены IP. По умолчанию — ничего (SPFA сам перевыпускает).
        own_cookies переопределяет: полностью перевыпускает куки под новый IP.
        """
        pass
