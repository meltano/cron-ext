from __future__ import annotations

import ast
import json
import logging
import os
import random
import re
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Generator, Iterable, Protocol, Sequence

import pytest
import yaml
from typer.testing import CliRunner, Result

from cron_ext import main
from cron_ext.extension import Cron

test_dir = Path(__file__).parent
cron_ext_script_dir = Path(".meltano/run/cron-ext/")
project_name = "cron_test_project"


@pytest.fixture(scope="session", autouse=True)
def meltano_project(tmp_path_factory: pytest.TempPathFactory) -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(tmp_path_factory.mktemp(f"cron-ext-projects-{os.getpid()}"))
        subprocess.run(
            ("meltano", "init", "--no_usage_stats", project_name), check=True
        )
        monkeypatch.chdir(project_name)
        shutil.copy(test_dir / "meltano.yml", "meltano.yml")
        subprocess.run(("meltano", "install", "utility", "cron"), check=True)
        yield


class Invoker(Protocol):
    def __call__(self, *args: str, expected_exit_code: int = ...) -> Result:
        ...


@pytest.fixture(scope="session")
def invoke() -> Invoker:
    def invoker(*args: str, expected_exit_code: int = 0):
        result = CliRunner().invoke(main.app, args)
        assert result.exit_code == expected_exit_code
        return result

    return invoker


@pytest.fixture(scope="function", autouse=True)
def reset_ext() -> None:
    # Required to reset the data cached by the extension between each test
    main.ext = Cron()


class CrontabContextManager(Protocol):
    def __call__(
        self, entries: Sequence[str], append: bool = ...
    ) -> Generator[None, None, None]:
        ...


@contextmanager
def cron_entries(entries: Sequence[str], append: bool = False) -> None:
    prev_content = subprocess.run(
        ("crontab", "-l"), stdout=subprocess.PIPE, text=True
    ).stdout
    if not prev_content.endswith("\n"):
        prev_content += "\n"
    try:
        proc = subprocess.run(
            ("crontab", "-"),
            input="\n".join(
                (*prev_content.splitlines(), *entries) if append else entries
            )
            + "\n",
            capture_output=True,
            text=True,
        )
        assert not proc.returncode
        yield
    finally:
        subprocess.run(("crontab", "-"), input=prev_content, text=True)


@contextmanager
def meltano_cron_entries(entries: Sequence[str], append: bool = False) -> None:
    with cron_entries(
        (
            "# --- BEGIN MELTANO CRONTAB SECTION ---",
            *entries,
            "# --- END MELTANO CRONTAB SECTION ---",
        ),
        append=append,
    ):
        yield


# Using this test to check both that the help text is printed when no
# sub-command is given, and that the CLI test harness is behaving at least
# fairly similar to simply running the extension with a subprocess.
@pytest.mark.parametrize(
    "invoke",
    (
        lambda: CliRunner().invoke(main.app),
        lambda: subprocess.run(
            ("meltano", "invoke", "cron"),
            stdout=subprocess.PIPE,
            text=True,
        ),
    ),
    ids=("CliRunner", "subprocess"),
)
def test_no_command(invoke: Callable[[], subprocess.CompletedProcess | Result]):
    result = invoke()
    try:
        assert not result.exit_code
    except AttributeError:
        assert not result.returncode
    assert result.stdout.startswith("Usage: cron [OPTIONS] COMMAND [ARGS]...\n")
    assert "Options:" in result.stdout
    assert "Commands:" in result.stdout


def test_initialize(invoke: Invoker):
    # The initialize command is a no-op; ensure it does not raise an exception
    invoke("initialize")


@pytest.mark.parametrize(
    ("format_arg", "verifier"),
    (
        (None, ast.parse),
        ("--format=text", ast.parse),
        ("--format=json", json.loads),
        ("--format=yaml", yaml.safe_load),
    ),
)
def test_describe(
    invoke: Invoker, format_arg: str | None, verifier: Callable[[str], Any]
):
    result = invoke("describe", format_arg) if format_arg else invoke("describe")
    assert result.output
    verifier(result.output)


