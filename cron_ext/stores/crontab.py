"""Cron entry store that stores entries using crontab."""

from __future__ import annotations

import os
import re
import sys
from typing import Iterable

if sys.version_info >= (3, 8):
    from functools import cached_property
else:
    from cached_property import cached_property

from cron_ext.entry import comment_pattern, entry_pattern
from cron_ext.stores.base import EntryStore
from cron_ext.subprocess import run_subprocess


class CrontabEntryStore(EntryStore):
    """Cron entry store backed by crontab."""

    is_managed = True

    def __init__(self) -> None:
        """Initialize the crontab entry store."""
        super().__init__()
        self.meltano_project_id = os.environ["MELTANO_PROJECT_ID"]

    @property
    def entries(self) -> tuple[str, ...]:
        """Entries from the installed crontab found within the Meltano section."""
        # noqa: DAR201
        lines = self.crontab.splitlines()
        try:
            a, b = self._find_meltano_section_indices(lines)
        except ValueError:
            return ()
        return tuple(line for line in lines[a:b] if not self._ignore_entry(line))

    @entries.setter
    def entries(self, new_entries: Iterable[str]) -> None:
        distinct_new_entries = tuple(self._unique_entries(new_entries))
        lines = self.crontab.splitlines()
        try:
            a, b = self._find_meltano_section_indices(lines)
        except ValueError:
            # create new Meltano section at the bottom of the crontab
            section_template = (
                "# ----- {} MELTANO CRONTAB SECTION "
                f"({self.meltano_project_id}) -----"
            )
            new_lines = (
                *lines,
                "",
                section_template.format("BEGIN"),
                *distinct_new_entries,
                section_template.format("END"),
                "",
            )
        else:
            # update the existing Meltano section
            new_lines = (
                *lines[:a],
                *distinct_new_entries,
                *lines[b:],
            )
        self.crontab = "\n".join(new_lines)

    @cached_property
    def _crontab(self) -> str:
        proc = run_subprocess(
            ("crontab", "-l"),
            "Unable to list crontab entries.",
            exit_on_nonzero_returncode=False,
        )
        return "" if proc.returncode else proc.stdout

    @property
    def crontab(self) -> str:
        """Content from the installed crontab."""
        # noqa: DAR201
        return self._crontab

    @crontab.setter
    def crontab(self, content: str) -> None:
        if not content.endswith("\n"):
            content += "\n"
        run_subprocess(
            ("crontab", "-"),
            "Unable to install new crontab.",
            input=content,
        )
        self._crontab = content

    def _index_of_match(self, pattern: str, lines: Iterable[str]) -> int:
        compiled_pattern = re.compile(pattern)
        for i, line in enumerate(lines):
            match = compiled_pattern.fullmatch(line)
            if match and match["id"] == self.meltano_project_id:
                return i
        raise ValueError(f"Pattern {pattern!r} does not match any line.")

    def _find_meltano_section_indices(self, lines: Iterable[str]) -> tuple[int, int]:
        template = r"^\s*#\s*-+\s*{} MELTANO CRONTAB SECTION \((?P<id>.*?)\)\s*-+\s*$"
        lines = tuple(lines)
        return (
            self._index_of_match(template.format("BEGIN"), lines) + 1,
            -self._index_of_match(template.format("END"), reversed(lines)) - 1,
        )

    @classmethod
    def _ignore_entry(cls, entry: str) -> bool:
        # Preserve/skip full-line comments and blank lines
        return bool(comment_pattern.fullmatch(entry)) or not entry.strip()

    @classmethod
    def _unique_entries(cls, entries: Iterable[str]) -> Iterable[str]:
        seen = set()
        for entry in entries:
            if cls._ignore_entry(entry):
                yield entry
            else:
                match = entry_pattern.fullmatch(entry)
                if not match:
                    continue
                elif match["name"] not in seen:
                    seen.add(match["name"])
                    yield entry
