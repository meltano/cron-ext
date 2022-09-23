"""Convenience functions for handling subprocesses."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import structlog

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
