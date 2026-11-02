"""Real provider check: `make llm-test`."""

import json
import sys

from emporio.config import Settings
from emporio.llm.base import LLMError
from emporio.llm.factory import ConfigurationError, build_provider

STATUS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_store_status",
        "description": "Whether the store is open now.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def main() -> int:
    settings = Settings()
    try:
        provider = build_provider(settings)
        print(f"Model: {settings.llm_model} at {settings.llm_base_url}")

        plain = provider.complete([{"role": "user", "content": "Reply with the word: ok"}], [])
        print(f"[ok] completion: {plain.content!r}")
        print(f"[ok] usage: {plain.usage.input_tokens} in, {plain.usage.output_tokens} out")

        messages = [{"role": "user", "content": "Is the store open? Use the tool."}]
        first = provider.complete(messages, [STATUS_TOOL])
        if not first.tool_calls:
            print(f"[fail] no tool call returned: {first.content!r}")
            return 1
        call = first.tool_calls[0]
        print(f"[ok] tool call: {call.name}({call.arguments})")

        messages.append(first.assistant_message)
        messages.append(
            {"role": "tool", "tool_call_id": call.id, "content": json.dumps({"open_now": True})}
        )
        second = provider.complete(messages, [STATUS_TOOL])
        print(f"[ok] tool round-trip: {second.content!r}")
    except (ConfigurationError, LLMError) as error:
        print(f"[fail] {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
