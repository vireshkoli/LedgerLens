import subprocess
from pathlib import Path

import pytest

import check_forbidden_files as guard


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    return tmp_path


def track(*names: str) -> None:
    subprocess.run(["git", "add", "--force", *names], check=True)


def test_all_flag_finds_a_tracked_pdf_with_a_space_in_its_name(repository: Path) -> None:
    (repository / "annual report.pdf").write_bytes(b"%PDF-1.7")
    track("annual report.pdf")

    assert guard.main(["--all"]) == 1


def test_all_flag_ignores_untracked_files(repository: Path) -> None:
    (repository / "notes.md").write_text("fine", encoding="utf-8")
    track("notes.md")
    (repository / "untracked.pdf").write_bytes(b"%PDF-1.7")

    assert guard.main(["--all"]) == 0


def test_all_flag_honours_the_allowlist_on_disk(repository: Path) -> None:
    (repository / "config").mkdir()
    fixture = repository / "filing.pdf"
    fixture.write_bytes(b"%PDF-1.7")
    digest = subprocess.run(
        ["shasum", "-a", "256", "filing.pdf"], check=True, capture_output=True, text=True
    ).stdout.split()[0]
    (repository / "config" / "allowed_fixtures.sha256").write_text(
        f"{digest}  filing.pdf\n", encoding="utf-8"
    )
    track("filing.pdf", "config/allowed_fixtures.sha256")

    assert guard.main(["--all"]) == 0
