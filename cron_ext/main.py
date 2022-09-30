"""Meltano cron utility extension CLI entrypoint."""

from __future__ import annotations

import sys
from typing import List, Optional

import structlog
import typer
from meltano.edk.extension import DescribeFormat
from meltano.edk.logging import default_logging_config, parse_log_level

from cron_ext import APP_NAME, Target
from cron_ext.entry import entry_pattern
from cron_ext.extension import Cron

log = structlog.get_logger(APP_NAME)

typer.core.rich = None  # remove to enable stylized help output when `rich` is installed
app = typer.Typer(
    name="cron",
    pretty_exceptions_enable=False,
)


@app.command()
def initialize(
    ctx: typer.Context,
    force: bool = typer.Option(False, help="Force initialization (if supported)"),
) -> None:
    """Initialize the cron extension (no-op)."""
    try:
        Cron().initialize(force)
    except Exception:
        log.exception(
            "initialize failed with uncaught exception, please report to maintainer"
        )
        sys.exit(1)


@app.command(name="list")
def list_command(
    target: Target = Target.crontab,
    name_only: bool = typer.Option(False, help="Whether only the names of the installed schedules should be listed")
) -> None:
    """List installed cron entries for the Meltano project."""
    entries = Cron(store=target).store.entries
    if name_only:
        entries = (entry_pattern.fullmatch(entry)['name'] for entry in entries)
    if entries:
        typer.echo("\n".join(entries))


@app.command()
def install(
    schedule_ids: Optional[List[str]] = typer.Argument(None),
    target: Target = Target.crontab,
) -> None:
    """Install a crontab for the Meltano project."""
    Cron(store=target).install(set(schedule_ids or ()))


@app.command()
def uninstall(
    schedule_ids: Optional[List[str]] = typer.Argument(None),
    uninstall_all: bool = typer.Option(
        False,
        "--all",
        "-a",
        help=(
            "Uninstall all schedules, rather than just the ones from the "
            "active Meltano environment"
        ),
    ),
    target: Target = Target.crontab,
) -> None:
    """Uninstall a crontab for the Meltano project."""
    try:
        Cron(store=target).uninstall(set(schedule_ids or ()), uninstall_all)
    except ValueError as ex:
        log.error(str(ex))
        sys.exit(1)


@app.command()
def describe(
    output_format: DescribeFormat = typer.Option(
        DescribeFormat.text, "--format", help="Output format"
    )
) -> None:
    """Describe the available commands for the cron extension."""
    try:
        typer.echo(Cron().describe_formatted(output_format))
    except Exception:
        log.exception(
            "describe failed with uncaught exception, please report to maintainer"
        )
        sys.exit(1)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL"),
    log_timestamps: bool = typer.Option(
        False, envvar="LOG_TIMESTAMPS", help="Show timestamp in logs"
    ),
    log_levels: bool = typer.Option(
        False, "--log-levels", envvar="LOG_LEVELS", help="Show log levels"
    ),
    meltano_log_json: bool = typer.Option(
        False,
        "--meltano-log-json",
        envvar="MELTANO_LOG_JSON",
        help="Log in the meltano JSON log format",
    ),
) -> None:
    """Meltano utility extension that provides basic job scheduling via cron."""
    default_logging_config(
        level=parse_log_level(log_level),
        timestamps=log_timestamps,
        levels=log_levels,
        json_format=meltano_log_json,
    )
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
