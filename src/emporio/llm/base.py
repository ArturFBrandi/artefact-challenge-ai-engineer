"""Provider contract and shared response types."""

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    """The model could not be reached or returned something unusable."""


class LLMAuthError(LLMError):
    """Credentials or account problem: retrying cannot help."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class LLMResponse:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    # The assistant message as returned. MiniMax requires it back unchanged on the next round.
    assistant_message: dict[str, Any] = field(default_factory=dict)
    usage: Usage = Usage()
    finish_reason: str = "stop"


class LLMProvider(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...
