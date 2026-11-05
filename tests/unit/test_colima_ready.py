import json
import shutil
import subprocess
from unittest.mock import MagicMock

import pytest
from hypothesis import given
from hypothesis import strategies as st

import colima_ready as ready

LIMIT_BYTES = ready.COLIMA_MEMORY_GIB * ready.BYTES_PER_GIB


def status_result(returncode: int, memory_bytes: int = 0) -> subprocess.CompletedProcess[bytes]:
    body = json.dumps({"memory": memory_bytes}).encode()
    return subprocess.CompletedProcess(["colima"], returncode, stdout=body)


@given(memory_bytes=st.integers(min_value=0, max_value=LIMIT_BYTES))
def test_memory_within_the_limit_passes(memory_bytes: int) -> None:
    assert ready.memory_problem(memory_bytes) is None


@given(memory_bytes=st.integers(min_value=LIMIT_BYTES + 1, max_value=LIMIT_BYTES * 16))
def test_memory_above_the_limit_is_reported(memory_bytes: int) -> None:
    assert ready.memory_problem(memory_bytes) is not None


def test_the_report_says_how_much_memory_and_what_to_do() -> None:
    problem = ready.memory_problem(8 * ready.BYTES_PER_GIB)

    assert problem is not None
    assert "8.0 GiB" in problem
    assert "colima stop" in problem


def test_hosts_without_colima_are_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    run = MagicMock()
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(subprocess, "run", run)

    assert ready.main() == 0
    run.assert_not_called()


def test_stopped_colima_starts_with_the_project_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    run = MagicMock(side_effect=[status_result(1), status_result(0)])
    monkeypatch.setattr(shutil, "which", lambda _: "/opt/homebrew/bin/colima")
    monkeypatch.setattr(subprocess, "run", run)

    assert ready.main() == 0

    start_command = run.call_args_list[1].args[0]
    assert start_command[:2] == ["colima", "start"]
    assert "--memory=6" in start_command


def test_running_colima_within_the_limit_is_not_restarted(monkeypatch: pytest.MonkeyPatch) -> None:
    run = MagicMock(return_value=status_result(0, LIMIT_BYTES))
    monkeypatch.setattr(shutil, "which", lambda _: "/opt/homebrew/bin/colima")
    monkeypatch.setattr(subprocess, "run", run)

    assert ready.main() == 0
    assert run.call_count == 1


def test_oversized_colima_stops_the_stack_and_is_not_restarted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = MagicMock(return_value=status_result(0, LIMIT_BYTES * 2))
    monkeypatch.setattr(shutil, "which", lambda _: "/opt/homebrew/bin/colima")
    monkeypatch.setattr(subprocess, "run", run)

    assert ready.main() == 1
    assert run.call_count == 1
    assert "12.0 GiB" in capsys.readouterr().err
