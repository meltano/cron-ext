from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from contextlib import suppress
from hashlib import sha256
from pathlib import Path
from typing import Callable, Iterable
from uuid import UUID

import structlog
from cached_property import cached_property
from meltano.edk import models
from meltano.edk.extension import ExtensionBase

log = structlog.get_logger()


class Cron(ExtensionBase):
    full_line_comment_pattern = re.compile(r"^\s*#.*$")
    entry_pattern = re.compile(
        r"(?i)^.+?'(?P<path>(?:/.*)+(?P<uuid>[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})\.sh)'.*$"
    )

    def invoke(self, *args, **kwargs):
        """Invoke the underlying cli, that is being wrapped by this extension."""
        raise NotImplementedError

    @cached_property
    def meltano_project_dir(self) -> Path:
        return Path(os.environ["MELTANO_PROJECT_ROOT"]).resolve()

    @cached_property
    def cron_ext_dir(self) -> Path:
        path = self.meltano_project_dir / ".meltano" / "cron-ext"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @cached_property
    def meltano_schedule(self) -> dict[str, str]:
        # FIXME: handle non-zero exit code
        return json.loads(
            subprocess.run(
                ("meltano", "schedule", "list", "--format=json"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
        )["schedules"]

    @cached_property
    def meltano_schedule_uuids(self) -> set[UUID]:
        # Blocked by https://github.com/meltano/meltano/issues/3437#issuecomment-1240952806
        raise NotImplementedError

    @property
    def crontab(self) -> str:
        # FIXME: handle non-zero exit code
        return subprocess.run(
            ("crontab", "-l"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout

    @crontab.setter
    def crontab(self, content: str) -> None:
        if not content.endswith("\n"):
            content += "\n"
        subprocess.run(
            ("crontab", "-"),
            input=content,
            text=True,
        )

    @staticmethod
    def _index_of_match(pattern: str, lines: Iterable[str]):
        compiled_pattern = re.compile(pattern)
        for i, line in enumerate(lines):
            if compiled_pattern.fullmatch(line):
                return i
        raise ValueError(f"Pattern {pattern!r} does not match any line.")

    def _find_meltano_section_indices(self, lines: Iterable[str]) -> tuple[int, int]:
        template = r"^\s*#\s*-+\s*{} MELTANO CRONTAB SECTION\s*-+\s*$"
        lines = tuple(lines)
        return (
            self._index_of_match(template.format("BEGIN"), lines) + 1,
            -self._index_of_match(template.format("END"), reversed(lines)) - 1,
        )

    @classmethod
    def _unique_entries(cls, *entries: str) -> Iterable[str]:
        seen = set()
        for entry in entries:
            if cls.full_line_comment_pattern.fullmatch(entry):
                yield entry  # Preserve full-line comments
            else:
                match = cls.entry_pattern.fullmatch(entry)
                if not match:
                    continue
                elif match.group("uuid").lower() not in seen:
                    seen.add(match.group("uuid").lower())
                    yield entry

    @property
    def entries(self) -> tuple[str]:
        lines = self.crontab.splitlines()
        try:
            a, b = self._find_meltano_section_indices(lines)
        except ValueError:
            return ()
        return tuple(
            line
            for line in lines[a:b]
            if not self.full_line_comment_pattern.fullmatch(line)
        )

    @entries.setter
    def entries(self, new_entries: Iterable[str]) -> None:
        lines = self.crontab.splitlines()
        try:
            a, b = self._find_meltano_section_indices(lines)
        except ValueError:
            # create new Meltano section at the bottom of the crontab
            new_lines = (
                *lines,
                "",
                "# ----- BEGIN MELTANO CRONTAB SECTION -----",
                *new_entries,
                "# ------ END MELTANO CRONTAB SECTION ------",
                "",
            )
        else:
            # update the existing Meltano section
            new_lines = (
                *lines[:a],
                *new_entries,
                *lines[b:],
            )
        self.crontab = "\n".join(new_lines)

    @staticmethod
    def _canonize_schedule_element(element: dict[str, str] | Path | str) -> str:
        if isinstance(element, str):
            return element
        if isinstance(element, dict):
            return " ".join((y for x in sorted(element.items()) for y in x))
        if isinstance(element, Path):
            return element.resolve().as_posix()
        raise TypeError

    @classmethod
    # Will be impacted by https://github.com/meltano/meltano/issues/3437#issuecomment-1240952806
    def _identify_schedule(cls, *elements: dict[str, str] | Path | str) -> UUID:
        canonical_elements = (cls._canonize_schedule_element(x) for x in elements)
        return UUID(sha256("\n".join(canonical_elements).encode()).hexdigest()[::2])

    def _new_entries(self, predicate: Callable[[UUID], bool]) -> Iterable[str]:
        base_env = {"PATH": f'{os.environ["PATH"]}:$PATH'}
        if "VIRTUAL_ENV" in os.environ:
            base_env["VIRTUAL_ENV"] = os.environ["VIRTUAL_ENV"]
        for schedule in self.meltano_schedule["elt"] + self.meltano_schedule["job"]:
            interval = (
                schedule["cron_interval"] if "job" in schedule else schedule["interval"]
            )
            args = " ".join(
                schedule["job"]["tasks"] if "job" in schedule else schedule["elt_args"]
            )
            cmd = "run" if "job" in schedule else "elt"
            env = {**base_env, **schedule["env"]}
            env_str = " ".join(f'{key}="{value}"' for key, value in env.items())
            schedule_uuid = self._identify_schedule(
                interval, self.meltano_project_dir, env, cmd, args
            )
            if not predicate(schedule_uuid):
                continue
            command_script = self.cron_ext_dir / f"{schedule_uuid}.sh"
            command_script.write_text(
                f"(cd '{self.meltano_project_dir}' && {env_str} "
                f"meltano {cmd} {args}) 2>&1 | /usr/bin/logger -t meltano\n"
            )
            # Make the command script executable by the user who owns it
            command_script.chmod(command_script.stat().st_mode | stat.S_IXUSR)
            yield f"{interval} '{command_script.as_posix()}'"

    def install(self, schedule_ids: list[UUID]) -> None:
        if schedule_ids:
            schedule_id_set = set(schedule_ids)
            predicate = lambda x: x in schedule_id_set
        else:
            predicate = lambda _: True
        self.entries = self._unique_entries(
            *self._new_entries(predicate), *self.entries
        )

    def uninstall(self, schedule_ids: list[UUID], uninstall_all: bool) -> None:
        prev_entries = self.entries

        # Get the predicate rule for what should be removed
        if uninstall_all:
            # XXX: This leaves behind the "begin/end Meltano section" comments
            predicate = lambda _: True
        elif schedule_ids:
            schedule_id_set = set(schedule_ids)
            predicate = lambda x: x in schedule_id_set
        else:  # Only uninstall the entries that are found in the current Meltano project:
            # Blocked by https://github.com/meltano/meltano/issues/3437#issuecomment-1240952806
            raise NotImplementedError
            predicate = lambda x: x in self.meltano_schedule_uuids

        # Update the installed entries and scripts using the chosen rule
        self.entries = (
            entry
            for entry in self.entries
            if self.entry_pattern.fullmatch(entry)
            and not predicate(UUID(self.entry_pattern.fullmatch(entry).group("uuid")))
        )
        for entry in prev_entries:
            match = self.entry_pattern.fullmatch(entry)
            if match and predicate(UUID(match.group("uuid"))):
                with suppress(FileNotFoundError):
                    Path(match.group("path")).unlink()

    def describe(self) -> models.Describe:
        # TODO: could we auto-generate all or portions of this from typer instead?
        return models.Describe(
            commands=[
                models.ExtensionCommand(name="cron", description="extension commands"),
            ]
        )
