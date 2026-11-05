import contextlib
import tempfile
from collections.abc import Generator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from llm_helpers import NOW, ClientFactory, make_config

from ledgerlens.core.llm.cache import ResponseCache
from ledgerlens.core.llm.client import (
    TOKEN_ALLOWANCE_PER_MESSAGE,
    LLMClient,
    input_token_bound,
)
from ledgerlens.core.llm.config import load_llm_config
from ledgerlens.core.llm.contracts import (
    Completion,
    LLMRequest,
    LLMResponse,
    Message,
    TextDelta,
    Usage,
)
from ledgerlens.core.llm.errors import (
    IncompleteStreamError,
    LedgerError,
    ProviderRejectedError,
    SpendCapError,
    UnknownPriceError,
    UnknownProviderError,
    UnknownRoleError,
)
from ledgerlens.core.llm.ledger import CallStatus, Ledger
from ledgerlens.core.llm.providers.fake import FakeProvider

PROMPT = (Message(role="user", content="What was revenue?"),)
MONTH = "2026-11"

# The prompt is 17 bytes plus the allowance, and the output limit is 100 tokens at $2 per million.
WORST_CASE_MICRO_INR = (17 + TOKEN_ALLOWANCE_PER_MESSAGE) * 1 + 100 * 2
ACTUAL_MICRO_INR = 10 * 1 + 5 * 2


def chat(client: LLMClient, role: str = "worker", sample: int = 0) -> LLMResponse:
    return client.chat(role, PROMPT, max_output_tokens=100, sample=sample)


def test_a_call_records_its_tokens_and_cost(make_client: ClientFactory, ledger: Ledger) -> None:
    provider = FakeProvider()

    response = chat(make_client(provider))

    assert response.text == "answer 1"
    assert response.cache_hit is False
    assert response.cost_inr == Decimal(ACTUAL_MICRO_INR) / 1_000_000
    (row,) = ledger.rows()
    assert row.status is CallStatus.SETTLED
    assert (row.input_tokens, row.output_tokens) == (10, 5)
    assert row.cost_micro_inr == ACTUAL_MICRO_INR
    assert (row.provider, row.model, row.role) == ("paid", "paid-model", "worker")


def test_the_default_clock_is_utc(ledger: Ledger, cache: ResponseCache) -> None:
    client = LLMClient(
        config=make_config(),
        ledger=ledger,
        cache=cache,
        providers={"paid": FakeProvider()},
    )

    chat(client)

    assert ledger.rows()[0].at.tzinfo == UTC


def test_the_run_id_reaches_the_ledger(make_client: ClientFactory, ledger: Ledger) -> None:
    make_client(FakeProvider()).chat("worker", PROMPT, max_output_tokens=100, run_id="run-7")

    assert ledger.rows()[0].run_id == "run-7"


def test_a_repeat_call_costs_nothing(make_client: ClientFactory, ledger: Ledger) -> None:
    provider = FakeProvider()
    client = make_client(provider)

    first = chat(client)
    second = chat(client)

    assert len(provider.requests) == 1
    assert second.text == first.text
    assert second.cache_hit is True
    assert second.cost_inr == 0
    assert ledger.month_total_micro_inr(MONTH) == ACTUAL_MICRO_INR
    assert [row.cache_hit for row in ledger.rows()] == [False, True]


def test_three_samples_are_three_real_calls(make_client: ClientFactory, ledger: Ledger) -> None:
    provider = FakeProvider()
    client = make_client(provider)

    samples = [chat(client, sample=number) for number in range(3)]

    assert len(provider.requests) == 3
    assert len({response.text for response in samples}) == 3
    assert not any(response.cache_hit for response in samples)
    assert ledger.month_total_micro_inr(MONTH) == 3 * ACTUAL_MICRO_INR


def test_each_sample_has_its_own_cache_entry(make_client: ClientFactory) -> None:
    provider = FakeProvider()
    client = make_client(provider)
    first_pass = [chat(client, sample=number).text for number in range(3)]

    second_pass = [chat(client, sample=number) for number in range(3)]

    assert len(provider.requests) == 3
    assert [response.text for response in second_pass] == first_pass
    assert all(response.cache_hit for response in second_pass)


