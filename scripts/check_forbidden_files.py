"""Block files that must never reach the public repository.

Company PDFs and FinanceBench data have licence limits, and the private tier is for personal
use only. Git history is permanent and this repository is public, so the check runs twice: as a
pre-commit hook for fast feedback, and in CI because a local hook can be skipped. CI reads the
whole history, because a file removed in a later commit is still public in the earlier one.

A PDF may be committed only if the allow-list names it with its SHA-256. Without the hash, a
different file could quietly take the place of an approved one.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath

ALLOWLIST_PATH = Path("config/allowed_fixtures.sha256")

# The PDF format allows the header anywhere in the first 1,024 bytes, and a renamed file keeps
# its content, so checking the extension alone would miss a PDF saved under another name.
PDF_HEADER = b"%PDF-"
PDF_HEADER_WINDOW = 1024
PDF_HEADER_AT_LINE_START = re.compile(rb"(?:\A|[\r\n])%PDF-\d")

PRIVATE_PREFIXES = ("private/", "data/private/")

# Source code and docs may mention FinanceBench freely, so only data formats are inspected.
DATA_SUFFIXES = frozenset(
    {
        ".arrow",
        ".csv",
        ".gz",
        ".json",
        ".jsonl",
        ".ndjson",
        ".parquet",
        ".tsv",
        ".txt",
        ".xlsx",
        ".zip",
    }
)
FINANCEBENCH_NAME = "financebench"
FINANCEBENCH_MARKER = b"financebench_id"

GIT_SUBMODULE_MODE = "160000"


def load_allowlist(path: Path) -> dict[str, str]:
    """Read an allow-list file.

    Args:
        path: File of `<sha256>  <path>` lines. Blank lines and `#` comments are skipped.

    Returns:
        A mapping from repository path to expected SHA-256. Empty if the file doesn't exist.
    """
    if not path.exists():
        return {}
    entries: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            digest, _, listed_path = line.partition("  ")
            entries[listed_path] = digest
    return entries


def looks_like_pdf(content: bytes) -> bool:
    """Detect a PDF by its content, whatever the file is called.

    Source code that handles PDFs quotes the header as ordinary text, so finding the header
    isn't enough. A real PDF has it at the start of a line, or sits in binary content.

    Args:
        content: The file's bytes.

    Returns:
        True if the content looks like a PDF.
    """
    window = content[:PDF_HEADER_WINDOW]
    if PDF_HEADER_AT_LINE_START.search(window):
        return True
    return PDF_HEADER in window and b"\0" in content


def find_violation(path: str, content: bytes, allowlist: Mapping[str, str]) -> str | None:
    """Decide whether one file may be committed.

    Args:
        path: Repository-relative path, using forward slashes.
        content: The file's bytes.
        allowlist: Approved PDFs, as returned by `load_allowlist`.

    Returns:
        The reason the file is blocked, or None if it may be committed.
    """
    posix_path = PurePosixPath(path)
    normalised = posix_path.as_posix()

    if normalised.lower().startswith(PRIVATE_PREFIXES):
        return "private-tier files never leave your Mac"

    is_pdf = posix_path.suffix.lower() == ".pdf" or looks_like_pdf(content)
    if is_pdf and allowlist.get(normalised) != hashlib.sha256(content).hexdigest():
        return "PDFs are blocked unless listed with their hash in " + str(ALLOWLIST_PATH)

    if posix_path.suffix.lower() in DATA_SUFFIXES:
        if FINANCEBENCH_NAME in normalised.lower():
            return "FinanceBench data is fetched by script and never committed"
        if FINANCEBENCH_MARKER in content:
            return "file contains FinanceBench records"

    return None


def check_files(paths: Iterable[str], allowlist: Mapping[str, str]) -> list[str]:
    """Check files on disk.

    Args:
        paths: Repository-relative paths. Paths that aren't files, such as deletions, are skipped.
        allowlist: Approved PDFs, as returned by `load_allowlist`.

    Returns:
        One `path: reason` line for each blocked file.
    """
    problems = []
    for path in paths:
        file = Path(path)
        if file.is_file():
            reason = find_violation(path, file.read_bytes(), allowlist)
            if reason is not None:
                problems.append(f"{path}: {reason}")
    return problems


def tracked_files() -> list[str]:
    """List every file Git tracks, including names with spaces or unusual characters."""
    result = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True)
    return [name for name in result.stdout.decode().split("\0") if name]


def is_shallow_clone() -> bool:
    """Report whether older commits are missing from this clone."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "true"


def history_versions() -> set[tuple[str, str]]:
    """List every version of every file in the history of HEAD.

    A file that only a merge commit added would be skipped without `--diff-merges=separate`, and
    renames are reported as additions so that a file's earlier path is checked too.

    Returns:
        (path, blob ID) pairs, including files that later commits changed or removed.
    """
    result = subprocess.run(
        [
            "git",
            "log",
            "--format=",
            "--raw",
            "--no-abbrev",
            "--no-renames",
            "--diff-merges=separate",
            "--diff-filter=d",
            "-z",
            "HEAD",
        ],
        check=True,
        capture_output=True,
    )
    fields = result.stdout.split(b"\0")
    versions = set()
    for status, name in zip(fields[0::2], fields[1::2], strict=False):
        _, mode, _, blob, _ = status.decode().split()
        if mode != GIT_SUBMODULE_MODE:
            versions.add((os.fsdecode(name), blob))
    return versions


def check_history(allowlist: Mapping[str, str]) -> list[str]:
    """Check every version of every file in the history of HEAD.

    Args:
        allowlist: Approved PDFs, as returned by `load_allowlist`.

    Returns:
        One `path (blob id): reason` line for each blocked version.
    """
    # A shallow clone would look clean only because the older commits aren't there to read.
    if is_shallow_clone():
        return ["this clone is shallow, so its history can't be checked: fetch all of it"]

    problems = []
    for path, blob in sorted(history_versions()):
        content = subprocess.run(
            ["git", "cat-file", "blob", blob], check=True, capture_output=True
        ).stdout
        reason = find_violation(path, content, allowlist)
        if reason is not None:
            problems.append(f"{path} (blob {blob}): {reason}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check.

    Args:
        argv: Command-line arguments. Defaults to `sys.argv`.

    Returns:
        0 if every file may be committed, otherwise 1.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="files to check, as pre-commit passes them")
    parser.add_argument("--all", action="store_true", help="check every file Git tracks")
    parser.add_argument(
        "--history", action="store_true", help="check every version of every committed file"
    )
    args = parser.parse_args(argv)

    allowlist = load_allowlist(ALLOWLIST_PATH)
    if args.history:
        problems = check_history(allowlist)
    else:
        problems = check_files(tracked_files() if args.all else args.paths, allowlist)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
