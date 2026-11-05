import subprocess
import time
from collections.abc import Iterator

import httpx2
import pytest

API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:5173"
COMPOSE = ["docker", "compose", "--env-file", ".env", "--file", "deploy/compose.yaml"]
RECOVERY_SECONDS = 60


def get(url: str) -> httpx2.Response:
    return httpx2.get(url, timeout=10)


def compose(*arguments: str) -> str:
    result = subprocess.run([*COMPOSE, *arguments], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def wait_until_ready() -> None:
    deadline = time.monotonic() + RECOVERY_SECONDS
    while time.monotonic() < deadline:
        if get(f"{API}/ready").status_code == 200:
            return
        time.sleep(0.5)
    pytest.fail("the API did not recover after Postgres restarted")


@pytest.fixture(scope="module", autouse=True)
def running_stack() -> None:
    try:
        get(f"{API}/health")
    except httpx2.TransportError:
        pytest.fail("the stack isn't running: start it with make up")


@pytest.fixture
def stopped_postgres() -> Iterator[None]:
    compose("stop", "postgres")
    try:
        yield
    finally:
        compose("start", "postgres")
        wait_until_ready()


def test_the_api_is_up() -> None:
    response = get(f"{API}/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_api_reaches_the_database() -> None:
    assert get(f"{API}/ready").status_code == 200


def test_the_web_app_is_served() -> None:
    response = get(f"{WEB}/")

    assert response.status_code == 200
    assert 'id="root"' in response.text


def test_the_web_server_proxies_the_api() -> None:
    response = get(f"{WEB}/api/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_postgres_has_pgvector() -> None:
    version = compose(
        "exec",
        "--no-TTY",
        "postgres",
        "psql",
        "--username=ledgerlens",
        "--dbname=ledgerlens",
        "--tuples-only",
        "--no-align",
        "--command=CREATE EXTENSION IF NOT EXISTS vector",
        "--command=SELECT extversion FROM pg_extension WHERE extname = 'vector'",
    )

    assert version.splitlines()[-1].count(".") == 2


@pytest.mark.parametrize("service", ["api", "web"])
def test_the_app_containers_do_not_run_as_root(service: str) -> None:
    assert compose("exec", "--no-TTY", service, "id", "-u") != "0"


@pytest.mark.usefixtures("stopped_postgres")
def test_a_database_outage_fails_ready_but_not_health() -> None:
    assert get(f"{API}/health").status_code == 200
    assert get(f"{API}/ready").status_code == 503
    assert get(f"{WEB}/api/ready").status_code == 503
