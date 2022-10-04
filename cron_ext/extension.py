"""Meltano cron utility extension."""

from __future__ import annotations

import json
import os
import stat
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

import cron_ext.stores as stores
from cron_ext import APP_NAME, Target
from cron_ext.entry import entry_pattern
from cron_ext.subprocess import run_subprocess

log = structlog.get_logger(APP_NAME)


class Cron(ExtensionBase):
    """Meltano extension class for cron-ext."""

    def __init__(
        self,
        *args: Any,
        store: Target = Target.crontab,
        **kwargs: Any,
    ) -> None:
        """Initialize the cron extension.

        Args:
            args: Positional arguments passed to the parent class.
            store: The store which should be used for reading/writing cron entries.
            kwargs: Keyword arguments passed to the parent class.
        """
        super().__init__(*args, **kwargs)
        self.store: stores.EntryStore = {
            Target.crontab: stores.CrontabEntryStore,
            Target.stdout: stores.StdoutEntryStore,
        }[store]()
        self.meltano_project_dir = Path(os.environ["MELTANO_PROJECT_ROOT"]).resolve()

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
        self.store.entries = (
            *self._new_entries(predicate),
            *self.store.entries,
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

        Raises:
            ValueError: The store is inappropriate for uninstallation.
        """
        if not self.store.is_managed:
            raise ValueError("Cannot uninstall from an unmanaged cron entry store")

        prev_entries = self.store.entries

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
        for entry in self.store.entries:
            match = entry_pattern.fullmatch(entry)
            if match and not predicate(match.group("name")):
                entries.append(entry)
        self.store.entries = tuple(entries)

        for entry in prev_entries:
            match = entry_pattern.fullmatch(entry)
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
