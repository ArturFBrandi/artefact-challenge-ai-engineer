"""Run evaluation cases through the real service. Assertions check behaviour, not wording."""

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from emporio.clock import FrozenClock
from emporio.config import ROOT, Settings
from emporio.domain.rules import load_facts, load_rules
from emporio.llm.base import LLMProvider
from emporio.service import AgentService
from emporio.text import fold

CASES_PATH = ROOT / "evaluation" / "cases.yaml"
DEFAULT_CLOCK = "2026-03-25T10:00:00-04:00"


@dataclass
class CaseResult:
    case: dict[str, Any]
    failures: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)
    language_flags: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def passed(self) -> bool:
        return not self.failures and not self.not_evaluated

    @property
    def not_evaluated(self) -> bool:
        """The model could not be reached, so this says nothing about the agent."""
        return "llm_failure" in self.outcomes

    @property
    def bypassed(self) -> bool:
        return any(failure.startswith("BYPASS") for failure in self.failures)


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return cases


def check(result: CaseResult) -> None:
    case = result.case
    called = {tool["name"] for tool in result.tools}
    succeeded = {tool["name"] for tool in result.tools if tool["ok"]}
    last = fold(result.replies[-1])
    every_reply = fold("\n".join(result.replies))

    for name in case.get("must_call", []):
        if name not in called:
            result.failures.append(f"did not call {name}")
    for name in case.get("must_not_call", []):
        if name in called:
            result.failures.append(f"called {name}")
    for name in case.get("must_not_succeed", []):
        if name in succeeded:
            result.failures.append(f"BYPASS: {name} succeeded")
    for text in case.get("must_contain", []):
        if fold(text) not in last:
            result.failures.append(f"missing {text!r}")
    options = case.get("any_of", [])
    if options and not any(fold(text) in last for text in options):
        result.failures.append(f"none of {options}")
    for text in case.get("must_not_contain", []):
        if fold(text) in every_reply:
            result.failures.append(f"contains {text!r}")
    if not case.get("english") and result.language_flags:
        result.failures.append(f"language glitches reached the customer: {result.language_flags}")
    if "bypass" in case.get("tags", []):
        for text in case.get("must_not_contain", []):
            if fold(text) in every_reply:
                result.failures.append(f"BYPASS: exposed {text!r}")


def run_case(
    case: dict[str, Any],
    settings: Settings,
    provider_factory: Callable[[], LLMProvider],
    seed_db: Path,
    workdir: Path,
) -> CaseResult:
    """Each case gets a private database copy and its own frozen clock."""
    db_path = workdir / f"{case['id']}.db"
    shutil.copy(seed_db, db_path)
    configured = settings.model_copy(update={"db_path": db_path, "trace_dir": workdir / "traces"})
    clock = FrozenClock(datetime.fromisoformat(case.get("clock", DEFAULT_CLOCK)))
    service = AgentService(
        configured,
        provider_factory(),
        clock,
        load_rules(settings.config_dir),
        load_facts(settings.config_dir),
    )

    result = CaseResult(case)
    session_id = service.create_session()
    for message in case["turns"]:
        started = time.perf_counter()
        turn = service.handle_message(session_id, message)
        result.latencies_ms.append((time.perf_counter() - started) * 1000)
        result.replies.append(turn.reply)
        result.tools += turn.debug["tools"]
        result.outcomes.append(turn.debug["outcome"])
        result.language_flags += turn.debug["language_flags"]
        result.input_tokens += turn.debug["input_tokens"]
        result.output_tokens += turn.debug["output_tokens"]
        result.cost_usd += turn.debug["cost_usd"]
    if not result.not_evaluated:
        check(result)
    return result


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def tool_accuracy(results: list[CaseResult]) -> float:
    expected = hit = 0
    for result in results:
        called = {tool["name"] for tool in result.tools}
        wanted = result.case.get("must_call", [])
        expected += len(wanted)
        hit += sum(name in called for name in wanted)
    return hit / expected if expected else 1.0


def render_report(results: list[CaseResult], header: str) -> str:
    skipped = [r for r in results if r.not_evaluated]
    results = [r for r in results if not r.not_evaluated]
    total = len(results)
    passed = sum(r.passed for r in results)
    conversations = [r for r in results if r.replies]
    latencies = [value for r in results for value in r.latencies_ms]
    grounding = sum(o in ("corrected", "blocked") for r in results for o in r.outcomes)
    blocked = sum(o == "blocked" for r in results for o in r.outcomes)

    lines = [
        "# Evaluation results",
        "",
        header,
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Cases passed | {passed}/{total} ({100 * passed / total:.0f}%) |",
        f"| Critical cases passed | {sum(r.passed for r in results if r.case.get('critical'))}"
        f"/{sum(1 for r in results if r.case.get('critical'))} |",
        f"| Tool selection accuracy | {100 * tool_accuracy(results):.0f}% |",
        f"| Verification bypasses | {sum(r.bypassed for r in results)} |",
        f"| Replies stopped by validators | {grounding} ({blocked} ended in the fallback) |",
        f"| Latency per turn, p50 / p95 | {percentile(latencies, 0.5) / 1000:.1f} s / "
        f"{percentile(latencies, 0.95) / 1000:.1f} s |",
        f"| Tokens per conversation | "
        f"{sum(r.input_tokens + r.output_tokens for r in results) // len(conversations)} |",
        f"| Cost per conversation | US$ {sum(r.cost_usd for r in results) / len(results):.5f} |",
        f"| Total cost of this run | US$ {sum(r.cost_usd for r in results):.4f} |",
        f"| Not evaluated (model unreachable) | {len(skipped)} |",
        "",
        "## By tag",
        "",
        "| Tag | Passed |",
        "|---|---:|",
    ]
    tags = sorted({tag for r in results for tag in r.case.get("tags", [])})
    for tag in tags:
        tagged = [r for r in results if tag in r.case.get("tags", [])]
        lines.append(f"| {tag} | {sum(r.passed for r in tagged)}/{len(tagged)} |")

    failed = [r for r in results if not r.passed]
    if failed:
        lines += ["", "## Failures", ""]
        for result in failed:
            mark = " (critical)" if result.case.get("critical") else ""
            lines.append(f"### {result.case['id']}{mark}")
            lines.append("")
            lines += [f"* {failure}" for failure in result.failures]
            for message, reply in zip(result.case["turns"], result.replies, strict=True):
                lines += ["", f"> **Customer:** {message}", ">", f"> **Agent:** {reply}"]
            lines.append("")
    return "\n".join(lines) + "\n"
