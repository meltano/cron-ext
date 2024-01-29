"""Base implementation of a cron entry store."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Iterable


class EntryStore(metaclass=ABCMeta):
    """Abstract base class for cron entry stores."""

    @classmethod  # type: ignore
    @property
    @abstractmethod
    def is_managed(cls) -> bool:
        """Whether the store manages its entries past inital assignment."""
        ...

    @property
    @abstractmethod
    def entries(self) -> tuple[str, ...]:
        """The stored cron entries."""
        ...

    @entries.setter
    @abstractmethod
    def entries(self, new_entries: Iterable[str]) -> None: ...
