"""Which model does which job.

Code asks for a role and never names a model, so changing a model is a config change.
"""

from pathlib import Path

import yaml

from ledgerlens.core.llm.contracts import Contract
from ledgerlens.core.llm.errors import UnknownRoleError


class ModelChoice(Contract):
    """A provider and one of its models."""

    provider: str
    model: str


class RoleTable(Contract):
    """Everything in `config/models.yaml`."""

    roles: dict[str, ModelChoice]

    def choice_for(self, role: str) -> ModelChoice:
        """Find the model for a role.

        Args:
            role: The job, such as `router`.

        Returns:
            The configured provider and model.

        Raises:
            UnknownRoleError: If the role isn't configured.
        """
        if role not in self.roles:
            message = f"no model is configured for role {role!r}"
            raise UnknownRoleError(message)
        return self.roles[role]


def load_roles(path: Path) -> RoleTable:
    """Read the role table.

    Args:
        path: The YAML file.

    Returns:
        The validated table.
    """
    return RoleTable.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
