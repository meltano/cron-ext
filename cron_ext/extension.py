from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from contextlib import suppress
from hashlib import sha256
from pathlib import Path
from typing import Callable, Iterable

import structlog
from cached_property import cached_property
from meltano.edk import models
from meltano.edk.extension import ExtensionBase

from cron_ext import APP_NAME

log = structlog.get_logger(APP_NAME)


def run_subprocess(
    args: tuple[str],
    error_message: str,
    *,
    exit_on_nonzero_returncode: bool = True,
) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        log.exception(error_message)
        sys.exit(1)
    if proc.returncode:
        if exit_on_nonzero_returncode:
            log.critical(error_message)
            sys.exit(proc.returncode)
        log.error(error_message)
    return proc


class Cron(ExtensionBase):
    full_line_comment_pattern = re.compile(r"^\s*#.*$")
    entry_pattern = re.compile(r"(?i)^.+?'(?P<path>(?:/.*)*/(?P<name>.*)\.sh)'.*$")

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
        return json.loads(
            run_subprocess(
                ("meltano", "schedule", "list", "--format=json"),
                "Unable to list Meltano schedules.",
            ).stdout
        )["schedules"]

    @cached_property
    def meltano_schedule_ids(self) -> set[str]:
        return {
            schedule["name"]
            for schedule in self.meltano_schedule["elt"] + self.meltano_schedule["job"]
        }

    @property
    def crontab(self) -> str:
        proc = run_subprocess(
            ("crontab", "-l"),
            "Unable to list crontab entries.",
            exit_on_nonzero_returncode=False,
        )
        return "" if proc.returncode else proc.stdout

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
                elif match.group("name") not in seen:
                    seen.add(match.group("name"))
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

    def _new_entries(self, predicate: Callable[[str], bool]) -> Iterable[str]:
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
            if not predicate(schedule["name"]):
                continue
            command_script = self.cron_ext_dir / f"{schedule['name']}.sh"
            command_script.write_text(
                f"(cd '{self.meltano_project_dir}' && {env_str} "
                f"meltano {cmd} {args}) 2>&1 | /usr/bin/logger -t meltano\n"
            )
            # Make the command script executable by the user who owns it
            command_script.chmod(command_script.stat().st_mode | stat.S_IXUSR)
            yield f"{interval} '{command_script.as_posix()}'"

    def install(self, schedule_ids: list[str]) -> None:
        if schedule_ids:
            schedule_id_set = set(schedule_ids)
            predicate = lambda x: x in schedule_id_set
        else:
            predicate = lambda _: True
        self.entries = self._unique_entries(
            *self._new_entries(predicate), *self.entries
        )

    def uninstall(self, schedule_ids: list[str], uninstall_all: bool) -> None:
        prev_entries = self.entries

        # Get the predicate rule for what should be removed
        if uninstall_all:
            # XXX: This leaves behind the "begin/end Meltano section" comments
            predicate = lambda _: True
        elif schedule_ids:
            schedule_id_set = set(schedule_ids)
            predicate = lambda x: x in schedule_id_set
        else:  # Only uninstall the entries that are found in the current Meltano project:
            predicate = lambda x: x in self.meltano_schedule_ids

        # Update the installed entries and scripts using the chosen rule
        self.entries = (
            entry
            for entry in self.entries
            if self.entry_pattern.fullmatch(entry)
            and not predicate(self.entry_pattern.fullmatch(entry).group("name"))
        )
        for entry in prev_entries:
            match = self.entry_pattern.fullmatch(entry)
            if match and predicate(match.group("name")):
                with suppress(FileNotFoundError):
                    Path(match.group("path")).unlink()

    def describe(self) -> models.Describe:
        # TODO: could we auto-generate all or portions of this from typer instead?
        return models.Describe(
            commands=[
                models.ExtensionCommand(name="cron", description="extension commands"),
            ]
        )
