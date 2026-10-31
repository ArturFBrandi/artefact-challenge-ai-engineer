"""Deterministic stand-in for tests. Never used outside APP_ENV=test."""

from collections.abc import Callable, Iterable
from typing import Any

from emporio.llm.base import LLMError, LLMResponse, ToolCall, Usage

Step = LLMResponse | Exception | str | Callable[[list[dict[str, Any]]], LLMResponse]


def tool_step(name: str, arguments: str = "{}", call_id: str = "call_1") -> LLMResponse:
    return tool_steps((name, arguments), call_id=call_id)


def tool_steps(*calls: tuple[str, str], call_id: str = "call") -> LLMResponse:
    tool_calls = tuple(
        ToolCall(f"{call_id}_{i}", name, arguments) for i, (name, arguments) in enumerate(calls)
    )
    return LLMResponse(
        content="",
        tool_calls=tool_calls,
        assistant_message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in tool_calls
            ],
        },
        usage=Usage(10, 5),
    )


class FakeLLMProvider:
    """Plays a script of steps; a plain string becomes a final reply."""

    def __init__(self, script: Iterable[Step] = ()) -> None:
        self._script = list(script)
        self.calls: list[list[dict[str, Any]]] = []
        self.tool_counts: list[int] = []

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        self.calls.append([dict(message) for message in messages])
        self.tool_counts.append(len(tools))
        if not self._script:
            return self._final("Test assistant: no script for this message.")
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, str):
            return self._final(step)
        if isinstance(step, LLMResponse):
            return step
        if callable(step):
            return step(messages)
        raise LLMError(f"Bad script step: {step!r}")

    @staticmethod
    def _final(text: str) -> LLMResponse:
        return LLMResponse(
            content=text,
            assistant_message={"role": "assistant", "content": text},
            usage=Usage(10, 5),
        )
