from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from llm_helpers import PAID_PRICE, make_pricing
from pydantic import ValidationError

from ledgerlens.core.llm.config import load_llm_config
from ledgerlens.core.llm.contracts import Usage
from ledgerlens.core.llm.errors import SpendCapError, UnknownPriceError, UnknownRoleError
from ledgerlens.core.llm.ledger import CallRecord, Ledger
from ledgerlens.core.llm.pricing import ExchangeRate, ModelPrice, PricingTable, to_rupees
from ledgerlens.core.llm.roles import RoleTable

CONFIG_DIRECTORY = Path("config")
TOKENS = st.integers(min_value=0, max_value=2_000_000)

REAL_RATE = PricingTable(
    last_verified=date(2026, 11, 5),
    exchange_rate=ExchangeRate(usd_inr=Decimal("94.86"), as_of=date(2026, 11, 3), source="test"),
    gst_rate=Decimal("0.18"),
    monthly_cap_inr=Decimal(1500),
    models={},
)
FLAT_PRICE = PAID_PRICE.model_copy(update={"long_context": None})


def test_a_known_call_costs_the_hand_worked_amount() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    price = FLAT_PRICE.model_copy(
        update={"input_usd": Decimal("0.10"), "output_usd": Decimal("0.50")}
    )

    # $0.60 at ₹94.86 is ₹56.916, and 18% GST makes it ₹67.16088.
    assert REAL_RATE.cost_micro_inr(price, usage) == 67_160_880


def test_cached_tokens_are_billed_at_the_cached_rate() -> None:
    usage = Usage(input_tokens=1000, cached_tokens=400, output_tokens=0)

    assert make_pricing().cost_micro_inr(FLAT_PRICE, usage) == 600 + 40


def test_the_long_context_rate_applies_to_the_whole_request() -> None:
    usage = Usage(input_tokens=1001, output_tokens=10)

    assert make_pricing().cost_micro_inr(PAID_PRICE, usage) == 1001 * 10 + 10 * 20


def test_a_request_exactly_at_the_threshold_stays_at_normal_rates() -> None:
    usage = Usage(input_tokens=1000, output_tokens=10)

    assert make_pricing().cost_micro_inr(PAID_PRICE, usage) == 1000 * 1 + 10 * 2


def test_cached_tokens_count_towards_the_threshold() -> None:
    usage = Usage(input_tokens=1001, cached_tokens=1000, output_tokens=0)

    assert make_pricing().cost_micro_inr(PAID_PRICE, usage) == 1 * 10 + 1000 * 1


def test_a_fraction_of_a_micro_rupee_rounds_up() -> None:
    price = FLAT_PRICE.model_copy(update={"input_usd": Decimal("0.001")})

    assert make_pricing().cost_micro_inr(price, Usage(input_tokens=1, output_tokens=0)) == 1


@given(input_tokens=TOKENS, output_tokens=TOKENS, more=st.integers(min_value=1, max_value=10_000))
def test_more_output_never_costs_less(input_tokens: int, output_tokens: int, more: int) -> None:
    pricing = make_pricing()
    fewer = Usage(input_tokens=input_tokens, output_tokens=output_tokens)
    extra = Usage(input_tokens=input_tokens, output_tokens=output_tokens + more)

    assert pricing.cost_micro_inr(PAID_PRICE, extra) > pricing.cost_micro_inr(PAID_PRICE, fewer)


@given(input_tokens=TOKENS, cached=st.floats(min_value=0, max_value=1), output_tokens=TOKENS)
def test_the_uncached_cost_bounds_the_cached_cost(
    input_tokens: int, cached: float, output_tokens: int
) -> None:
    pricing = make_pricing()
    uncached = Usage(input_tokens=input_tokens, output_tokens=output_tokens)
    with_cache = uncached.model_copy(update={"cached_tokens": int(input_tokens * cached)})

    assert pricing.cost_micro_inr(PAID_PRICE, with_cache) <= pricing.cost_micro_inr(
        PAID_PRICE, uncached
    )


