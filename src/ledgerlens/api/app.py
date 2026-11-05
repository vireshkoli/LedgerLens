"""HTTP API for LedgerLens.

There are two probes, so a database outage never looks like a dead process: `/health` only says
the process is up, and `/ready` also proves Postgres answers.
"""

from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel

CONNECT_TIMEOUT_SECONDS = 2

app = FastAPI(title="LedgerLens")


class ProbeResult(BaseModel):
    """The body of a successful probe."""

    status: Literal["ok"] = "ok"


def database_is_reachable() -> bool:
    """Check that Postgres answers a query.

    Settings come from the standard `PG*` environment variables, so a password never has to be
    escaped into a connection URL.

    Returns:
        True if the query ran.
    """
    try:
        with psycopg.connect(connect_timeout=CONNECT_TIMEOUT_SECONDS) as connection:
            connection.execute("SELECT 1")
    except psycopg.OperationalError:
        return False
    return True


@app.get("/health")
def health() -> ProbeResult:
    """Report that the process is up."""
    return ProbeResult()


@app.get("/ready")
def ready(database_ok: Annotated[bool, Depends(database_is_reachable)]) -> ProbeResult:
    """Report that the API can serve requests.

    Args:
        database_ok: Whether Postgres answered.

    Returns:
        An ok result.

    Raises:
        HTTPException: 503 if Postgres did not answer.
    """
    if not database_ok:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unreachable")
    return ProbeResult()
