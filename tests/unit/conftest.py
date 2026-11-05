from datetime import datetime
from pathlib import Path

import pytest
from llm_helpers import NOW, ClientFactory, make_config

from ledgerlens.core.llm.cache import ResponseCache
from ledgerlens.core.llm.client import LLMClient
from ledgerlens.core.llm.ledger import Ledger
from ledgerlens.core.llm.providers.base import Provider


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    return Ledger(tmp_path / "llm" / "ledger.sqlite3")


@pytest.fixture
def cache(tmp_path: Path) -> ResponseCache:
    return ResponseCache(tmp_path / "llm" / "cache")


@pytest.fixture
def make_client(ledger: Ledger, cache: ResponseCache) -> ClientFactory:
    def build(provider: Provider, *, cap_inr: str = "1", now: datetime = NOW) -> LLMClient:
        return LLMClient(
            config=make_config(cap_inr),
            ledger=ledger,
            cache=cache,
            providers={"paid": provider, "free": provider},
            now=lambda: now,
        )

    return build
