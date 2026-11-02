from pathlib import Path

from evaluation.harness import (
    CaseResult,
    check,
    load_cases,
    percentile,
    render_report,
    run_case,
    tool_accuracy,
)
from evaluation.make_examples import CONVERSATIONS, render

from emporio.llm.fake import FakeLLMProvider, tool_step
from emporio.tools.registry import TOOLS


def result(case, replies, tools=()):
    outcome = CaseResult(case, replies=replies, tools=list(tools))
    check(outcome)
    return outcome


class TestDataset:
    def test_size_and_unique_ids(self):
        cases = load_cases()
        ids = [case["id"] for case in cases]
        assert len(ids) >= 60
        assert len(set(ids)) == len(ids)

    def test_every_tool_named_exists(self):
        for case in load_cases():
            for key in ("must_call", "must_not_call", "must_not_succeed"):
                assert set(case.get(key, [])) <= set(TOOLS), case["id"]

    def test_only_known_fields(self):
        known = {
            "id",
            "turns",
            "clock",
            "must_call",
            "must_not_call",
            "must_not_succeed",
            "must_contain",
            "any_of",
            "must_not_contain",
            "critical",
            "tags",
            "english",
        }
        for case in load_cases():
            assert set(case) <= known, case["id"]

    def test_all_suggested_scenarios_are_covered(self):
        first_turns = [case["turns"][0] for case in load_cases()]
        for question in (
            "Quais opções de violões disponíveis custando até R$1000?",
            "Qual o endereço da loja?",
            "Quanto custa o Takamine GD20?",
            "Me arrependi da minha compra, posso devolver meu pedido?",
        ):
            assert question in first_turns


class TestChecks:
    def test_contains_ignores_accents_and_case(self):
        assert result({"must_contain": ["DISPONÍVEL"]}, ["disponivel sim"]).passed

    def test_missing_tool_fails(self):
        assert not result({"must_call": ["get_order"]}, ["ok"]).passed

    def test_forbidden_text_in_an_early_reply_fails(self):
        assert not result({"must_not_contain": ["segredo"]}, ["o segredo", "fim"]).passed

    def test_any_of(self):
        assert result({"any_of": ["a b", "c d"]}, ["x c d y"]).passed
        assert not result({"any_of": ["a b"]}, ["nada"]).passed

    def test_gate_tool_can_be_tried_but_not_succeed(self):
        case = {"must_not_succeed": ["get_order"]}
        assert result(case, ["x"], [{"name": "get_order", "ok": False}]).passed
        succeeded = result(case, ["x"], [{"name": "get_order", "ok": True}])
        assert succeeded.bypassed

    def test_exposure_in_a_bypass_case_counts_as_a_bypass(self):
        case = {"must_not_contain": ["BRJL"], "tags": ["bypass"]}
        assert result(case, ["BRJL5544332BR"]).bypassed

    def test_language_flags_fail_a_case(self):
        outcome = CaseResult({}, replies=["x"], language_flags=["paying"])
        check(outcome)
        assert "language glitches" in outcome.failures[0]

    def test_english_cases_ignore_language_flags(self):
        outcome = CaseResult({"english": True}, replies=["x"], language_flags=["the"])
        check(outcome)
        assert outcome.passed

    def test_unreachable_model_is_not_a_failure(self, settings, seeded_db, tmp_path):
        from emporio.llm.base import LLMError

        case = {"id": "x", "turns": ["oi"], "must_contain": ["nunca"]}
        provider = FakeLLMProvider([LLMError("429")])
        outcome = run_case(case, settings, lambda: provider, seeded_db, tmp_path)
        assert outcome.not_evaluated and not outcome.passed and not outcome.failures
        good = CaseResult({"id": "y"}, replies=["ok"], latencies_ms=[1.0], outcomes=["answered"])
        report = render_report([outcome, good], "Header")
        assert "1/1 (100%)" in report
        assert "| Not evaluated (model unreachable) | 1 |" in report

    def test_metrics(self):
        assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 3.0
        good = result({"must_call": ["get_order"]}, ["x"], [{"name": "get_order", "ok": True}])
        bad = result({"must_call": ["get_order"]}, ["x"])
        assert tool_accuracy([good, bad]) == 0.5


def test_a_case_runs_end_to_end_with_a_scripted_model(settings, seeded_db, tmp_path):
    case = {
        "id": "scripted",
        "turns": ["Quanto custa?"],
        "must_call": ["get_product"],
        "must_contain": ["2.199,00"],
        "critical": True,
        "tags": ["pricing"],
    }
    script = [tool_step("get_product", '{"name_or_id": "95"}'), "Custa R$ 2.199,00"]
    outcome = run_case(case, settings, lambda: FakeLLMProvider(script), seeded_db, tmp_path)
    assert outcome.passed, outcome.failures
    report = render_report([outcome], "Header")
    assert "1/1 (100%)" in report
    assert "| Verification bypasses | 0 |" in report


def test_failures_are_listed_in_the_report(settings, seeded_db, tmp_path):
    case = {"id": "broken", "turns": ["oi"], "must_contain": ["nunca"], "critical": True}
    outcome = run_case(case, settings, lambda: FakeLLMProvider(["oi!"]), seeded_db, tmp_path)
    report = render_report([outcome], "Header")
    assert "broken (critical)" in report
    assert "**Agent:** oi!" in report


def test_example_generator_runs(settings, tmp_path: Path):
    conversation = CONVERSATIONS[1]
    provider = FakeLLMProvider(["Resposta"] * len(conversation.messages))
    text = render(conversation, settings, provider, tmp_path)
    assert text.count("**Tom:**") == len(conversation.messages)
    assert "Store clock: 2026-03-29" in text


def test_example_count_meets_the_statement():
    assert 3 <= len(CONVERSATIONS) <= 5
