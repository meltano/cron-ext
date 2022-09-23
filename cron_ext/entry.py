"""Patterns & utilities for handling cron entries."""

import re

comment_pattern = re.compile(r"^\s*#.*$")
entry_pattern = re.compile(r"(?i)^.+?'(?P<path>(?:/.*)*/(?P<name>.*)\.sh)'.*$")
