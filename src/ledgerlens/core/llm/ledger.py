"""A durable record of every call, and the place the spending cap is enforced.

Before a paid call, `reserve` adds a row holding that call's worst-case cost. The cap check and
the insert happen in one write transaction, so parallel calls and parallel processes can't all
pass the check together. Every row counts towards the month, whatever its status, so a call that
crashes mid-flight stays counted at its worst case instead of vanishing.

SQLite is used because hosted runs happen on the Mac, where the cap must hold even when the
compose stack is down. Reservations rely only on the database's own locking, so a Postgres table
can take over when the API needs a cap shared between hosts.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from ledgerlens.core.llm.contracts import Contract, Usage
from ledgerlens.core.llm.errors import LedgerError, SpendCapError
from ledgerlens.core.llm.pricing import to_rupees

LOCK_WAIT_SECONDS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_ledger (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    month TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    role TEXT NOT NULL,
    run_id TEXT,
    status TEXT NOT NULL,
    cache_hit INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    cached_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_micro_inr INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_ledger_month ON llm_ledger (month);
"""

INSERT = """
INSERT INTO llm_ledger (
    at, month, provider, model, role, run_id, status, cache_hit,
    input_tokens, cached_tokens, output_tokens, cost_micro_inr
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
RETURNING id
"""
SETTLE = """
UPDATE llm_ledger
SET status = 'settled', input_tokens = ?, cached_tokens = ?, output_tokens = ?, cost_micro_inr = ?
WHERE id = ? AND status = 'reserved'
"""
RELEASE = """
UPDATE llm_ledger SET status = 'released', cost_micro_inr = 0
WHERE id = ? AND status = 'reserved'
"""
MARK_UNKNOWN = "UPDATE llm_ledger SET status = 'unknown' WHERE id = ? AND status = 'reserved'"
MONTH_TOTAL = "SELECT COALESCE(SUM(cost_micro_inr), 0) FROM llm_ledger WHERE month = ?"
ALL_ROWS = "SELECT * FROM llm_ledger ORDER BY id"


class CallStatus(StrEnum):
    """Where a ledger row stands."""

    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"
    UNKNOWN = "unknown"


class CallRecord(Contract):
    """What the ledger needs to know about a call."""

    at: datetime
    provider: str
    model: str
    role: str
    run_id: str | None = None

    @property
    def month(self) -> str:
        """The month the call counts towards, as `YYYY-MM`."""
        return self.at.strftime("%Y-%m")


class LedgerRow(Contract):
    """One row of the ledger."""

    id: int
    at: datetime
    month: str
    provider: str
    model: str
    role: str
    run_id: str | None
    status: CallStatus
    cache_hit: bool
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost_micro_inr: int