def test_the_price_in_force_is_the_newest_one_that_has_started() -> None:
    old = PAID_PRICE.model_copy(update={"effective_from": date(2026, 1, 1)})
    new = PAID_PRICE.model_copy(update={"effective_from": date(2026, 12, 1)})
    pricing = make_pricing().model_copy(update={"models": {"paid": {"model": (new, old)}}})

    assert pricing.price_for("paid", "model", date(2026, 11, 30)) == old
    assert pricing.price_for("paid", "model", date(2026, 12, 1)) == new


def test_a_call_before_the_first_price_has_no_price() -> None:
    with pytest.raises(UnknownPriceError, match="nothing was sent"):
        make_pricing().price_for("paid", "paid-model", date(2025, 12, 31))


def test_rupees_convert_exactly() -> None:
    assert to_rupees(1_500_000) == Decimal("1.5")


def test_a_cached_count_above_the_input_is_refused() -> None:
    with pytest.raises(ValidationError):
        Usage(input_tokens=1, cached_tokens=2, output_tokens=0)


def test_a_negative_price_is_refused() -> None:
    with pytest.raises(ValidationError):
        ModelPrice(
            effective_from=date(2026, 1, 1),
            input_usd=Decimal(-1),
            cached_input_usd=Decimal(0),
            output_usd=Decimal(0),
        )


def test_a_typo_in_the_config_is_refused() -> None:
    with pytest.raises(ValidationError):
        ModelPrice.model_validate(
            {
                "effective_from": date(2026, 1, 1),
                "input_usd": 1,
                "cached_input_usd": 1,
                "output_usd": 1,
                "ouptut_usd": 1,
            }
        )


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(UnknownRoleError):
        RoleTable(roles={}).choice_for("router")


def test_the_shipped_config_loads() -> None:
    config = load_llm_config(CONFIG_DIRECTORY)

    assert config.pricing.exchange_rate.usd_inr == Decimal("94.86")
    assert config.roles.roles


def test_every_shipped_role_has_a_price() -> None:
    config = load_llm_config(CONFIG_DIRECTORY)
    today = config.pricing.last_verified

    for choice in config.roles.roles.values():
        assert config.pricing.price_for(choice.provider, choice.model, today)


def test_the_shipped_cap_is_zero_until_the_cost_gate() -> None:
    # This must change at V3-1, on your yes, and not before.
    assert load_llm_config(CONFIG_DIRECTORY).pricing.monthly_cap_inr == 0


def test_the_shipped_cap_refuses_every_paid_model(tmp_path: Path) -> None:
    config = load_llm_config(CONFIG_DIRECTORY).pricing
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    usage = Usage(input_tokens=1, output_tokens=1)
    paid = [
        (provider, model, versions[-1])
        for provider, models in config.models.items()
        for model, versions in models.items()
        if config.cost_micro_inr(versions[-1], usage) > 0
    ]

    assert paid
    for provider, model, price in paid:
        record = CallRecord(
            at=datetime(2026, 11, 15, tzinfo=UTC), provider=provider, model=model, role="any"
        )
        with pytest.raises(SpendCapError):
            ledger.reserve(
                record, config.cost_micro_inr(price, usage), config.monthly_cap_micro_inr
            )


def test_the_shipped_prices_match_the_values_read_from_the_official_pages() -> None:
    raw = yaml.safe_load((CONFIG_DIRECTORY / "pricing.yaml").read_text(encoding="utf-8"))
    luna = raw["models"]["openai"]["gpt-6-luna"][0]
    haiku = raw["models"]["anthropic"]["claude-haiku-5-5"][0]

    assert (luna["input_usd"], luna["output_usd"]) == (0.10, 0.50)
    assert luna["long_context"]["above_input_tokens"] == 272000
    assert haiku["long_context"]["above_input_tokens"] == 100000
