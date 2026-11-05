"""A provider that never touches a network, for tests and dry runs."""

from collections.abc import Iterator

from ledgerlens.core.llm.contracts import Completion, LLMRequest, TextDelta, Usage


class FakeProvider:
    """Answers from fixed values and records every request.

    Each answer includes the call number, because a real model's repeated samples differ. That
    makes a sample wrongly served from the cache visible in a test.
    """

    def __init__(
        self,
        usage: Usage | None = None,
        failure: Exception | None = None,
    ) -> None:
        """Set up the fake.

        Args:
            usage: The usage every answer reports.
            failure: An exception to raise instead of answering.
        """
        self.requests: list[LLMRequest] = []
        self._usage = usage or Usage(input_tokens=10, output_tokens=5)
        self._failure = failure

    def complete(self, request: LLMRequest) -> Completion:
        """Answer a request.

        Args:
            request: The request.

        Returns:
            A numbered answer.

        Raises:
            Exception: The failure this fake was given, if any.
        """
        self.requests.append(request)
        if self._failure is not None:
            raise self._failure
        return Completion(
            text=f"answer {len(self.requests)}",
            usage=self._usage,
            model=request.model,
            finish_reason="stop",
        )

    def stream(self, request: LLMRequest) -> Iterator[TextDelta | Completion]:
        """Answer a request in two pieces.

        Args:
            request: The request.

        Yields:
            Each word of the answer, then the whole answer.
        """
        completion = self.complete(request)
        for word in completion.text.split():
            yield TextDelta(text=word)
        yield completion
