from collections.abc import Iterator
from types import TracebackType
from typing import Self
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient

from ledgerlens.api import app as api


class FakeConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def execute(self, query: str) -> None:
        self.queries.append(query)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(api.app) as test_client:
        yield test_client
    api.app.dependency_overrides.clear()


def test_health_needs_no_database(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connect = MagicMock(side_effect=AssertionError("/health must not touch the database"))
    monkeypatch.setattr(psycopg, "connect", connect)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    connect.assert_not_called()


def test_ready_passes_when_the_database_answers(client: TestClient) -> None:
    api.app.dependency_overrides[api.database_is_reachable] = lambda: True

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_fails_when_the_database_does_not_answer(client: TestClient) -> None:
    api.app.dependency_overrides[api.database_is_reachable] = lambda: False

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unreachable"}


def test_database_check_runs_a_query(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(psycopg, "connect", lambda **_: connection)

    assert api.database_is_reachable() is True
    assert connection.queries == ["SELECT 1"]


def test_database_check_reports_a_failed_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psycopg, "connect", MagicMock(side_effect=psycopg.OperationalError))

    assert api.database_is_reachable() is False
