"""Prices, and the arithmetic that turns tokens into rupees.

Amounts are whole micro-rupees and always round up. Whole numbers keep sums exact, and rounding
up means a cost is never understated, which matters more here than being precise to the paisa.
"""

import math
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import Field

from ledgerlens.core.llm.contracts import Contract, Usage
from ledgerlens.core.llm.errors import UnknownPriceError

MICRO_RUPEES_PER_RUPEE = 1_000_000
TOKENS_PER_PRICE_UNIT = 1_000_000


class TokenRates(Contract):
    """USD per million tokens."""

    input_usd: Decimal = Field(ge=0)
    cached_input_usd: Decimal = Field(ge=0)
    output_usd: Decimal = Field(ge=0)


class LongContextRates(TokenRates):
    """Rates for a whole request whose input is above a threshold."""

    above_input_tokens: int = Field(gt=0)


class ModelPrice(TokenRates):
    """A model's rates from a given date."""

    effective_from: date
    long_context: LongContextRates | None = None

    def rates_for(self, input_tokens: int) -> TokenRates:
        """Pick the rates for a request.

        Providers price the whole request at the higher rates once it passes the threshold, not
        just the tokens above it.

        Args:
            input_tokens: Every input token in the request, including cached ones.

        Returns:
            The rates that apply to the whole request.
        """
        if self.long_context and input_tokens > self.long_context.above_input_tokens:
            return self.long_context
        return self


class ExchangeRate(Contract):
    """The rupee rate used for every estimate."""

    usd_inr: Decimal = Field(gt=0)
    as_of: date
    source: str


class PricingTable(Contract):
    """Everything in `config/pricing.yaml`."""

    last_verified: date
    exchange_rate: ExchangeRate
    gst_rate: Decimal = Field(ge=0)
    monthly_cap_inr: Decimal = Field(ge=0)
    models: dict[str, dict[str, tuple[ModelPrice, ...]]]

    @property
    def monthly_cap_micro_inr(self) -> int:
        """The monthly cap in micro-rupees."""
        return math.floor(self.monthly_cap_inr * MICRO_RUPEES_PER_RUPEE)

    def price_for(self, provider: str, model: str, on: date) -> ModelPrice:
        """Find the price in force on a date.

        Args:
            provider: The provider's name in the config.
            model: The model's name in the config.
            on: The date of the call.

        Returns:
            The newest price that has taken effect.

        Raises:
            UnknownPriceError: If no price has taken effect, since the cost then has no bound.
        """
        versions = self.models.get(provider, {}).get(model, ())
        in_force = [version for version in versions if version.effective_from <= on]
        if not in_force:
            message = f"no price for {provider}/{model} on {on}, so nothing was sent"
            raise UnknownPriceError(message)
        return max(in_force, key=lambda version: version.effective_from)

    def cost_micro_inr(self, price: ModelPrice, usage: Usage) -> int:
        """Work out what a call costs, including GST.

        Args:
            price: The model's price.
            usage: The tokens the call used.

        Returns:
            The cost in micro-rupees, rounded up.
        """
        rates = price.rates_for(usage.input_tokens)
        uncached_tokens = usage.input_tokens - usage.cached_tokens
        usd = (
            uncached_tokens * rates.input_usd
            + usage.cached_tokens * rates.cached_input_usd
            + usage.output_tokens * rates.output_usd
        ) / TOKENS_PER_PRICE_UNIT
        rupees = usd * self.exchange_rate.usd_inr * (1 + self.gst_rate)
        return math.ceil(rupees * MICRO_RUPEES_PER_RUPEE)


def to_rupees(micro_inr: int) -> Decimal:
    """Convert micro-rupees to rupees.

    Args:
        micro_inr: An amount in micro-rupees.

    Returns:
        The same amount in rupees.
    """
    return Decimal(micro_inr) / MICRO_RUPEES_PER_RUPEE


def load_pricing(path: Path) -> PricingTable:
    """Read the pricing table.

    Args:
        path: The YAML file.

    Returns:
        The validated table.
    """
    return PricingTable.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
