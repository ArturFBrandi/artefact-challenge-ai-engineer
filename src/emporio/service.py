"""AgentService.handle_message is the single entry point; a WhatsApp webhook could call it too."""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from emporio.agent.loop import LoopResult, run_loop
from emporio.agent.validators import (
    clean_format,
    contacts_in,
    language_problems,
    leaked_contacts,
    number_tokens,
    unsupported_amounts,
    words_in,
)
from emporio.clock import Clock
from emporio.config import Settings
from emporio.data import repositories as repo
from emporio.data.db import session_scope
from emporio.domain.hours import store_status
from emporio.domain.rules import PolicyRules, StoreFacts
from emporio.llm.base import LLMError, LLMProvider
from emporio.memory import sessions as store
from emporio.memory.sessions import Session
from emporio.policies.extract import Section
from emporio.policies.retrieve import Bm25Retriever, Retriever
from emporio.tools.base import Tool, ToolContext
from emporio.tools.orders import register_handoff
from emporio.tools.registry import TOOLS

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "agent" / "prompts" / "system.md"
SAFE_RETRY_LIMIT = 1


def fallback_reply(facts: StoreFacts) -> str:
    return (
        "Desculpa, não consegui confirmar essa informação agora. "
        f"Nossa equipe pode ajudar pelo telefone {facts.phone} ou pelo WhatsApp {facts.whatsapp}.\n"
        "Sorry, I could not confirm that right now. The team can help on the numbers above."
    )


def unavailable_reply(facts: StoreFacts) -> str:
    return (
        "Desculpa, estou com uma instabilidade e não consigo consultar o sistema agora. "
        f"Fale com a equipe pelo telefone {facts.phone}, WhatsApp {facts.whatsapp} "
        f"ou e-mail {facts.email}.\n"
        "Sorry, I cannot reach our systems right now. Please use the contacts above."
    )


@dataclass
class TurnResult:
    session_id: str
    turn: int
    reply: str
    debug: dict[str, Any] = field(default_factory=dict)


