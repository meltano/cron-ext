"""Meltano CRON utility extension."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, Iterable

if sys.version_info >= (3, 8):
    from functools import cached_property
else:
    from cached_property import cached_property

import structlog
from meltano.edk import models
from meltano.edk.extension import ExtensionBase

from cron_ext import APP_NAME

log = structlog.get_logger(APP_NAME)


def run_subprocess(
    args: tuple[str, ...],
    error_message: str,
    *,
    exit_on_nonzero_returncode: bool = True,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Helper function to run a subprocess.

    Args:
        args: Args for the subprocess to run.
        error_message: The error message to log if the process has a non-zero
            return code, or if an exception is raised (e.g. because the
            command was not found).
        kwargs: Keyword arguments for `subprocess.run`.
        exit_on_nonzero_returncode: Whether the calling process should exit if
            the subprocess has a non-zero return code.

    Returns:
        The completed process.
    """
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=True,
            **kwargs,
        )
    except subprocess.CalledProcessError:
        if exit_on_nonzero_returncode:
            log.critical(error_message)
            sys.exit(proc.returncode)
        log.error(error_message)
    except Exception:
        log.exception(error_message)
        sys.exit(1)
    return proc


class Cron(ExtensionBase):
    """Meltano extension class for cron-ext."""

    comment_pattern = re.compile(r"^\s*#.*$")
    entry_pattern = re.compile(r"(?i)^.+?'(?P<path>/?(?:.*/)(?P<name>.*)\.sh)'.*$")

    def invoke(self, *args: Any, **kwargs: Any) -> None:
        """Invoke the underlying CLI that is being wrapped by this extension.

        Args:
            args: Ignored positional arguments.
            kwargs: Ignored keyword arguments.

        Raises:
            NotImplementedError: There is no underlying CLI for this extension.
        """
        raise NotImplementedError

    @cached_property
    def meltano_project_dir(self) -> Path:
        """Path to the Meltano project directory."""
        # noqa: DAR201
        try:
            return Path(os.environ["MELTANO_PROJECT_ROOT"]).resolve()
        except KeyError:
            # In rare cases `$MELTANO_PROJECT_ROOT` may not be set, so we try
            # using the current working directory.
            return (Path.cwd() / "meltano.yml").resolve(strict=True).parent

    @cached_property
    def cron_ext_dir(self) -> Path:
        """Path to the cron-ext directory, where scripts run by cron are stored."""
        # noqa: DAR201
        path: Path = self.meltano_project_dir / ".meltano" / "run" / "cron-ext"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @cached_property
    def meltano_schedule(self) -> dict[str, list[dict]]:
        """JSON schedule data from Meltano."""
        # noqa: DAR201
        return json.loads(  # type: ignore
            run_subprocess(
                ("meltano", "schedule", "list", "--format=json"),
                "Unable to list Meltano schedules.",
            ).stdout
        )["schedules"]

    @cached_property
    def meltano_schedule_ids(self) -> set[str]:
        """Schedule IDs from Meltano."""
        # noqa: DAR201
        return {
            schedule["name"]
            for schedule in self.meltano_schedule["elt"] + self.meltano_schedule["job"]
        }

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

    @staticmethod
    def _index_of_match(pattern: str, lines: Iterable[str]) -> int:
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
    def _ignore_entry(cls, entry: str) -> bool:
        # Preserve/skip full-line comments and blank lines
        return bool(cls.comment_pattern.fullmatch(entry)) or not entry.strip()

    @classmethod
    def _unique_entries(cls, *entries: str) -> Iterable[str]:
        seen = set()
        for entry in entries:
            if cls._ignore_entry(entry):
                yield entry
            else:
                match = cls.entry_pattern.fullmatch(entry)
                if not match:
                    continue
                elif match["name"] not in seen:
                    seen.add(match["name"])
                    yield entry

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

    def install(self, schedule_ids: set[str]) -> None:
        """Install cron entries into the Meltano section of the crontab.

        Args:
            schedule_ids: The IDs of the schedules to be installed. If none are
                provided, then all schedules Meltano knows about will be
                installed. If any specified IDs are not known to Meltano, then
                the ones that are available will be installed, an error-level
                log message will be emitted specifying which IDs could not be
                installed, and the program will exit with return code 1.
        """
        if schedule_ids:
            predicate = lambda x: x in schedule_ids
        else:
            predicate = lambda _: True
        self.entries = tuple(
            self._unique_entries(
                *self._new_entries(predicate),
                *self.entries,
            )
        )
        if schedule_ids:
            unavailable_schedule_ids = schedule_ids - self.meltano_schedule_ids
            if unavailable_schedule_ids:
                log.error(
                    "Failed to install all specified schedules: schedules "
                    f"with IDs {unavailable_schedule_ids!r} were not found"
                )
                sys.exit(1)

    def uninstall(self, schedule_ids: set[str], uninstall_all: bool) -> None:
        """Uninstall cron entries from the Meltano section of the crontab.

        Args:
            schedule_ids: The IDs of the schedules to be uninstalled. If none
                are provided, then all schedules known to Meltano will be
                uninstalled.
            uninstall_all: Whether all installed Meltano schedules should be
                uninstalled, including those currently unknown to Meltano.
        """
        prev_entries = self.entries

        # Get the predicate rule for what should be removed
        if uninstall_all:
            # XXX: This leaves behind the "begin/end Meltano section" comments
            # FIXME: This does not delete all managed scripts in
            #        `.meltano/run/cron-ext/`
            predicate = lambda _: True
        elif schedule_ids:
            predicate = lambda x: x in schedule_ids
        else:  # Only uninstall entries that are found in the current Meltano project:
            predicate = lambda x: x in self.meltano_schedule_ids

        # Update the installed entries and scripts using the chosen rule
        entries = []
        for entry in self.entries:
            match = self.entry_pattern.fullmatch(entry)
            if match and not predicate(match.group("name")):
                entries.append(entry)
        self.entries = tuple(entries)

        for entry in prev_entries:
            match = self.entry_pattern.fullmatch(entry)
            if match and predicate(match["name"]):
                with suppress(FileNotFoundError):
                    Path(match["path"]).unlink()

    def describe(self) -> models.Describe:
        """Generate a description of the commands and capabilities the ext provides.

        Returns:
            A description of the commands and capabilities the extension provides.
        """
        # TODO: could we auto-generate all or portions of this from typer instead?
        return models.Describe(
            commands=[
                models.ExtensionCommand(name="cron", description="extension commands"),
            ]
        )