class TestListCommand:
    def test_list_empty(self, invoke: Invoker):
        for manager in (cron_entries, meltano_cron_entries):
            with manager(()):
                result = invoke("list")
                assert not result.output

    def test_list_only_lists_meltano_entries(self, invoke: Invoker):
        new_meltano_cron_entries = [
            "1 1 1 1 1 echo 'double negative' | tac | tac",
            "2 2 2 2 2 head -c 16 /dev/urandom > /dev/null",
        ]
        with cron_entries(
            (
                "1 2 3 4 5 true",
                "5 4 3 2 1 false",
            )
        ):
            with meltano_cron_entries(
                new_meltano_cron_entries,
                append=True,
            ):
                assert invoke("list").output.splitlines() == new_meltano_cron_entries

    @pytest.mark.parametrize("max_repeats", range(1, 8))
    def test_detect_meltano_entries(self, invoke: Invoker, max_repeats: int):
        """
        Ensure that the largest valid section is identified when detecting Meltano
        entries in a crontab, and that the identification of the section header and
        footer is sufficiently flexible.
        """
        dashes = ["-" * x for x in random.choices(range(1, max_repeats + 1), k=4)]
        spaces = [" " * x for x in random.choices(range(max_repeats), k=10)]
        non_comment_entries = [
            "1 1 1 1 1 true",
            "2 2 2 2 2 true",
            "3 3 3 3 3 true",
            "4 4 4 4 4 true",
            "5 5 5 5 5 true",
        ]
        begin_section_line = (
            "{0}#{1}{5}{2}BEGIN MELTANO CRONTAB SECTION{3}{6}{4}".format(
                *spaces[::2], *dashes[::2]
            )
        )
        end_section_line = "{0}#{1}{5}{2}END MELTANO CRONTAB SECTION{3}{6}{4}".format(
            *spaces[1::2], *dashes[1::2]
        )
        with cron_entries(
            (
                begin_section_line,
                non_comment_entries[0],
                "# A comment",
                begin_section_line,
                non_comment_entries[1],
                non_comment_entries[2],
                "# Another comment",
                non_comment_entries[3],
                "# --- END MELTANO CRONTAB SECTION --- ",
                end_section_line,
                non_comment_entries[4],
                end_section_line,
            )
        ):
            assert invoke("list").output.splitlines() == non_comment_entries


@contextmanager
def meltano_yml(content: str) -> None:
    # We assume & assert that the CWD is within a Meltano project
    meltano_yml_path = Path.cwd() / "meltano.yml"
    meltano_yml_bak_path = Path.cwd() / "meltano.yml.bak"
    assert meltano_yml_path.exists()
    assert not meltano_yml_bak_path.exists()
    meltano_yml_path.rename(meltano_yml_bak_path)
    meltano_yml_path.write_text(content)
    try:
        yield
    finally:
        meltano_yml_bak_path.rename(meltano_yml_path)
        assert meltano_yml_path.exists()
        assert not meltano_yml_bak_path.exists()


@contextmanager
def meltano_yml_schedules(schedules: list[dict[str, str | datetime]]) -> None:
    # We assume & assert that the CWD is within a Meltano project
    meltano_yml_path = Path.cwd() / "meltano.yml"
    assert meltano_yml_path.exists()
    meltano_yml_content = yaml.safe_load(meltano_yml_path.read_text())
    if schedules:
        meltano_yml_content["schedules"] = schedules
    else:
        del meltano_yml_content["schedules"]
    with meltano_yml(yaml.dump(meltano_yml_content)):
        yield


