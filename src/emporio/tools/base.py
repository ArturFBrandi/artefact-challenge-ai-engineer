"""Tool contract. Tools receive identity through ToolContext, never through LLM arguments."""

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from emporio.clock import Clock
from emporio.domain.rules import PolicyRules, StoreFacts
from emporio.memory.sessions import Session
from emporio.policies.retrieve import Retriever


class ToolFailure(Exception):
    """An expected failure, reported to the model as a structured result."""


@dataclass
class ToolContext:
    connection: sqlite3.Connection
    session: Session
    clock: Clock
    rules: PolicyRules
    facts: StoreFacts
    retriever: Retriever


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], dict[str, Any]]

    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }


@dataclass(frozen=True)
class ToolRun:
    name: str
    ok: bool
    latency_ms: float
    output: str


def run_tool(tool: Tool, raw_arguments: str, context: ToolContext) -> ToolRun:
    started = time.perf_counter()
    ok = False
    try:
        arguments = tool.input_model.model_validate_json(raw_arguments or "{}")
        result = {"ok": True, **tool.handler(context, arguments)}
        ok = True
    except ValidationError as error:
        problems = [
            {"field": ".".join(map(str, e["loc"])), "problem": e["msg"]} for e in error.errors()
        ]
        result = {"ok": False, "error": "invalid_arguments", "details": problems}
    except ToolFailure as error:
        result = {"ok": False, "error": str(error)}
    except sqlite3.Error:
        result = {"ok": False, "error": "storage_unavailable"}
    return ToolRun(
        tool.name,
        ok,
        (time.perf_counter() - started) * 1000,
        json.dumps(result, ensure_ascii=False, default=str),
    )
