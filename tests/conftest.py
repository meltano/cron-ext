import os
import sys
from pathlib import Path

from pytest import Session

test_dir = Path(__file__).parent

sys.path.append(str(test_dir.parent))


def pytest_sessionstart(session: Session) -> None:
    if os.environ.get('CONTAINERIZED', 'False')[0].lower() != 't':
        raise Exception('These tests should only be run within a container! Refer to README.md')
