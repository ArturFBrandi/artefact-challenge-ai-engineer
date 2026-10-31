"""MiniMax-M3 through its OpenAI-compatible API.

Details taken from MiniMax's documentation:
* `reasoning_split` moves thinking out of `content`; <think> blocks are still stripped defensively.
* The full assistant message must go back into the history on tool rounds.
* `temperature` is ignored by the model, so it is not sent.
* `max_completion_tokens` counts thinking too.
* Failures can arrive in a `base_resp` field of the body.
"""

import random
import re
import time
from typing import Any

import openai
from openai import OpenAI
from pydantic import SecretStr

from emporio.llm.base import LLMAuthError, LLMError, LLMResponse, ToolCall, Usage

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
RETRYABLE_CODES = frozenset({1000, 1001, 1002, 1024, 1033, 1039, 2045, 2046, 2047, 2064, 2066})
ACCOUNT_CODES = frozenset({1004, 1008, 2049, 2053, 2056, 2061, 2067, 2068, 2069})


class _Retryable(Exception):
    pass


def strip_thinking(text: str) -> str:
    return THINK_BLOCK.sub("", text).strip()


class MiniMaxProvider:
    def __init__(
        self,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout: float,
        max_retries: int,
        max_completion_tokens: int,
        thinking: str,
    ) -> None:
        self._client = OpenAI(
            api_key=api_key.get_secret_value(), base_url=base_url, timeout=timeout, max_retries=0
        )
        self._model = model
        self._max_retries = max_retries
        self._max_completion_tokens = max_completion_tokens
        self._extra_body: dict[str, Any] = {"reasoning_split": True}
        if thinking == "disabled":
            self._extra_body["thinking"] = {"type": "disabled"}

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        for attempt in range(self._max_retries + 1):
            try:
                return self._call(messages, tools)
            except _Retryable as error:
                if attempt == self._max_retries:
                    raise LLMError(str(error)) from error
                time.sleep(min(8.0, 2.0**attempt) * (0.5 + random.random() / 2))
        raise LLMError("unreachable")

    def _call(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        arguments: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_completion_tokens": self._max_completion_tokens,
            "extra_body": self._extra_body,
        }
        if tools:
            arguments["tools"] = tools
        try:
            response = self._client.chat.completions.create(**arguments)
        except (openai.AuthenticationError, openai.PermissionDeniedError) as error:
            raise LLMAuthError(f"MiniMax rejected the credentials: {error}") from error
        except (
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.InternalServerError,
        ) as error:
            raise _Retryable(f"MiniMax transient failure: {error}") from error
        except openai.APIStatusError as error:
            raise LLMError(f"MiniMax rejected the request: {error}") from error
        return parse_response(response)


def parse_response(response: Any) -> LLMResponse:
    base = (response.model_extra or {}).get("base_resp") or {}
    code = base.get("status_code", 0)
    if code in ACCOUNT_CODES:
        raise LLMAuthError(f"MiniMax account error {code}: {base.get('status_msg')}")
    if code in RETRYABLE_CODES:
        raise _Retryable(f"MiniMax error {code}: {base.get('status_msg')}")
    if code:
        raise LLMError(f"MiniMax error {code}: {base.get('status_msg')}")
    if not response.choices:
        raise _Retryable("MiniMax returned no choices")

    choice = response.choices[0]
    message = choice.message
    tool_calls = tuple(
        ToolCall(call.id, call.function.name, call.function.arguments or "{}")
        for call in message.tool_calls or []
    )
    content = strip_thinking(message.content or "")
    if not content and not tool_calls:
        raise _Retryable(f"MiniMax returned an empty reply (finish: {choice.finish_reason})")

    usage = response.usage
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        assistant_message=message.model_dump(exclude_none=True),
        usage=Usage(
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        ),
        finish_reason=choice.finish_reason or "stop",
    )
