"""Why a call was refused or failed."""


class LLMError(Exception):
    """Base class for everything `LLMClient` raises on purpose."""


class UnknownRoleError(LLMError):
    """No model is configured for this role."""


class UnknownProviderError(LLMError):
    """The role names a provider this client wasn't given."""


class UnknownPriceError(LLMError):
    """The model has no price on this date, so its cost can't be bounded."""


class LedgerError(LLMError):
    """The ledger can't be read or written, so spending can't be tracked."""


class SpendCapError(LLMError):
    """This call could take the month's spending past the cap."""


class ProviderRejectedError(LLMError):
    """The provider refused the request before doing any work, so nothing was billed."""


class IncompleteStreamError(LLMError):
    """A stream ended without its final completion."""