def check_installed(schedule_ids: Iterable[str]):
    entries = subprocess.run(
        ("meltano", "invoke", "cron", "list"),
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.splitlines()
    entry_set = set(entries)
    assert len(entries) == len(entry_set)
    cwd = Path.cwd().resolve()
    seen = set()
    for entry in entry_set:
        match = Cron.entry_pattern.fullmatch(entry)
        seen.add(match.group("name"))
        path = Path(match.group("path"))
        assert path.exists()
        assert path.relative_to(cwd).parent == cron_ext_script_dir
    assert set(schedule_ids) == seen


class TestInstallCommand:
    def test_install_nothing(self, invoke: Invoker):
        with meltano_yml_schedules([]):
            assert not invoke("install").output
            assert not invoke("list").output

    def test_install_all(self, invoke: Invoker):
        assert not invoke("install").output
        check_installed(Cron().meltano_schedule_ids)

    @pytest.mark.parametrize(
        "schedule_ids",
        (
            ("a-to-b", "c-to-d"),
            ("c-to-d",),
            ("e-to-f", "c-to-d"),
            # Ensure duplicates work properly:
            random.choices(("a-to-b", "c-to-d", "e-to-f"), k=12),
        ),
    )
    def test_install_selective(self, invoke: Invoker, schedule_ids: tuple[str]):
        with cron_entries(()):
            assert not invoke("install", *schedule_ids).output
            check_installed(schedule_ids)

    @pytest.mark.parametrize(
        "schedule_ids",
        (
            {"a-to-b", "c-to-d", "not-real"},
            {"not-real"},
        ),
    )
    def test_install_unavailable(
        self,
        schedule_ids: set[str],
        invoke: Invoker,
        caplog: pytest.LogCaptureFixture,
    ):
        with cron_entries(()), caplog.at_level(logging.ERROR):
            invoke("install", *schedule_ids, expected_exit_code=1)

            should_be_installed = schedule_ids - {"not-real"}
            if should_be_installed:
                check_installed(should_be_installed)

        assert len(caplog.record_tuples) == 1
        assert caplog.record_tuples[0][0] == "cron-ext"
        assert caplog.record_tuples[0][1] == logging.ERROR
        match = re.fullmatch(
            "Failed to install all specified schedules: schedules with IDs "
            "(.*) were not found",
            caplog.record_tuples[0][2],
        )
        assert ast.literal_eval(match[1]) == {"not-real"}

    def test_install_does_not_interfere_with_existing_cron_entries(
        self, invoke: Invoker
    ):
        non_meltano_entries = ["1 2 3 4 5 true", "5 4 3 2 1 false"]
        with cron_entries(non_meltano_entries):
            assert not invoke("install").output
            assert (
                subprocess.run(
                    ("crontab", "-l"), stdout=subprocess.PIPE, text=True
                ).stdout.splitlines()[:2]
                == non_meltano_entries
            )

    def test_install_can_clear_existing_meltano_entries(self, invoke: Invoker):
        with meltano_cron_entries(("1 2 3 4 5 true", "5 4 3 2 1 false")):
            with meltano_yml_schedules([]):
                assert not invoke("install").output
                assert not invoke("list").output


class TestUninstallCommand:
    @pytest.mark.parametrize("crontab_section", (cron_entries, meltano_cron_entries))
    def test_uninstall_with_no_cron_entries(
        self, invoke: Invoker, crontab_section: CrontabContextManager
    ):
        with crontab_section(()):
            assert not invoke("uninstall").output

    @pytest.mark.parametrize("crontab_section", (cron_entries, meltano_cron_entries))
    def test_uninstall_available(
        self, invoke: Invoker, crontab_section: CrontabContextManager
    ):
        with crontab_section(()):
            assert not invoke("install").output
            assert invoke("list").output
            assert list(cron_ext_script_dir.iterdir())
            assert not invoke("uninstall").output
            assert not invoke("list").output
            assert not list(cron_ext_script_dir.iterdir())

    @pytest.mark.parametrize("flag", ("-a", "--all"))
    def test_uninstall_all(self, flag: str, invoke: Invoker):
        with meltano_cron_entries(("1 2 3 2 1 true", "5 4 3 4 5 false")):
            assert not invoke("install").output
            assert invoke("list").output
            assert list(cron_ext_script_dir.iterdir())
            assert not invoke("uninstall", flag).output
            assert not invoke("list").output
            assert not list(cron_ext_script_dir.iterdir())

    @pytest.mark.parametrize(
        "schedule_ids",
        (
            {"a-to-b"},
            {"a-to-b", "e-to-f", "c-to-d"},
            {"catbat"},  # uninstalling non-existent entries is fine
            {"batcat", "e-to-f"},  # non-existent entries should not interfere
        ),
    )
    def test_uninstall_selective(self, invoke: Invoker, schedule_ids: set[str]):
        assert not invoke("install").output
        check_installed({"a-to-b", "e-to-f", "c-to-d"})
        assert not invoke("uninstall", *schedule_ids).output
        check_installed({"a-to-b", "e-to-f", "c-to-d"} - schedule_ids)

    @pytest.mark.parametrize("uninstall_args", ((), ("--all",), ("a-to-b", "e-to-f")))
    @pytest.mark.parametrize("do_install", (True, False))
    def test_uninstall_does_not_interfere_with_existing_cron_entries(
        self, do_install: bool, uninstall_args: tuple[str, ...], invoke: Invoker
    ):
        non_meltano_entries = ["1 2 * 4 5 true", "5 4 * 2 1 false"]
        with cron_entries(non_meltano_entries):
            if do_install:
                assert not invoke("install").output
            assert not invoke("uninstall", *uninstall_args).output
            assert (
                subprocess.run(
                    ("crontab", "-l"), stdout=subprocess.PIPE, text=True
                ).stdout.splitlines()[:2]
                == non_meltano_entries
            )
