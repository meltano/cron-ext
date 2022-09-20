"""Meltano CRON utility extension CLI entrypoint."""

from __future__ import annotations

import sys
from typing import List, Optional

import structlog
import typer
from meltano.edk.extension import DescribeFormat
from meltano.edk.logging import default_logging_config, parse_log_level

from cron_ext import APP_NAME
from cron_ext.extension import Cron

log = structlog.get_logger(APP_NAME)

ext = Cron()

typer.core.rich = None  # remove to enable stylized help output when `rich` is installed
app = typer.Typer(
    name='cron',
    pretty_exceptions_enable=False,
)


@app.command()
def initialize(
    ctx: typer.Context,
    force: bool = typer.Option(False, help="Force initialization (if supported)"),
) -> None:
    """Initialize the cron extension (no-op)."""
    try:
        ext.initialize(force)
    except Exception:
        log.exception(
            "initialize failed with uncaught exception, please report to maintainer"
        )
        sys.exit(1)


@app.command(name="list")
def list_command() -> None:
    """List installed cron entries for the Meltano project."""
    entries = ext.entries
    if entries:
        typer.echo("\n".join(entries))


@app.command()
def install(
    ctx: typer.Context,
    schedule_ids: Optional[List[str]] = typer.Argument(None),
) -> None:
    """Install a crontab for the Meltano project."""
    ext.install(set(schedule_ids or ()))


@app.command()
def uninstall(
    ctx: typer.Context,
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
) -> None:
    """Uninstall a crontab for the Meltano project."""
    ext.uninstall(set(schedule_ids or ()), uninstall_all)


@app.command()
def describe(
    output_format: DescribeFormat = typer.Option(
        DescribeFormat.text, "--format", help="Output format"
    )
) -> None:
    """Describe the available commands for the cron extension."""
    try:
        typer.echo(ext.describe_formatted(output_format))
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
    """Meltano utility extension that provides basic job scheduling via CRON."""
    default_logging_config(
        level=parse_log_level(log_level),
        timestamps=log_timestamps,
        levels=log_levels,
        json_format=meltano_log_json,
    )
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