def test_the_cap_stops_a_call_before_anything_is_sent(
    make_client: ClientFactory, ledger: Ledger
) -> None:
    provider = FakeProvider()

    with pytest.raises(SpendCapError, match="Nothing was sent"):
        chat(make_client(provider, cap_inr="0"))

    assert provider.requests == []
    assert ledger.rows() == []


def test_a_call_that_exactly_fits_the_cap_is_allowed(make_client: ClientFactory) -> None:
    provider = FakeProvider()
    cap = str(Decimal(WORST_CASE_MICRO_INR) / 1_000_000)

    chat(make_client(provider, cap_inr=cap))

    assert len(provider.requests) == 1


def test_the_cap_counts_the_worst_case_and_not_the_likely_cost(
    make_client: ClientFactory,
) -> None:
    provider = FakeProvider()
    just_under = str(Decimal(WORST_CASE_MICRO_INR - 1) / 1_000_000)

    with pytest.raises(SpendCapError):
        chat(make_client(provider, cap_inr=just_under))

    assert provider.requests == []


def test_spending_builds_up_until_the_cap_refuses(
    make_client: ClientFactory, ledger: Ledger
) -> None:
    provider = FakeProvider()
    cap_micro_inr = WORST_CASE_MICRO_INR + 3 * ACTUAL_MICRO_INR
    client = make_client(provider, cap_inr=str(Decimal(cap_micro_inr) / 1_000_000))

    for sample in range(4):
        chat(client, sample=sample)

    with pytest.raises(SpendCapError):
        chat(client, sample=4)

    assert len(provider.requests) == 4
    assert ledger.month_total_micro_inr(MONTH) == 4 * ACTUAL_MICRO_INR


def test_the_cap_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    cap = str(Decimal(WORST_CASE_MICRO_INR + ACTUAL_MICRO_INR - 1) / 1_000_000)

    def fresh_client(provider: FakeProvider) -> LLMClient:
        return LLMClient(
            config=make_config(cap),
            ledger=Ledger(path),
            cache=ResponseCache(tmp_path / "cache"),
            providers={"paid": provider},
            now=lambda: NOW,
        )

    chat(fresh_client(FakeProvider()))
    restarted = FakeProvider()

    with pytest.raises(SpendCapError):
        chat(fresh_client(restarted), sample=1)

    assert restarted.requests == []


def test_a_new_month_starts_fresh(make_client: ClientFactory) -> None:
    cap = str(Decimal(WORST_CASE_MICRO_INR) / 1_000_000)
    provider = FakeProvider()
    chat(make_client(provider, cap_inr=cap))
    with pytest.raises(SpendCapError):
        chat(make_client(provider, cap_inr=cap), sample=1)

    next_month = make_client(provider, cap_inr=cap, now=datetime(2026, 12, 1, tzinfo=UTC))

    assert chat(next_month, sample=1).cache_hit is False


def test_a_free_model_runs_at_a_zero_cap(make_client: ClientFactory) -> None:
    provider = FakeProvider()

    response = chat(make_client(provider, cap_inr="0"), role="local")

    assert response.cost_inr == 0
    assert len(provider.requests) == 1


def test_a_free_model_keeps_running_once_the_budget_is_gone(
    make_client: ClientFactory, ledger: Ledger
) -> None:
    provider = FakeProvider()
    client = make_client(provider, cap_inr=str(Decimal(WORST_CASE_MICRO_INR) / 1_000_000))
    chat(client)
    with pytest.raises(SpendCapError):
        chat(client, sample=1)

    assert chat(client, role="local").cost_inr == 0
    assert ledger.month_total_micro_inr(MONTH) == ACTUAL_MICRO_INR


def test_a_cached_answer_is_served_when_the_budget_is_gone(make_client: ClientFactory) -> None:
    provider = FakeProvider()
    chat(make_client(provider))

    assert chat(make_client(provider, cap_inr="0")).cache_hit is True


