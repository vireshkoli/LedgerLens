import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledgerlens.core.llm.cache import ResponseCache, cache_key
from ledgerlens.core.llm.contracts import Completion, LLMRequest, Message, Usage

REQUEST = LLMRequest(
    provider="paid",
    model="paid-model",
    messages=(Message(role="user", content="What was revenue?"),),
    max_output_tokens=100,
)
COMPLETION = Completion(
    text="Revenue was ₹5.",
    usage=Usage(input_tokens=10, output_tokens=5),
    model="paid-model",
    finish_reason="stop",
)


def test_the_same_request_has_the_same_key() -> None:
    assert cache_key(REQUEST) == cache_key(REQUEST.model_copy())


@pytest.mark.parametrize(
    "changed",
    [
        {"provider": "other"},
        {"model": "other-model"},
        {"messages": (Message(role="user", content="What was profit?"),)},
        {"messages": (Message(role="system", content="What was revenue?"),)},
        {"max_output_tokens": 101},
        {"sample": 1},
    ],
)
def test_anything_that_decides_a_response_changes_the_key(changed: dict[str, object]) -> None:
    assert cache_key(REQUEST.model_copy(update=changed)) != cache_key(REQUEST)


@given(samples=st.lists(st.integers(min_value=0, max_value=1000), unique=True, max_size=20))
def test_every_sample_has_its_own_key(samples: list[int]) -> None:
    keys = {cache_key(REQUEST.model_copy(update={"sample": sample})) for sample in samples}

    assert len(keys) == len(samples)


def test_a_key_is_stable_across_processes() -> None:
    # A fixed value, so a change to the key's recipe can't silently orphan the committed replays.
    assert cache_key(REQUEST) == "8d4291f64107377ae93c2ad28170666bb3457e5975e700cb22f54fe21b3f5397"


def test_a_missing_entry_is_a_miss(cache: ResponseCache) -> None:
    assert cache.get("0" * 64) is None


def test_an_entry_round_trips(cache: ResponseCache) -> None:
    key = cache_key(REQUEST)

    cache.put(key, COMPLETION)

    assert cache.get(key) == COMPLETION


def test_a_damaged_entry_is_a_miss(cache: ResponseCache) -> None:
    key = cache_key(REQUEST)
    cache.put(key, COMPLETION)
    entry = next(path for path in cache._root.rglob("*.json"))
    entry.write_text('{"text": "half an entr', encoding="utf-8")

    assert cache.get(key) is None


def test_writing_leaves_no_temporary_files(cache: ResponseCache) -> None:
    cache.put(cache_key(REQUEST), COMPLETION)

    assert list(cache._root.rglob("*.tmp")) == []
