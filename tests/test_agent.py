from datetime import datetime

import pytest

from emporio.agent.validators import (
    clean_format,
    contacts_in,
    language_problems,
    leaked_contacts,
    number_tokens,
    parse_number,
    unsupported_amounts,
)
from emporio.clock import FrozenClock
from emporio.data.db import connect
from emporio.llm.base import LLMAuthError, LLMError
from emporio.llm.fake import tool_step, tool_steps
from emporio.llm.minimax import _Retryable, parse_response, strip_thinking
from emporio.memory.redact import redact
from emporio.memory.sessions import append_turn, history


class TestNumbers:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("2.199,00", "2199"),
            ("2,199.00", "2199"),
            ("2199", "2199"),
            ("2.199", "2199"),
            ("1.967,18", "1967.18"),
            ("996,55", "996.55"),
            ("19.90", "19.9"),
            ("1,5", "1.5"),
        ],
    )
    def test_parse(self, text, expected):
        assert format(parse_number(text), "f") == expected

    def test_supported_amount_passes(self):
        assert unsupported_amounts("Fica R$ 2.199,00", number_tokens('"R$ 2.199,00"')) == []

    def test_equivalent_format_passes(self):
        assert unsupported_amounts("Fica R$2199", number_tokens('"R$ 2.199,00"')) == []

    def test_invented_amount_is_caught(self):
        found = unsupported_amounts("Fica R$ 1.868,82", number_tokens("R$ 1.967,18"))
        assert found == ["R$ 1.868,82"]

    def test_invented_percentage_is_caught(self):
        assert unsupported_amounts("Dou 50% de desconto", number_tokens("18")) == ["50%"]

    def test_money_with_punctuation_after(self):
        assert unsupported_amounts("Custa R$ 500.", {"500"}) == []


class TestLanguage:
    @pytest.mark.parametrize(
        "reply",
        ["Quer que euCOMPARE as opções?", "Nada está announcement/garantido", "Você is the best"],
    )
    def test_glitches_are_found(self, reply):
        assert language_problems(reply)

    @pytest.mark.parametrize(
        "reply",
        [
            "Quer que eu compare as opções? Não tem problema.",
            "The price is R$ 699,90. Would you like more details?",
            "Takamine GD20 Dreadnought com PIX e MIDI",
        ],
    )
    def test_clean_replies_pass(self, reply):
        assert language_problems(reply) == []

    def test_markdown_emphasis_is_removed(self):
        assert clean_format("Me passa o **número** do pedido") == "Me passa o número do pedido"


class TestContacts:
    allowed = contacts_in("(67) 3341-4444 contato@emporiodamusica.com.br")

    def test_store_contacts_pass(self):
        reply = "Ligue (67) 3341-4444 ou contato@emporiodamusica.com.br"
        assert leaked_contacts(reply, self.allowed) == []

    def test_other_contacts_are_caught(self):
        reply = "O telefone dela é (67) 99654-7821 e o e-mail ana@coldmail.com"
        assert len(leaked_contacts(reply, self.allowed)) == 2

    def test_tracking_codes_are_not_phones(self):
        assert leaked_contacts("Código BRJL5544332BR", self.allowed) == []

    def test_redaction(self):
        assert redact("sou (67) 99654-7821 ana@x.com") == "sou [phone] [email]"


