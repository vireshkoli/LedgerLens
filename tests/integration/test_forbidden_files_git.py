import hashlib
import subprocess
from pathlib import Path

import pytest

import check_forbidden_files as guard

PDF_BYTES = b"%PDF-1.7"


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    return tmp_path


def track(*names: str) -> None:
    subprocess.run(["git", "add", "--force", *names], check=True)


def git(*arguments: str) -> None:
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]
    subprocess.run(["git", *identity, *arguments], check=True, capture_output=True)


def commit_all(message: str) -> None:
    track(".")
    git("commit", "--quiet", "--allow-empty", "--message", message)


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


def test_history_passes_when_nothing_was_ever_blocked(repository: Path) -> None:
    (repository / "notes.md").write_text("first", encoding="utf-8")
    commit_all("add notes")
    (repository / "notes.md").write_text("second", encoding="utf-8")
    commit_all("change notes")

    assert guard.main(["--history"]) == 0


def test_history_finds_a_pdf_added_then_removed(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repository / "annual report.pdf").write_bytes(PDF_BYTES)
    commit_all("add a report")
    git("rm", "--quiet", "annual report.pdf")
    commit_all("remove the report")

    assert guard.main(["--all"]) == 0
    assert guard.main(["--history"]) == 1
    assert "annual report.pdf" in capsys.readouterr().err


def test_history_finds_a_version_that_was_overwritten(repository: Path) -> None:
    (repository / "cases.jsonl").write_bytes(b'{"financebench_id": "financebench_id_03029"}')
    commit_all("add cases")
    (repository / "cases.jsonl").write_bytes(b"{}")
    commit_all("empty the cases")

    assert guard.main(["--all"]) == 0
    assert guard.main(["--history"]) == 1


def test_history_finds_the_path_a_file_was_renamed_from(repository: Path) -> None:
    (repository / "private").mkdir()
    (repository / "private" / "notes.md").write_text("restricted", encoding="utf-8")
    commit_all("add notes")
    git("mv", "private/notes.md", "notes.md")
    commit_all("move the notes")

    assert guard.main(["--all"]) == 0
    assert guard.main(["--history"]) == 1


def test_history_finds_a_file_only_a_merge_commit_added(repository: Path) -> None:
    (repository / "start.md").write_text("start", encoding="utf-8")
    commit_all("start")
    git("switch", "--quiet", "--create", "side")
    (repository / "side.md").write_text("side", encoding="utf-8")
    commit_all("side work")
    git("switch", "--quiet", "-")
    (repository / "main.md").write_text("main", encoding="utf-8")
    commit_all("main work")
    git("merge", "--quiet", "--no-commit", "--no-ff", "side")
    (repository / "report.pdf").write_bytes(PDF_BYTES)
    commit_all("merge with an extra file")
    git("rm", "--quiet", "report.pdf")
    commit_all("remove the extra file")

    assert guard.main(["--history"]) == 1


def test_history_honours_the_allowlist(repository: Path) -> None:
    (repository / "config").mkdir()
    (repository / "filing.pdf").write_bytes(PDF_BYTES)
    (repository / "config" / "allowed_fixtures.sha256").write_text(
        f"{hashlib.sha256(PDF_BYTES).hexdigest()}  filing.pdf\n", encoding="utf-8"
    )
    commit_all("add an approved fixture")

    assert guard.main(["--history"]) == 0


def test_history_skips_submodules(repository: Path) -> None:
    (repository / "notes.md").write_text("notes", encoding="utf-8")
    commit_all("add notes")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    git("update-index", "--add", "--cacheinfo", f"160000,{head},vendored")
    git("commit", "--quiet", "--message", "add a submodule")

    assert guard.main(["--history"]) == 0


def test_history_refuses_a_shallow_clone(
    repository: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repository / "report.pdf").write_bytes(PDF_BYTES)
    commit_all("add a report")
    git("rm", "--quiet", "report.pdf")
    commit_all("remove the report")
    clone = tmp_path_factory.mktemp("shallow") / "clone"
    git("clone", "--quiet", "--depth=1", f"file://{repository}", str(clone))
    monkeypatch.chdir(clone)

    assert guard.main(["--history"]) == 1
