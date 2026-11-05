import hashlib
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

import check_forbidden_files as guard

PDF_BYTES = b"%PDF-1.7\nsome content"
FILE_NAMES = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=20)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize("name", ["report.pdf", "REPORT.PDF", "tests/fixtures/report.Pdf"])
def test_pdf_extension_is_blocked_in_any_case(name: str) -> None:
    assert guard.find_violation(name, b"not really a pdf", {}) is not None


@given(name=FILE_NAMES, suffix=st.sampled_from(["", ".txt", ".py", ".md", ".bin"]))
def test_renamed_pdf_is_blocked_by_its_content(name: str, suffix: str) -> None:
    assert guard.find_violation(name + suffix, PDF_BYTES, {}) is not None


def test_pdf_header_after_leading_bytes_is_blocked() -> None:
    assert guard.find_violation("disguised.bin", b"\x00" * 500 + PDF_BYTES, {}) is not None


def test_allowlisted_pdf_with_matching_hash_passes() -> None:
    allowlist = {"tests/fixtures/filing.pdf": sha256(PDF_BYTES)}
    assert guard.find_violation("tests/fixtures/filing.pdf", PDF_BYTES, allowlist) is None


def test_allowlisted_path_with_different_content_is_blocked() -> None:
    allowlist = {"tests/fixtures/filing.pdf": sha256(b"the approved file")}
    assert guard.find_violation("tests/fixtures/filing.pdf", PDF_BYTES, allowlist) is not None


def test_hash_approved_for_another_path_does_not_transfer() -> None:
    allowlist = {"tests/fixtures/filing.pdf": sha256(PDF_BYTES)}
    assert guard.find_violation("somewhere/else.pdf", PDF_BYTES, allowlist) is not None


@pytest.mark.parametrize(
    "name",
    [
        "financebench_open_source.jsonl",
        "data/FinanceBench_cases.csv",
        "eval/financebench/cases.json",
        "financebench.parquet",
    ],
)
def test_financebench_data_is_blocked_by_name(name: str) -> None:
    assert guard.find_violation(name, b"{}", {}) is not None


@pytest.mark.parametrize("name", ["cases.jsonl", "fixture.csv", "export.parquet", "notes.txt"])
def test_financebench_records_are_blocked_under_any_data_name(name: str) -> None:
    content = b'{"financebench_id": "financebench_id_03029", "question": "..."}'
    assert guard.find_violation(name, content, {}) is not None


@pytest.mark.parametrize("name", ["src/ledgerlens/ingest/financebench.py", "docs/financebench.md"])
def test_code_and_docs_may_name_financebench(name: str) -> None:
    assert guard.find_violation(name, b"financebench_id is a field name", {}) is None


@pytest.mark.parametrize("name", ["private/notes.md", "data/private/ltimes.json", "Private/a.py"])
def test_private_tier_is_blocked_whatever_the_file_type(name: str) -> None:
    assert guard.find_violation(name, b"text", {}) is not None


def test_leading_dot_slash_cannot_dodge_the_private_rule() -> None:
    assert guard.find_violation("./private/notes.md", b"text", {}) is not None


def test_ordinary_files_pass() -> None:
    assert guard.find_violation("src/ledgerlens/__init__.py", b'"""Docstring."""', {}) is None


def test_allowlist_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    listing = tmp_path / "allowed.sha256"
    listing.write_text("# a comment\n\nabc123  tests/fixtures/filing.pdf\n", encoding="utf-8")
    assert guard.load_allowlist(listing) == {"tests/fixtures/filing.pdf": "abc123"}


def test_missing_allowlist_is_empty(tmp_path: Path) -> None:
    assert guard.load_allowlist(tmp_path / "missing") == {}


def test_check_files_reports_blocked_files_and_skips_deleted_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("report.pdf").write_bytes(PDF_BYTES)
    Path("notes.md").write_text("fine", encoding="utf-8")

    problems = guard.check_files(["report.pdf", "notes.md", "deleted.pdf"], {})

    assert len(problems) == 1
    assert problems[0].startswith("report.pdf: ")


def test_main_returns_one_and_names_the_blocked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("report.pdf").write_bytes(PDF_BYTES)

    assert guard.main(["report.pdf"]) == 1
    assert "report.pdf" in capsys.readouterr().err


def test_main_returns_zero_with_nothing_to_check() -> None:
    assert guard.main([]) == 0


def test_source_code_that_quotes_the_header_passes() -> None:
    # Regression: the first version blocked this very script and its tests.
    source = b'"""Docstring."""\nPDF_HEADER = b"%PDF-"\nPDF_BYTES = b"%PDF-1.7"\n'
    assert guard.find_violation("src/ledgerlens/parse/pdf.py", source, {}) is None


def test_every_tracked_file_in_this_repository_passes() -> None:
    assert guard.main(["--all"]) == 0