class TestProviderParsing:
    def _response(self, **fields):
        from openai.types.chat import ChatCompletion

        message = {"role": "assistant", "content": fields.get("content", "oi")}
        message |= fields.get("message", {})
        return ChatCompletion.model_validate(
            {
                "id": "1",
                "created": 1,
                "model": "MiniMax-M3",
                "object": "chat.completion",
                "choices": fields.get(
                    "choices", [{"index": 0, "finish_reason": "stop", "message": message}]
                ),
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                **fields.get("extra", {}),
            }
        )

    def test_strips_thinking(self):
        assert strip_thinking("<think>hmm\nyes</think>\nOi!") == "Oi!"

    def test_keeps_reasoning_on_the_message_for_the_next_round(self):
        response = self._response(
            content="",
            message={
                "reasoning_content": "thinking",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "get_store_status", "arguments": ""},
                    }
                ],
            },
        )
        parsed = parse_response(response)
        assert parsed.assistant_message["reasoning_content"] == "thinking"
        assert parsed.tool_calls[0].arguments == "{}"

    def test_reads_usage(self):
        parsed = parse_response(self._response())
        assert (parsed.usage.input_tokens, parsed.usage.output_tokens) == (3, 2)

    def test_error_in_body_is_detected(self):
        extra = {"base_resp": {"status_code": 2049, "status_msg": "invalid api key"}}
        with pytest.raises(LLMAuthError):
            parse_response(self._response(extra=extra))

    def test_transient_error_in_body_is_retryable(self):
        extra = {"base_resp": {"status_code": 2064, "status_msg": "busy"}}
        with pytest.raises(_Retryable):
            parse_response(self._response(extra=extra))

    def test_unknown_error_in_body_fails(self):
        with pytest.raises(LLMError):
            parse_response(
                self._response(extra={"base_resp": {"status_code": 2013, "status_msg": "bad"}})
            )

    def test_empty_reply_is_retryable(self):
        with pytest.raises(_Retryable):
            parse_response(self._response(content=""))


class TestLoop:
    def test_tool_round_trip(self, make_service):
        service, provider = make_service(
            [tool_step("get_product", '{"name_or_id": "Takamine GD20"}'), "Custa R$ 2.199,00"]
        )
        result = service.handle_message(service.create_session(), "quanto custa?")
        assert result.reply == "Custa R$ 2.199,00"
        assert result.debug["tools"][0]["name"] == "get_product"
        assert result.debug["llm_calls"] == 2
        assert result.debug["outcome"] == "answered"
        assert provider.calls[1][-1]["role"] == "tool"
        assert provider.calls[1][-2]["tool_calls"]

    def test_several_tools_in_one_round(self, make_service):
        service, provider = make_service(
            [tool_steps(("get_store_status", "{}"), ("list_active_promotions", "{}")), "Pronto"]
        )
        result = service.handle_message(service.create_session(), "oi")
        assert [t["name"] for t in result.debug["tools"]] == [
            "get_store_status",
            "list_active_promotions",
        ]
        assert [m["role"] for m in provider.calls[1][-2:]] == ["tool", "tool"]

    def test_round_limit_ends_with_a_handoff(self, make_service, db_path):
        service, _ = make_service([tool_step("get_store_status")] * 10)
        result = service.handle_message(service.create_session(), "oi")
        assert result.debug["outcome"] == "round_limit"
        assert result.debug["llm_calls"] == 4
        assert "EM-20260325-0001" in result.reply

    def test_last_round_offers_no_tools_so_the_model_answers(self, make_service):
        service, provider = make_service([tool_step("get_store_status")] * 3 + ["Resposta"])
        result = service.handle_message(service.create_session(), "oi")
        assert result.reply == "Resposta"
        assert provider.tool_counts[:3] == [12, 12, 12]
        assert provider.tool_counts[3] == 0

    def test_malformed_arguments_go_back_to_the_model(self, make_service):
        service, provider = make_service([tool_step("get_order", "{oops"), "Pode repetir?"])
        result = service.handle_message(service.create_session(), "pedido")
        assert result.reply == "Pode repetir?"
        assert result.debug["tools"][0]["ok"] is False
        assert '"ok": false' in provider.calls[1][-1]["content"]

    def test_unknown_tool_goes_back_to_the_model(self, make_service):
        service, provider = make_service([tool_step("delete_everything"), "Desculpa"])
        result = service.handle_message(service.create_session(), "x")
        assert result.reply == "Desculpa"
        assert "unknown_tool" in provider.calls[1][-1]["content"]

    def test_llm_failure_gives_an_honest_message(self, make_service, facts):
        service, _ = make_service([LLMError("down")])
        result = service.handle_message(service.create_session(), "oi")
        assert facts.phone in result.reply
        assert result.debug["outcome"] == "llm_failure"

    def test_auth_failure_also_gives_an_honest_message(self, make_service):
        service, _ = make_service([LLMAuthError("bad key")])
        result = service.handle_message(service.create_session(), "oi")
        assert result.debug["outcome"] == "llm_failure"


