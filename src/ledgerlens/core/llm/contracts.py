"""The data that moves through `LLMClient`."""

from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    """Base for immutable models that refuse unknown fields, so a typo can't pass silently."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Message(Contract):
    """One turn of a conversation."""

    role: Literal["system", "user", "assistant"]
    content: str


class LLMRequest(Contract):
    """Everything that decides a response.

    The cache key covers this whole model, so a new field can't be left out of the key by
    accident. `sample` is never sent to a provider: it exists so that repeated samples of the
    same prompt are separate cache entries, and therefore separate real calls.
    """

    provider: str
    model: str
    messages: tuple[Message, ...] = Field(min_length=1)
    max_output_tokens: int = Field(gt=0)
    sample: int = Field(default=0, ge=0)


class Usage(Contract):
    """Tokens a call used.

    `input_tokens` counts every input token, and `cached_tokens` is the part of them billed at
    the cached rate. Providers report this differently, so adapters convert to this meaning.
    """

    input_tokens: int = Field(ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def _cached_tokens_are_part_of_input(self) -> Self:
        if self.cached_tokens > self.input_tokens:
            message = "cached_tokens can't exceed input_tokens"
            raise ValueError(message)
        return self


class Completion(Contract):
    """What a provider returns, and what the cache stores."""

    text: str
    usage: Usage
    model: str
    finish_reason: str


class LLMResponse(Completion):
    """What the client returns."""

    cost_inr: Decimal
    cache_hit: bool


class TextDelta(Contract):
    """A piece of streamed text."""

    text: str