class AgentService:
    def __init__(
        self,
        settings: Settings,
        provider: LLMProvider,
        clock: Clock,
        rules: PolicyRules,
        facts: StoreFacts,
        tools: dict[str, Tool] | None = None,
        retriever: Retriever | None = None,
    ) -> None:
        self._settings = settings
        self._provider = provider
        self._clock = clock
        self._rules = rules
        self._facts = facts
        self._tools = tools if tools is not None else TOOLS
        self._prompt = PROMPT_PATH.read_text(encoding="utf-8")
        self._retriever = retriever or self._build_retriever()
        self._base_evidence = number_tokens(
            yaml.safe_dump(rules.model_dump(mode="json")) + facts.model_dump_json()
        )
        self._vocabulary = words_in(facts.model_dump_json()) | self._store_vocabulary()

    def _build_retriever(self) -> Retriever:
        with session_scope(self._settings.db_path) as connection:
            rows = connection.execute("SELECT * FROM policy_sections").fetchall()
        return Bm25Retriever([Section(r["section_id"], r["title"], r["body"]) for r in rows])

    def _store_vocabulary(self) -> set[str]:
        """Words that are normal here though rare in Portuguese: brands, woods, models."""
        with session_scope(self._settings.db_path) as connection:
            rows = connection.execute(
                "SELECT name || ' ' || description AS text FROM products "
                "UNION ALL SELECT name FROM categories "
                "UNION ALL SELECT title || ' ' || body FROM policy_sections"
            ).fetchall()
            specs = connection.execute("SELECT specs FROM products").fetchall()
        values = " ".join(str(v) for row in specs for v in json.loads(row["specs"]).values())
        return words_in(" ".join(row["text"] for row in rows) + " " + values)

    def create_session(self) -> str:
        with session_scope(self._settings.db_path) as connection:
            return store.create_session(connection, self._clock.now()).session_id

    def session_exists(self, session_id: str) -> bool:
        with session_scope(self._settings.db_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row is not None

    def transcript(self, session_id: str) -> list[dict[str, str]]:
        with session_scope(self._settings.db_path) as connection:
            return store.history(connection, session_id, 10_000)

    def _context_block(self, session: Session, connection: Any) -> str:
        now = self._clock.now()
        status = store_status(now, self._facts)
        lines = [f"Current date and time at the store: {now:%A, %d/%m/%Y %H:%M}."]
        if status.is_open:
            assert status.closes_at is not None
            lines.append(f"The store is open and closes at {status.closes_at:%H:%M}.")
        else:
            assert status.next_opening is not None
            lines.append(
                "The store is CLOSED. The team returns "
                f"{status.next_opening:%A, %d/%m/%Y at %H:%M}. Tell the customer this in your "
                "first reply, and whenever you hand off to the team. You can keep helping."
            )
        customer_id = session.verified_customer_id
        customer = repo.customer_by_id(connection, customer_id) if customer_id else None
        if customer:
            first_name = customer["name"].split()[0]
            lines.append(
                f"This customer is already verified. First name: {first_name}. Do not ask for "
                "their details again, and go straight to the order tools."
            )
        else:
            lines.append("This customer is not verified.")
        return "\n".join(lines)

    def handle_message(self, session_id: str, text: str) -> TurnResult:
        started = time.perf_counter()
        now = self._clock.now()
        with session_scope(self._settings.db_path) as connection:
            session = store.load_session(
                connection, session_id, now, self._settings.verification_ttl_minutes
            )
            if session is None:
                session = store.create_session(connection, now)
            turn = store.next_turn(connection, session.session_id)
            context = ToolContext(
                connection, session, self._clock, self._rules, self._facts, self._retriever
            )
            messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": self._prompt.replace(
                        "{{context}}", self._context_block(session, connection)
                    ),
                },
                *store.history(connection, session.session_id, self._settings.memory_window_turns),
                {"role": "user", "content": text},
            ]

            loop = LoopResult(reply=None)
            outcome = "answered"
            try:
                run_loop(
                    self._provider,
                    messages,
                    self._tools,
                    context,
                    self._settings.max_tool_rounds,
                    loop,
                )
                if loop.reply is None:
                    outcome = "round_limit"
                    protocol = register_handoff(
                        context, "tool_failure", f"Agent stopped on: {text[:200]}"
                    )["protocol"]
                    reply = f"{fallback_reply(self._facts)}\nProtocolo: {protocol}"
                else:
                    reply, outcome = self._validated(messages, text, session, context, loop)
            except LLMError as error:
                logger.warning("LLM failure: %s", error)
                outcome, reply = "llm_failure", unavailable_reply(self._facts)

            flags = language_problems(reply, self._vocabulary | words_in(text) | loop.words())
            store.append_turn(connection, session.session_id, turn, text, reply, now)
            store.save_session(connection, session, now)

        debug = self._record(session.session_id, turn, loop, outcome, started)
        debug["language_flags"] = flags
        return TurnResult(session.session_id, turn, reply, debug)

    def _validated(
        self,
        messages: list[dict[str, Any]],
        text: str,
        session: Session,
        context: ToolContext,
        loop: LoopResult,
    ) -> tuple[str, str]:
        """Check the reply; on a problem, ask the model once to fix it, then fall back."""
        allowed_contacts = contacts_in(text) | contacts_in(self._facts.model_dump_json())
        seen = session.evidence.split()
        for attempt in range(SAFE_RETRY_LIMIT + 1):
            evidence = (
                self._base_evidence
                | set(seen)
                | number_tokens(text)
                | {n for run in loop.runs for n in number_tokens(run.output)}
            )
            reply = loop.reply or ""
            bad_amounts = unsupported_amounts(reply, evidence)
            bad_contacts = leaked_contacts(reply, allowed_contacts)
            bad_language = language_problems(
                reply, self._vocabulary | words_in(text) | loop.words()
            )
            if not bad_amounts and not bad_contacts and not bad_language:
                session.evidence = " ".join(sorted(evidence - self._base_evidence))
                return clean_format(reply), "answered" if attempt == 0 else "corrected"
            logger.info(
                "Reply rejected: amounts=%s contacts=%d language=%s",
                bad_amounts,
                len(bad_contacts),
                bad_language,
            )
            if attempt == SAFE_RETRY_LIMIT:
                if not bad_amounts and not bad_contacts:
                    # A stray word is better than refusing to answer.
                    return clean_format(reply), "corrected"
                break
            messages.append(
                {
                    "role": "user",
                    "content": "[Automatic check, not from the customer] Your reply was not sent. "
                    f"These values have no source: {bad_amounts}. Personal contact details "
                    f"found: {len(bad_contacts)}. Foreign words or typing errors: {bad_language}. "
                    "Use the tools or remove them, and rewrite the reply for the customer.",
                }
            )
            run_loop(
                self._provider,
                messages,
                self._tools,
                context,
                self._settings.max_tool_rounds,
                loop,
            )
            if loop.reply is None:
                break
        return fallback_reply(self._facts), "blocked"

    def _record(
        self, session_id: str, turn: int, loop: LoopResult, outcome: str, started: float
    ) -> dict[str, Any]:
        settings = self._settings
        cost = (
            loop.input_tokens * settings.llm_price_input_per_mtok
            + loop.output_tokens * settings.llm_price_output_per_mtok
        ) / 1_000_000
        debug: dict[str, Any] = {
            "outcome": outcome,
            "tools": [
                {"name": run.name, "ok": run.ok, "latency_ms": round(run.latency_ms, 1)}
                for run in loop.runs
            ],
            "llm_calls": loop.llm_calls,
            "input_tokens": loop.input_tokens,
            "output_tokens": loop.output_tokens,
            "cost_usd": round(cost, 6),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
        anonymous = hashlib.sha256(session_id.encode()).hexdigest()[:12]
        settings.trace_dir.mkdir(parents=True, exist_ok=True)
        path = settings.trace_dir / f"{self._clock.now():%Y-%m-%d}.jsonl"
        with path.open("a", encoding="utf-8") as trace:
            trace.write(json.dumps({"session": anonymous, "turn": turn, **debug}) + "\n")
        return debug