class TestGrounding:
    def test_invented_price_triggers_one_retry(self, make_service):
        service, provider = make_service(
            [
                "Custa R$ 1.234,00",
                tool_step("get_product", '{"name_or_id": "95"}'),
                "Custa R$ 2.199,00",
            ]
        )
        result = service.handle_message(service.create_session(), "preço?")
        assert result.reply == "Custa R$ 2.199,00"
        assert result.debug["outcome"] == "corrected"
        assert "not from the customer" in provider.calls[1][-1]["content"]

    def test_repeated_invention_is_blocked(self, make_service, facts):
        service, _ = make_service(["Custa R$ 1.234,00", "Custa R$ 1.235,00"])
        result = service.handle_message(service.create_session(), "preço?")
        assert "1.235" not in result.reply
        assert facts.phone in result.reply
        assert result.debug["outcome"] == "blocked"

    def test_contact_leak_is_blocked(self, make_service):
        service, _ = make_service(["O telefone dela é (67) 99654-7821"] * 2)
        result = service.handle_message(service.create_session(), "telefone da Ana?")
        assert "99654" not in result.reply

    def test_customer_can_get_their_own_contact_back(self, make_service):
        service, _ = make_service(["Anotei (67) 99000-1111"])
        result = service.handle_message(service.create_session(), "meu fone é (67) 99000-1111")
        assert result.debug["outcome"] == "answered"

    def test_amount_the_customer_typed_is_allowed(self, make_service):
        service, _ = make_service(["Para até R$ 1000 temos opções"])
        result = service.handle_message(service.create_session(), "até R$1000?")
        assert result.debug["outcome"] == "answered"

    def test_amounts_from_earlier_turns_stay_supported(self, make_service):
        service, _ = make_service(
            [tool_step("get_product", '{"name_or_id": "95"}'), "R$ 2.199,00", "Era R$ 2.199,00"]
        )
        session = service.create_session()
        service.handle_message(session, "preço?")
        result = service.handle_message(session, "quanto mesmo?")
        assert result.debug["outcome"] == "answered"


class TestLanguageRetry:
    def test_glitch_triggers_a_rewrite(self, make_service):
        service, _ = make_service(["Quer que euCOMPARE?", "Quer que eu compare?"])
        result = service.handle_message(service.create_session(), "oi")
        assert result.reply == "Quer que eu compare?"
        assert result.debug["outcome"] == "corrected"

    def test_bold_is_removed_before_sending(self, make_service):
        service, _ = make_service(["Me passa o **pedido**"])
        result = service.handle_message(service.create_session(), "oi")
        assert result.reply == "Me passa o pedido"


