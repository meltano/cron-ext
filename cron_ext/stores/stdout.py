"""Cron entry store that "store" by printing entries to stdout."""

from __future__ import annotations

from typing import Iterable

from cron_ext.stores.base import EntryStore


class StdoutEntryStore(EntryStore):
    """Cron entry store which emits the entries to stdout for custom handling."""

    is_managed = False

    @property
    def entries(self) -> tuple[str, ...]:
        """
        When read, returns an empty tuple, because the stdout cron entry store
        does not manage any cron entries.

        When written to, creates and prints new cron entries to stdout.
        """  # noqa
        return ()

    @entries.setter
    def entries(self, new_entries: Iterable[str]) -> None:
        print(*new_entries, sep="\n", flush=True)