class Ledger:
    """The spending record, held in one SQLite file."""

    def __init__(self, path: Path) -> None:
        """Open the ledger, creating it if needed.

        Args:
            path: The SQLite file.

        Raises:
            LedgerError: If the file can't be opened as a ledger.
        """
        self._path = path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            message = f"can't create the ledger's folder for {path}: {error}"
            raise LedgerError(message) from error
        with self._connection() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(
                self._path, timeout=LOCK_WAIT_SECONDS, isolation_level=None
            )
            connection.row_factory = sqlite3.Row
            try:
                yield connection
            finally:
                connection.close()
        except sqlite3.Error as error:
            message = f"can't use the ledger at {self._path}: {error}"
            raise LedgerError(message) from error

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            # BEGIN IMMEDIATE takes the write lock before the first read, so the total a caller
            # checks can't change before its insert lands.
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")

    def reserve(self, record: CallRecord, worst_case_micro_inr: int, cap_micro_inr: int) -> int:
        """Set aside a call's worst-case cost, or refuse the call.

        A call that can't cost anything is never refused, because local models must keep working
        once the hosted budget is used up.

        Args:
            record: The call.
            worst_case_micro_inr: The most this call could cost.
            cap_micro_inr: The monthly cap.

        Returns:
            The reservation's ID.

        Raises:
            SpendCapError: If the call could take the month past the cap.
        """
        with self._write_transaction() as connection:
            spent = self._month_total(connection, record.month)
            if worst_case_micro_inr > 0 and spent + worst_case_micro_inr > cap_micro_inr:
                message = (
                    f"monthly LLM spend cap reached for {record.month}: "
                    f"₹{to_rupees(spent):.4f} of ₹{to_rupees(cap_micro_inr):.2f} is spent or "
                    f"reserved, and this call could cost up to "
                    f"₹{to_rupees(worst_case_micro_inr):.4f}. Nothing was sent."
                )
                raise SpendCapError(message)
            values = self._values(record, CallStatus.RESERVED, False, None, worst_case_micro_inr)
            return self._insert(connection, values)

    def settle(self, reservation: int, usage: Usage, cost_micro_inr: int) -> None:
        """Replace a reservation with what the call really cost.

        Args:
            reservation: From `reserve`.
            usage: The tokens the call used.
            cost_micro_inr: The real cost.
        """
        values = (usage.input_tokens, usage.cached_tokens, usage.output_tokens, cost_micro_inr)
        self._update(SETTLE, (*values, reservation))

    def release(self, reservation: int) -> None:
        """Cancel a reservation for a call that was certainly not billed.

        Args:
            reservation: From `reserve`.
        """
        self._update(RELEASE, (reservation,))

    def mark_unknown(self, reservation: int) -> None:
        """Flag a call that failed after it may have been billed.

        The worst-case amount stays counted: overstating spending is the safe mistake.

        Args:
            reservation: From `reserve`.
        """
        self._update(MARK_UNKNOWN, (reservation,))

    def record_cache_hit(self, record: CallRecord, usage: Usage) -> None:
        """Record a call the cache answered, at no cost.

        The tokens are the ones the original call used, which shows what the cache saved.

        Args:
            record: The call.
            usage: The tokens the cached response took.
        """
        with self._write_transaction() as connection:
            self._insert(connection, self._values(record, CallStatus.SETTLED, True, usage, 0))

    def month_total_micro_inr(self, month: str) -> int:
        """Add up a month's spending, including open reservations.

        Args:
            month: The month as `YYYY-MM`.

        Returns:
            The total in micro-rupees.
        """
        with self._connection() as connection:
            return self._month_total(connection, month)

    def rows(self) -> list[LedgerRow]:
        """Read every row, oldest first.

        Returns:
            The ledger's rows.
        """
        with self._connection() as connection:
            return [LedgerRow(**dict(row)) for row in connection.execute(ALL_ROWS)]

    def _update(self, statement: str, values: tuple[int, ...]) -> None:
        with self._write_transaction() as connection:
            if connection.execute(statement, values).rowcount != 1:
                message = f"reservation {values[-1]} isn't open"
                raise LedgerError(message)

    @staticmethod
    def _insert(connection: sqlite3.Connection, values: tuple[object, ...]) -> int:
        row_id: int = connection.execute(INSERT, values).fetchone()[0]
        return row_id

    @staticmethod
    def _month_total(connection: sqlite3.Connection, month: str) -> int:
        total: int = connection.execute(MONTH_TOTAL, (month,)).fetchone()[0]
        return total

    @staticmethod
    def _values(
        record: CallRecord,
        status: CallStatus,
        cache_hit: bool,
        usage: Usage | None,
        cost_micro_inr: int,
    ) -> tuple[object, ...]:
        tokens = usage or Usage(input_tokens=0, output_tokens=0)
        return (
            record.at.isoformat(),
            record.month,
            record.provider,
            record.model,
            record.role,
            record.run_id,
            status,
            cache_hit,
            tokens.input_tokens,
            tokens.cached_tokens,
            tokens.output_tokens,
            cost_micro_inr,
        )
