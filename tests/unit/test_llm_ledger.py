from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ledgerlens.core.llm.contracts import Usage
from ledgerlens.core.llm.errors import LedgerError, SpendCapError
from ledgerlens.core.llm.ledger import CallRecord, CallStatus, Ledger

RECORD = CallRecord(
    at=datetime(2026, 11, 15, tzinfo=UTC), provider="paid", model="paid-model", role="worker"
)
MONTH = "2026-11"
USAGE = Usage(input_tokens=10, cached_tokens=4, output_tokens=5)


def test_a_record_counts_towards_its_calendar_month() -> None:
    assert RECORD.month == MONTH


def test_a_reservation_counts_until_it_is_settled(ledger: Ledger) -> None:
    reservation = ledger.reserve(RECORD, 100, 1000)
    assert ledger.month_total_micro_inr(MONTH) == 100

    ledger.settle(reservation, USAGE, 30)

    assert ledger.month_total_micro_inr(MONTH) == 30
    (row,) = ledger.rows()
    assert row.status is CallStatus.SETTLED
    assert (row.input_tokens, row.cached_tokens, row.output_tokens) == (10, 4, 5)


def test_a_settled_cost_above_the_reservation_is_recorded_truthfully(ledger: Ledger) -> None:
    reservation = ledger.reserve(RECORD, 100, 100)

    ledger.settle(reservation, USAGE, 150)

    assert ledger.month_total_micro_inr(MONTH) == 150
    with pytest.raises(SpendCapError):
        ledger.reserve(RECORD, 1, 100)


def test_release_cancels_the_cost(ledger: Ledger) -> None:
    ledger.release(ledger.reserve(RECORD, 100, 1000))

    assert ledger.month_total_micro_inr(MONTH) == 0
    assert ledger.rows()[0].status is CallStatus.RELEASED


def test_an_unknown_outcome_keeps_the_worst_case(ledger: Ledger) -> None:
    ledger.mark_unknown(ledger.reserve(RECORD, 100, 1000))

    assert ledger.month_total_micro_inr(MONTH) == 100
    assert ledger.rows()[0].status is CallStatus.UNKNOWN


def test_a_crash_after_reserving_stays_counted(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    Ledger(path).reserve(RECORD, 100, 1000)

    assert Ledger(path).month_total_micro_inr(MONTH) == 100


def test_a_reservation_can_only_be_closed_once(ledger: Ledger) -> None:
    reservation = ledger.reserve(RECORD, 100, 1000)
    ledger.settle(reservation, USAGE, 30)

    with pytest.raises(LedgerError, match="isn't open"):
        ledger.release(reservation)

    assert ledger.month_total_micro_inr(MONTH) == 30


def test_a_refused_reservation_leaves_no_row(ledger: Ledger) -> None:
    with pytest.raises(SpendCapError):
        ledger.reserve(RECORD, 101, 100)

    assert ledger.rows() == []


def test_the_refusal_says_what_happened(ledger: Ledger) -> None:
    ledger.reserve(RECORD, 500_000, 1_000_000)

    with pytest.raises(SpendCapError) as refusal:
        ledger.reserve(RECORD, 600_000, 1_000_000)

    message = str(refusal.value)
    assert MONTH in message
    assert "₹0.5000" in message
    assert "₹1.00" in message
    assert "₹0.6000" in message


def test_a_free_call_is_never_refused(ledger: Ledger) -> None:
    ledger.reserve(RECORD, 100, 100)

    ledger.reserve(RECORD, 0, 100)

    assert len(ledger.rows()) == 2


def test_a_free_call_still_runs_when_spending_is_over_the_cap(ledger: Ledger) -> None:
    ledger.settle(ledger.reserve(RECORD, 100, 100), USAGE, 150)

    ledger.reserve(RECORD, 0, 100)

    assert len(ledger.rows()) == 2


def test_a_cache_hit_costs_nothing_and_keeps_its_tokens(ledger: Ledger) -> None:
    ledger.record_cache_hit(RECORD, USAGE)

    (row,) = ledger.rows()
    assert row.cache_hit is True
    assert row.cost_micro_inr == 0
    assert row.output_tokens == 5


def test_parallel_calls_cannot_overspend_together(ledger: Ledger) -> None:
    def try_to_reserve(_: int) -> bool:
        try:
            ledger.reserve(RECORD, 1, 50)
        except SpendCapError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(try_to_reserve, range(200)))

    assert sum(results) == 50
    assert ledger.month_total_micro_inr(MONTH) == 50


def test_a_damaged_file_is_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "damaged.sqlite3"
    path.write_bytes(b"this is not a database" * 100)

    with pytest.raises(LedgerError, match="can't use the ledger"):
        Ledger(path)


def test_a_folder_that_cannot_be_created_is_a_clear_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("in the way", encoding="utf-8")

    with pytest.raises(LedgerError, match="can't create"):
        Ledger(blocker / "ledger.sqlite3")
