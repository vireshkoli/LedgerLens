"""Loads everything `LLMClient` reads from the config folder."""

from pathlib import Path

from ledgerlens.core.llm.contracts import Contract
from ledgerlens.core.llm.pricing import PricingTable, load_pricing
from ledgerlens.core.llm.roles import RoleTable, load_roles


class LLMConfig(Contract):
    """Which model does which job, and what each one costs."""

    roles: RoleTable
    pricing: PricingTable


def load_llm_config(directory: Path) -> LLMConfig:
    """Read the LLM config.

    Args:
        directory: The folder holding `models.yaml` and `pricing.yaml`.

    Returns:
        The validated config.
    """
    return LLMConfig(
        roles=load_roles(directory / "models.yaml"),
        pricing=load_pricing(directory / "pricing.yaml"),
    )
