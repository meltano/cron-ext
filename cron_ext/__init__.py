"""A Meltano utility extension that provides basic job scheduling via CRON."""

from enum import Enum

APP_NAME = "cron-ext"


class Target(str, Enum):
    """Enum of cron entry stores that can be used by this extension."""

    crontab = "crontab"
    stdout = "stdout"