@pytest.mark.parametrize(
    ("role", "error"),
    [
        ("no-such-role", UnknownRoleError),
        ("unwired", UnknownProviderError),
        ("unpriced", UnknownPriceError),
    ],
)
def test_anything_unknown_stops_the_call(
    make_client: ClientFactory, ledger: Ledger, role: str, error: type[Exception]
) -> None:
    provider = FakeProvider()

    with pytest.raises(error):
        chat(make_client(provider), role=role)

    assert provider.requests == []
    assert ledger.rows() == []


def test_the_shipped_config_runs_local_roles_and_refuses_hosted_ones(
    ledger: Ledger, cache: ResponseCache
) -> None:
    provider = FakeProvider()
    client = LLMClient(
        config=load_llm_config(Path("config")),
        ledger=ledger,
        cache=cache,
        providers={"openai_compatible": provider, "anthropic": provider, "google": provider},
        now=lambda: NOW,
    )

    assert client.chat("generator", PROMPT, max_output_tokens=100).cost_inr == 0
    for hosted_role in ("judge", "showcase"):
        with pytest.raises(SpendCapError):
            client.chat(hosted_role, PROMPT, max_output_tokens=100)

    assert len(provider.requests) == 1


def test_a_broken_ledger_stops_the_call(
    tmp_path: Path, cache: ResponseCache, ledger: Ledger, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider()
    client = LLMClient(
        config=make_config(),
        ledger=ledger,
        cache=cache,
        providers={"paid": provider},
        now=lambda: NOW,
    )
    damaged = tmp_path / "damaged.sqlite3"
    damaged.write_bytes(b"this is not a database" * 100)
    monkeypatch.setattr(ledger, "_path", damaged)

    with pytest.raises(LedgerError):
        chat(client)

    assert provider.requests == []


def test_a_refused_request_gives_the_reservation_back(
    make_client: ClientFactory, ledger: Ledger
) -> None:
    provider = FakeProvider(failure=ProviderRejectedError("bad request"))

    with pytest.raises(ProviderRejectedError):
        chat(make_client(provider))

    (row,) = ledger.rows()
    assert row.status is CallStatus.RELEASED
    assert ledger.month_total_micro_inr(MONTH) == 0


def test_a_failed_call_stays_counted_because_it_may_be_billed(
    make_client: ClientFactory, ledger: Ledger
) -> None:
    provider = FakeProvider(failure=TimeoutError("no answer"))

    with pytest.raises(TimeoutError):
        chat(make_client(provider))

    (row,) = ledger.rows()
    assert row.status is CallStatus.UNKNOWN
    assert ledger.month_total_micro_inr(MONTH) == WORST_CASE_MICRO_INR


def test_a_failed_call_is_not_cached(make_client: ClientFactory) -> None:
    failing = FakeProvider(failure=TimeoutError("no answer"))
    with pytest.raises(TimeoutError):
        chat(make_client(failing))
    working = FakeProvider()

    response = chat(make_client(working))

    assert response.cache_hit is False
    assert len(working.requests) == 1


def test_a_paid_answer_survives_a_cache_write_failure(
    make_client: ClientFactory, cache: ResponseCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_key: str, _completion: Completion) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(cache, "put", fail)

    assert chat(make_client(FakeProvider())).text == "answer 1"


def test_a_call_over_the_threshold_is_priced_at_long_context_rates(
    make_client: ClientFactory, ledger: Ledger
) -> None:
    provider = FakeProvider(usage=Usage(input_tokens=2000, output_tokens=10))

    chat(make_client(provider))

    assert ledger.rows()[0].cost_micro_inr == 2000 * 10 + 10 * 20


def test_the_reservation_uses_long_context_rates_for_a_long_prompt(
    make_client: ClientFactory,
) -> None:
    provider = FakeProvider()
    long_prompt = (Message(role="user", content="x" * 2000),)
    at_normal_rates = str(Decimal(2000 + TOKEN_ALLOWANCE_PER_MESSAGE + 200) / 1_000_000)

    with pytest.raises(SpendCapError):
        make_client(provider, cap_inr=at_normal_rates).chat(
            "worker", long_prompt, max_output_tokens=100
        )

    assert provider.requests == []


def test_the_bound_is_never_below_the_byte_count() -> None:
    messages = (
        Message(role="system", content="naïve ₹"),
        Message(role="user", content="日本語"),
    )

    assert input_token_bound(messages) == len("naïve ₹".encode()) + len("日本語".encode()) + 32


def collect(events: Iterator[TextDelta | LLMResponse]) -> tuple[list[str], LLMResponse]:
    items = list(events)
    final = items[-1]
    assert isinstance(final, LLMResponse)
    return [item.text for item in items[:-1] if isinstance(item, TextDelta)], final


def stream(client: LLMClient) -> Generator[TextDelta | LLMResponse]:
    yield from client.stream("worker", PROMPT, max_output_tokens=100)


def test_a_stream_delivers_text_then_the_final_response(
    make_client: ClientFactory, ledger: Ledger
) -> None:
    pieces, final = collect(stream(make_client(FakeProvider())))

    assert pieces == ["answer", "1"]
    assert final.text == "answer 1"
    assert final.cache_hit is False
    assert ledger.rows()[0].status is CallStatus.SETTLED
    assert ledger.month_total_micro_inr(MONTH) == ACTUAL_MICRO_INR


def test_a_repeat_stream_costs_nothing(make_client: ClientFactory, ledger: Ledger) -> None:
    provider = FakeProvider()
    client = make_client(provider)
    collect(stream(client))

    pieces, final = collect(stream(client))

    assert pieces == ["answer 1"]
    assert final.cache_hit is True
    assert len(provider.requests) == 1
    assert ledger.month_total_micro_inr(MONTH) == ACTUAL_MICRO_INR


def test_the_cap_stops_a_stream_before_anything_is_sent(make_client: ClientFactory) -> None:
    provider = FakeProvider()

    with pytest.raises(SpendCapError):
        next(stream(make_client(provider, cap_inr="0")))

    assert provider.requests == []


def test_an_abandoned_stream_stays_counted_and_uncached(
    make_client: ClientFactory, ledger: Ledger
) -> None:
    provider = FakeProvider()
    client = make_client(provider)
    events = stream(client)

    next(events)
    events.close()

    (row,) = ledger.rows()
    assert row.status is CallStatus.UNKNOWN
    assert ledger.month_total_micro_inr(MONTH) == WORST_CASE_MICRO_INR
    assert chat(client).cache_hit is False


def test_a_stream_that_never_finishes_stays_counted(
    make_client: ClientFactory, ledger: Ledger
) -> None:
    class CutOffProvider(FakeProvider):
        def stream(self, request: LLMRequest) -> Iterator[TextDelta | Completion]:
            self.requests.append(request)
            yield TextDelta(text="half an ans")

    with pytest.raises(IncompleteStreamError):
        list(stream(make_client(CutOffProvider())))

    assert ledger.rows()[0].status is CallStatus.UNKNOWN


def test_a_refused_stream_gives_the_reservation_back(
    make_client: ClientFactory, ledger: Ledger
) -> None:
    provider = FakeProvider(failure=ProviderRejectedError("bad request"))

    with pytest.raises(ProviderRejectedError):
        list(stream(make_client(provider)))

    assert ledger.month_total_micro_inr(MONTH) == 0


@settings(deadline=None, max_examples=25)
@given(
    prompts=st.lists(st.text(max_size=40), min_size=1, max_size=12),
    cap_micro_inr=st.integers(min_value=0, max_value=2000),
)
def test_no_sequence_of_calls_spends_past_the_cap(prompts: list[str], cap_micro_inr: int) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = Ledger(root / "ledger.sqlite3")
        client = LLMClient(
            config=make_config(str(Decimal(cap_micro_inr) / 1_000_000)),
            ledger=ledger,
            cache=ResponseCache(root / "cache"),
            providers={"paid": FakeProvider(usage=Usage(input_tokens=5, output_tokens=5))},
            now=lambda: NOW,
        )

        for number, prompt in enumerate(prompts):
            message = (Message(role="user", content=prompt),)
            with contextlib.suppress(SpendCapError):
                client.chat("worker", message, max_output_tokens=50, sample=number)

        assert ledger.month_total_micro_inr(MONTH) <= cap_micro_inr
