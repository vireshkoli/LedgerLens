"""The one client every LLM call goes through.

The order of checks is the point of this file. A call is sent only once its role, provider and
price are known, the cache has missed, and its worst-case cost has been reserved inside the
monthly cap. Anything unknown stops the call, because a refused call costs nothing and an
unbounded one could cost anything.
"""

import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from ledgerlens.core.llm.cache import ResponseCache, cache_key
from ledgerlens.core.llm.config import LLMConfig
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
    ProviderRejectedError,
    UnknownProviderError,
)
from ledgerlens.core.llm.ledger import CallRecord, Ledger
from ledgerlens.core.llm.pricing import ModelPrice, to_rupees
from ledgerlens.core.llm.providers.base import Provider

# Tokens never outnumber a text's UTF-8 bytes, so bytes bound the input before any tokenizer
# runs. The allowance covers the role markers a provider adds around each message.
TOKEN_ALLOWANCE_PER_MESSAGE = 16

logger = logging.getLogger(__name__)


def input_token_bound(messages: Sequence[Message]) -> int:
    """Bound a prompt's input tokens without a tokenizer.

    Args:
        messages: The prompt.

    Returns:
        A number the real count can't exceed. It's a few times too high for ordinary text, which
        only makes the cap refuse a call a little early.
    """
    return sum(len(message.content.encode()) + TOKEN_ALLOWANCE_PER_MESSAGE for message in messages)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _response(completion: Completion, *, cost_micro_inr: int, cache_hit: bool) -> LLMResponse:
    return LLMResponse(
        text=completion.text,
        usage=completion.usage,
        model=completion.model,
        finish_reason=completion.finish_reason,
        cost_inr=to_rupees(cost_micro_inr),
        cache_hit=cache_hit,
    )


@dataclass(frozen=True)
class _PreparedCall:
    """A call that has passed every check that needs no I/O."""

    request: LLMRequest
    record: CallRecord
    provider: Provider
    price: ModelPrice


class LLMClient:
    """Sends LLM calls, and tracks and caps what they cost."""

    def __init__(
        self,
        *,
        config: LLMConfig,
        ledger: Ledger,
        cache: ResponseCache,
        providers: Mapping[str, Provider],
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Set up a client.

        Args:
            config: Which model does which job, what each costs, and the monthly cap.
            ledger: The spending record.
            cache: Stored responses.
            providers: Adapters by name.
            now: The clock, which decides the price in force and the month a call counts in.
        """
        self._roles = config.roles
        self._pricing = config.pricing
        self._ledger = ledger
        self._cache = cache
        self._providers = providers
        self._now = now

    def chat(
        self,
        role: str,
        messages: Sequence[Message],
        *,
        max_output_tokens: int,
        sample: int = 0,
        run_id: str | None = None,
    ) -> LLMResponse:
        """Send a prompt and wait for the whole response.

        Args:
            role: The job, which picks the model.
            messages: The prompt.
            max_output_tokens: The output limit, which also bounds the call's cost.
            sample: Which repeat of this prompt this is. Each value is a separate real call.
            run_id: The run this call belongs to, if any.

        Returns:
            The response, with what it cost.
        """
        call = self._prepare(role, messages, max_output_tokens, sample, run_id)
        cached = self._from_cache(call)
        if cached is not None:
            return cached
        with self._reservation(call) as reservation:
            completion = call.provider.complete(call.request)
        return self._settle(call, reservation, completion)

    def stream(
        self,
        role: str,
        messages: Sequence[Message],
        *,
        max_output_tokens: int,
        sample: int = 0,
        run_id: str | None = None,
    ) -> Iterator[TextDelta | LLMResponse]:
        """Send a prompt and yield text as it arrives.

        Nothing runs until the first item is requested. A consumer that stops early leaves the
        reservation in place, because a partial response is still billed.

        Args:
            role: The job, which picks the model.
            messages: The prompt.
            max_output_tokens: The output limit, which also bounds the call's cost.
            sample: Which repeat of this prompt this is. Each value is a separate real call.
            run_id: The run this call belongs to, if any.

        Yields:
            Pieces of text, then the final response with what it cost.

        Raises:
            IncompleteStreamError: If the provider never delivers the final completion.
        """
        call = self._prepare(role, messages, max_output_tokens, sample, run_id)
        cached = self._from_cache(call)
        if cached is not None:
            yield TextDelta(text=cached.text)
            yield cached
            return
        completion = None
        with self._reservation(call) as reservation:
            for event in call.provider.stream(call.request):
                if isinstance(event, Completion):
                    completion = event
                else:
                    yield event
            if completion is None:
                message = f"{call.request.provider} ended a stream with no final completion"
                raise IncompleteStreamError(message)
        yield self._settle(call, reservation, completion)

    def _prepare(
        self,
        role: str,
        messages: Sequence[Message],
        max_output_tokens: int,
        sample: int,
        run_id: str | None,
    ) -> _PreparedCall:
        choice = self._roles.choice_for(role)
        provider = self._providers.get(choice.provider)
        if provider is None:
            message = f"role {role!r} needs provider {choice.provider!r}, which isn't set up"
            raise UnknownProviderError(message)
        at = self._now()
        return _PreparedCall(
            request=LLMRequest(
                provider=choice.provider,
                model=choice.model,
                messages=tuple(messages),
                max_output_tokens=max_output_tokens,
                sample=sample,
            ),
            record=CallRecord(
                at=at, provider=choice.provider, model=choice.model, role=role, run_id=run_id
            ),
            provider=provider,
            price=self._pricing.price_for(choice.provider, choice.model, at.date()),
        )

    def _from_cache(self, call: _PreparedCall) -> LLMResponse | None:
        completion = self._cache.get(cache_key(call.request))
        if completion is None:
            return None
        self._ledger.record_cache_hit(call.record, completion.usage)
        return _response(completion, cost_micro_inr=0, cache_hit=True)

    @contextmanager
    def _reservation(self, call: _PreparedCall) -> Iterator[int]:
        worst_case = Usage(
            input_tokens=input_token_bound(call.request.messages),
            output_tokens=call.request.max_output_tokens,
        )
        reservation = self._ledger.reserve(
            call.record,
            self._pricing.cost_micro_inr(call.price, worst_case),
            self._pricing.monthly_cap_micro_inr,
        )
        try:
            yield reservation
        except ProviderRejectedError:
            self._ledger.release(reservation)
            raise
        except BaseException:
            self._ledger.mark_unknown(reservation)
            raise

    def _settle(self, call: _PreparedCall, reservation: int, completion: Completion) -> LLMResponse:
        cost = self._pricing.cost_micro_inr(call.price, completion.usage)
        self._ledger.settle(reservation, completion.usage, cost)
        try:
            self._cache.put(cache_key(call.request), completion)
        except OSError:
            # The answer is paid for, so losing the cache entry mustn't lose the answer too.
            logger.warning("couldn't cache a response for %s", call.request.model, exc_info=True)
        return _response(completion, cost_micro_inr=cost, cache_hit=False)
