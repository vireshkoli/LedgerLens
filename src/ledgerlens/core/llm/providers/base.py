"""What every provider adapter must do."""

from collections.abc import Iterator
from typing import Protocol

from ledgerlens.core.llm.contracts import Completion, LLMRequest, TextDelta


class Provider(Protocol):
    """One LLM provider.

    An adapter raises `ProviderRejectedError` only when it's certain nothing was billed, such as
    a refused request. Any other exception counts as possibly billed, so the client keeps the
    call's reservation.
    """

    def complete(self, request: LLMRequest) -> Completion:
        """Run a request to the end.

        Args:
            request: The request.

        Returns:
            The whole response.
        """
        ...

    def stream(self, request: LLMRequest) -> Iterator[TextDelta | Completion]:
        """Run a request, yielding text as it arrives.

        Args:
            request: The request.

        Yields:
            Pieces of text, then a final `Completion` holding the whole response.
        """
        ...