class TestMemory:
    def test_history_reaches_the_model(self, make_service):
        service, provider = make_service(["Primeira", "Segunda"])
        session = service.create_session()
        service.handle_message(session, "oi")
        service.handle_message(session, "tudo bem?")
        roles = [(m["role"], m["content"]) for m in provider.calls[1][1:]]
        assert roles == [("user", "oi"), ("assistant", "Primeira"), ("user", "tudo bem?")]

    def test_window_limits_history(self, make_service):
        service, provider = make_service(["a", "b", "c"], memory_window_turns=1)
        session = service.create_session()
        for text in ("um", "dois", "três"):
            service.handle_message(session, text)
        assert [m["content"] for m in provider.calls[2][1:]] == ["dois", "b", "três"]

    def test_contacts_are_redacted_at_rest(self, make_service, db_path):
        service, _ = make_service(["ok"])
        session = service.create_session()
        service.handle_message(session, "meu fone é (67) 99654-7821")
        stored = connect(db_path).execute("SELECT content FROM turns").fetchall()
        assert "99654" not in stored[0]["content"]

    def test_turns_keep_order(self, db_path, clock):
        connection = connect(db_path)
        connection.execute(
            "INSERT INTO sessions (session_id, created_at, last_seen_at) VALUES ('s', 'x', 'x')"
        )
        append_turn(connection, "s", 1, "pergunta", "resposta", clock.now())
        assert [m["role"] for m in history(connection, "s", 5)] == ["user", "assistant"]

    def test_verification_persists_across_turns(self, make_service):
        verify = '{"order_id": 8, "phone": "(67) 99654-7821"}'
        service, provider = make_service(
            [
                tool_step("verify_customer", verify),
                "Ok!",
                tool_step("get_order", '{"order_id": 8}'),
                "Está a caminho",
            ]
        )
        session = service.create_session()
        service.handle_message(session, "pedido 8, meu telefone...")
        result = service.handle_message(session, "e o status?")
        assert result.debug["tools"][0]["ok"] is True
        assert "First name: Ana" in provider.calls[2][0]["content"]

    def test_verification_expires_after_inactivity(self, make_service, db_path):
        verify = '{"order_id": 8, "phone": "(67) 99654-7821"}'
        start = FrozenClock(datetime.fromisoformat("2026-03-25T10:00:00-04:00"))
        later = FrozenClock(datetime.fromisoformat("2026-03-25T11:00:00-04:00"))
        service, _ = make_service([tool_step("verify_customer", verify), "Ok!"], at=start)
        session = service.create_session()
        service.handle_message(session, "pedido 8")
        again, _ = make_service([tool_step("get_order", '{"order_id": 8}'), "?"], at=later)
        result = again.handle_message(session, "status?")
        assert result.debug["tools"][0]["ok"] is False

    def test_sessions_do_not_share_identity(self, make_service):
        verify = '{"order_id": 8, "phone": "(67) 99654-7821"}'
        service, _ = make_service(
            [
                tool_step("verify_customer", verify),
                "Ok!",
                tool_step("get_order", '{"order_id": 8}'),
                "?",
            ]
        )
        service.handle_message(service.create_session(), "pedido 8")
        result = service.handle_message(service.create_session(), "pedido 8")
        assert result.debug["tools"][0]["ok"] is False


class TestContextBlock:
    def test_open_store(self, make_service):
        service, provider = make_service(["oi"])
        service.handle_message(service.create_session(), "oi")
        system = provider.calls[0][0]["content"]
        assert "Wednesday, 2026-03-25 10:00" in system
        assert "open and closes at 18:00" in system
        assert "{{context}}" not in system

    def test_closed_store_gives_next_opening(self, make_service):
        sunday = FrozenClock(datetime.fromisoformat("2026-03-29T10:00:00-04:00"))
        service, provider = make_service(["oi"], at=sunday)
        service.handle_message(service.create_session(), "oi")
        assert "CLOSED" in provider.calls[0][0]["content"]
        assert "Monday, 2026-03-30 at 09:00" in provider.calls[0][0]["content"]


def test_trace_has_no_customer_text(make_service, settings):
    service, _ = make_service(["ok"])
    service.handle_message(service.create_session(), "meu segredo")
    trace = next(settings.trace_dir.glob("*.jsonl")).read_text()
    assert "segredo" not in trace
    assert '"outcome": "answered"' in trace


def test_fake_provider_is_refused_outside_tests():
    from emporio.config import Settings
    from emporio.llm.factory import ConfigurationError, build_provider

    with pytest.raises(ConfigurationError):
        build_provider(Settings(_env_file=None, llm_provider="fake", app_env="development"))


def test_missing_key_gives_a_clear_error():
    from emporio.config import Settings
    from emporio.llm.factory import ConfigurationError, build_provider

    with pytest.raises(ConfigurationError, match="LLM_API_KEY"):
        build_provider(Settings(_env_file=None, llm_api_key=""))


def test_frozen_clock_needs_an_offset():
    from emporio.config import Settings

    with pytest.raises(ValueError, match="UTC offset"):
        Settings(_env_file=None, store_now="2026-03-25T10:00:00")
