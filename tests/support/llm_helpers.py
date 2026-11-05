from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

from ledgerlens.core.llm.client import LLMClient
from ledgerlens.core.llm.config import LLMConfig
from ledgerlens.core.llm.pricing import (
    ExchangeRate,
    LongContextRates,
    ModelPrice,
    PricingTable,
)
from ledgerlens.core.llm.roles import ModelChoice, RoleTable

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)

# ₹1 per USD and no GST, so one token at $1 per million costs exactly one micro-rupee.
PAID_PRICE = ModelPrice(
    effective_from=date(2026, 1, 1),
    input_usd=Decimal(1),
    cached_input_usd=Decimal("0.1"),
    output_usd=Decimal(2),
    long_context=LongContextRates(
        above_input_tokens=1000,
        input_usd=Decimal(10),
        cached_input_usd=Decimal(1),
        output_usd=Decimal(20),
    ),
)
FREE_PRICE = ModelPrice(
    effective_from=date(2026, 1, 1),
    input_usd=Decimal(0),
    cached_input_usd=Decimal(0),
    output_usd=Decimal(0),
)


def make_pricing(cap_inr: str = "1") -> PricingTable:
    return PricingTable(
        last_verified=date(2026, 11, 5),
        exchange_rate=ExchangeRate(usd_inr=Decimal(1), as_of=date(2026, 11, 3), source="test"),
        gst_rate=Decimal(0),
        monthly_cap_inr=Decimal(cap_inr),
        models={"paid": {"paid-model": (PAID_PRICE,)}, "free": {"free-model": (FREE_PRICE,)}},
    )


def make_config(cap_inr: str = "1") -> LLMConfig:
    return LLMConfig(
        roles=RoleTable(
            roles={
                "worker": ModelChoice(provider="paid", model="paid-model"),
                "local": ModelChoice(provider="free", model="free-model"),
                "unpriced": ModelChoice(provider="paid", model="no-such-model"),
                "unwired": ModelChoice(provider="absent", model="paid-model"),
            }
        ),
        pricing=make_pricing(cap_inr),
    )


ClientFactory = Callable[..., LLMClient]
