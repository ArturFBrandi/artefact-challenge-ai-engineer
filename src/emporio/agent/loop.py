"""The agent: a bounded tool-calling loop, deliberately explicit."""

from dataclasses import dataclass, field
from typing import Any

from emporio.llm.base import LLMProvider, Usage
from emporio.tools.base import Tool, ToolContext, ToolRun, run_tool


@dataclass
class LoopResult:
    reply: str | None  # None when the round limit ran out
    runs: list[ToolRun] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0

    def add_usage(self, usage: Usage) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.llm_calls += 1


def run_loop(
    provider: LLMProvider,
    messages: list[dict[str, Any]],
    tools: dict[str, Tool],
    context: ToolContext,
    max_rounds: int,
    result: LoopResult | None = None,
) -> LoopResult:
    """Run until the model answers. `messages` is extended in place."""
    result = result or LoopResult(reply=None)
    result.reply = None
    specs = [tool.spec() for tool in tools.values()]

    for round_number in range(1, max_rounds + 1):
        # The last round offers no tools, so the model has to answer with what it found.
        response = provider.complete(messages, [] if round_number == max_rounds else specs)
        result.add_usage(response.usage)

        if not response.tool_calls:
            messages.append(response.assistant_message)
            result.reply = response.content
            return result

        messages.append(response.assistant_message)
        for call in response.tool_calls:
            tool = tools.get(call.name)
            if tool is None:
                run = ToolRun(call.name, False, 0.0, '{"ok": false, "error": "unknown_tool"}')
            else:
                run = run_tool(tool, call.arguments, context)
            result.runs.append(run)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": run.output})
    return result
