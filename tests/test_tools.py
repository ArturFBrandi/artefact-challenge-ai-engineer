import json
from datetime import datetime

import pytest

from emporio.clock import FrozenClock
from emporio.data.db import connect
from emporio.memory.sessions import Session
from emporio.policies.extract import Section
from emporio.policies.retrieve import Bm25Retriever
from emporio.tools.base import ToolContext, run_tool
from emporio.tools.registry import TOOLS

ANA = {"order_id": 8, "phone": "(67) 99654-7821"}
LUCAS_PHONE = "(67) 99812-3456"


@pytest.fixture
def context(db_path, clock, rules, facts):
    connection = connect(db_path)
    rows = connection.execute("SELECT * FROM policy_sections").fetchall()
    retriever = Bm25Retriever([Section(r["section_id"], r["title"], r["body"]) for r in rows])
    connection.execute(
        "INSERT INTO sessions (session_id, created_at, last_seen_at) VALUES ('s', 'x', 'x')"
    )
    yield ToolContext(connection, Session("s"), clock, rules, facts, retriever)
    connection.close()


def call(context, name, **arguments):
    run = run_tool(TOOLS[name], json.dumps(arguments), context)
    return json.loads(run.output)


class TestCatalog:
    def test_budget_search_hides_unavailable(self, context):
        result = call(context, "search_products", category="Violões", max_price=1000, limit=12)
        names = [p["name"] for p in result["products"]]
        assert result["total_matches"] == 12
        assert result["unavailable_matches_hidden"] == 2
        assert not any("GF-3D" in name or "SN-7C" in name for name in names)
        assert names[0].startswith("Tagima Memphis")

    def test_budget_search_reveals_pix_only_fit(self, context):
        result = call(context, "search_products", category="Violões", max_price=1000)
        fits = result["fits_budget_only_with_pix"]
        assert [p["product_id"] for p in fits] == [101]
        assert fits[0]["pix_price"] == "R$ 996,55"

    def test_budget_uses_promotional_price(self, context):
        result = call(context, "search_products", category="Ukuleles", max_price=450, limit=12)
        assert 121 in [p["product_id"] for p in result["products"]]  # 549 with 20% off

    def test_empty_categories_say_nothing_matches(self, context):
        result = call(context, "search_products", category="Cordas Orquestrais")
        assert result["total_matches"] == 0
        assert "note" in result

    def test_words_not_in_catalog_find_nothing(self, context):
        assert call(context, "search_products", query="saxofone")["total_matches"] == 0

    def test_search_handles_plural_and_accents(self, context):
        result = call(context, "search_products", query="violoes 7 cordas", limit=12)
        assert result["total_matches"] == 4  # the fifth one, #113, is discontinued

    def test_extra_words_do_not_hide_the_catalog(self, context):
        result = call(context, "search_products", query="violão nylon barato")
        assert result["total_matches"] > 0
        assert result["partial_match"] is True

    def test_full_matches_are_not_flagged_as_partial(self, context):
        assert "partial_match" not in call(context, "search_products", query="violão nylon")

    def test_two_word_search_for_an_absent_instrument_is_flagged(self, context):
        result = call(context, "search_products", query="saxofone estudante")
        assert result["total_matches"] == 0 or result["partial_match"] is True

    @pytest.mark.parametrize("name", ["saxofone", "violino", "flauta transversal", "clarinete"])
    def test_absent_instruments_are_not_matched_by_name(self, context, name):
        assert call(context, "get_product", name_or_id=name)["error"] == "product_not_found"

    def test_string_and_electronics_filters(self, context):
        result = call(
            context, "search_products", category="Violões", strings="steel", electronics=True
        )
        assert result["total_matches"] > 0
        assert all(p["name"] for p in result["products"])

    def test_partial_name_finds_one_product(self, context):
        result = call(context, "get_product", name_or_id="Takamine GD20")
        assert result["product_id"] == 95
        assert result["price"] == "R$ 2.199,00"
        assert result["pix_price"] == "R$ 2.089,05"
        assert result["max_installments"] == 12
        assert "promotion" not in result

    def test_expired_promotion_is_flagged_but_never_priced(self, context):
        result = call(context, "get_product", name_or_id="95")
        assert result["expired_promotions"] == ["Oferta Especial"]
        assert "12" not in json.dumps(result.get("promotion", {}))

    def test_ambiguous_name_returns_candidates(self, context):
        result = call(context, "get_product", name_or_id="Takamine")
        assert result["ambiguous"] is True
        assert len(result["candidates"]) == 4

    def test_d28_does_not_match_d28e(self, context):
        assert call(context, "get_product", name_or_id="Martin D-28")["product_id"] == 93
        assert call(context, "get_product", name_or_id="Martin D-28E")["product_id"] == 108

    def test_typo_gets_close_candidates(self, context):
        result = call(context, "get_product", name_or_id="Takamine GD21 Dreadnought Natural")
        assert result.get("product_id") == 95 or result.get("ambiguous")

    @pytest.mark.parametrize(
        ("product", "availability"),
        [(96, "out_of_stock"), (113, "discontinued"), (136, "discontinued"), (130, "coming_soon")],
    )
    def test_unavailable_products_offer_alternatives(self, context, product, availability):
        result = call(context, "get_product", name_or_id=str(product))
        assert result["availability"] == availability
        assert 0 < len(result["alternatives"]) <= 3
        assert all(a["availability"] == "available" for a in result["alternatives"])
        assert "stock_quantity" not in result

    def test_active_promotion_shows_all_three_values(self, context):
        result = call(context, "get_product", name_or_id="90")
        assert result["promotion"] == {
            "name": "Desconto Exclusivo",
            "percent": 18,
            "original_price": "R$ 2.399,00",
            "promotional_price": "R$ 1.967,18",
        }

    def test_quote_refuses_stacked_pix(self, context):
        result = call(context, "quote_price", product_id=90, payment_method="pix")
        assert result["final_price"] == "R$ 1.967,18"
        assert "1.868,82" not in json.dumps(result)
        assert result["notes"]

    def test_quote_refuses_installments_and_gives_the_limit(self, context):
        result = call(
            context, "quote_price", product_id=87, payment_method="credit", installments=10
        )
        assert result["installments_allowed"] is False
        assert result["max_installments"] == 6  # R$ 699,90: 7x would be under R$ 100

    def test_active_promotions_list_has_four(self, context):
        result = call(context, "list_active_promotions")
        assert {p["product_id"] for p in result["promotions"]} == {90, 94, 121, 127}


class TestStore:
    def test_status_and_contacts(self, context):
        result = call(context, "get_store_status")
        assert result["open_now"] is True
        assert result["closes_at"] == "18:00"
        assert result["whatsapp"] == "(67) 3321-4500"
        assert result["email"] == "contato@emporiodamusica.com.br"

    def test_closed_on_sunday(self, context):
        context.clock = FrozenClock(datetime.fromisoformat("2026-03-29T10:00:00-04:00"))
        result = call(context, "get_store_status")
        assert result["open_now"] is False
        assert result["next_opening"].startswith("Monday 2026-03-30")

    def test_policy_search_returns_sections(self, context):
        result = call(context, "search_policies", query="trocar por outra cor")
        assert any("preferência" in s["title"].lower() for s in result["sections"])

    def test_shipping(self, context):
        assert (
            call(context, "check_shipping", city="Campo Grande", order_value=499)["fee"]
            == "R$ 35,00"
        )
        assert call(context, "check_shipping", city="Dourados", order_value=900)["fee"] is None


class TestVerification:
    def test_no_tool_accepts_a_customer_id(self):
        for tool in TOOLS.values():
            assert "customer" not in " ".join(tool.input_model.model_fields)

    @pytest.mark.parametrize("name", ["get_order", "check_return_eligibility", "list_my_orders"])
    def test_order_tools_refuse_unverified_sessions(self, context, name):
        arguments = {
            "get_order": {"order_id": 8},
            "check_return_eligibility": {"order_id": 8, "reason": "regret"},
            "list_my_orders": {},
        }[name]
        assert call(context, name, **arguments)["error"] == "customer_not_verified"

    def test_right_order_and_phone(self, context):
        result = call(context, "verify_customer", **ANA)
        assert result == {"ok": True, "verified": True, "first_name": "Ana"}
        assert context.session.verified_customer_id == 2

    def test_phone_formats_are_normalized(self, context):
        result = call(context, "verify_customer", order_id=8, phone="+55 67 99654 7821")
        assert result["verified"] is True

    def test_other_customers_phone_fails(self, context):
        result = call(context, "verify_customer", order_id=8, phone=LUCAS_PHONE)
        assert result["error"] == "verification_failed"
        assert context.session.verified_customer_id is None

    def test_failures_are_indistinguishable(self, context):
        wrong_phone = call(context, "verify_customer", order_id=8, phone=LUCAS_PHONE)
        no_order = call(context, "verify_customer", order_id=9999, phone=LUCAS_PHONE)
        assert wrong_phone == no_order

    def test_locks_after_three_failures(self, context):
        for _ in range(3):
            call(context, "verify_customer", order_id=8, phone=LUCAS_PHONE)
        result = call(context, "verify_customer", **ANA)
        assert result["error"] == "verification_locked_create_a_handoff"
        assert context.session.verified_customer_id is None

    def test_shared_email_does_not_identify_alone(self, context):
        result = call(context, "verify_customer", email="bruno.martins@jmail.com")
        assert result["verified"] is False
        assert context.session.verified_customer_id is None

    def test_shared_email_works_with_the_order(self, context):
        result = call(context, "verify_customer", order_id=10, email="bruno.martins@jmail.com")
        assert result["verified"] is True
        assert context.session.verified_customer_id == 11

    def test_phone_and_email_together(self, context):
        result = call(
            context,
            "verify_customer",
            phone="(67) 98432-1098",
            email="PEDRO.oliveira@jmail.com",
        )
        assert result["verified"] is True

    def test_missing_details_do_not_count_as_a_failure(self, context):
        result = call(context, "verify_customer", order_id=8)
        assert result["verified"] is False
        assert context.session.failed_verifications == 0


class TestOrders:
    def test_verified_customer_sees_order(self, context):
        call(context, "verify_customer", **ANA)
        result = call(context, "get_order", order_id=8)
        assert result["tracking_code"] == "BRJL5544332BR"
        assert result["days_overdue"] == 25
        assert result["items"] == [{"name": "Kala KA-C Concert Mogno", "quantity": 1}]

    def test_verified_customer_cannot_see_others(self, context):
        call(context, "verify_customer", **ANA)
        result = call(context, "get_order", order_id=4)
        missing = call(context, "get_order", order_id=9999)
        assert result == missing
        assert result["error"] == "order_not_found_for_this_customer"

    def test_stored_total_is_reported_as_is(self, context):
        context.session.verified_customer_id = 12
        assert call(context, "get_order", order_id=3)["total"] == "R$ 3.450,00"

    def test_output_has_no_contact_details(self, context):
        call(context, "verify_customer", **ANA)
        text = json.dumps(call(context, "list_my_orders"))
        assert "99654" not in text
        assert "coldmail" not in text

    def test_cancellation_reason_shown_only_when_cancelled(self, context):
        context.session.verified_customer_id = 3
        orders = {o["order_id"]: o for o in call(context, "list_my_orders")["orders"]}
        assert orders[19]["cancellation_reason"]
        assert "cancellation_reason" not in orders[1]

    def test_return_needs_channel_then_expires(self, context):
        context.session.verified_customer_id = 14
        first = call(context, "check_return_eligibility", order_id=7, reason="regret")
        assert first["verdict"] == "needs_info"
        second = call(
            context,
            "check_return_eligibility",
            order_id=7,
            reason="regret",
            purchase_channel="online",
        )
        assert second["verdict"] == "ineligible"
        assert second["days_since_estimated_delivery"] == 36

    def test_return_inside_the_window_with_an_earlier_clock(self, context):
        context.clock = FrozenClock(datetime.fromisoformat("2026-02-20T10:00:00-04:00"))
        context.session.verified_customer_id = 14
        result = call(
            context,
            "check_return_eligibility",
            order_id=7,
            reason="regret",
            purchase_channel="online",
            condition_ok=True,
        )
        assert result["verdict"] == "eligible"

    def test_handoff_is_idempotent_per_kind(self, context):
        first = call(context, "create_handoff", kind="complaint", summary="Late delivery")
        second = call(context, "create_handoff", kind="complaint", summary="Late delivery again")
        third = call(context, "create_handoff", kind="human_request", summary="Wants a person")
        assert first["protocol"] == second["protocol"] != third["protocol"]
        assert first["response_deadline"] == "24 business hours"

    def test_handoff_does_not_block_other_conversations(self, context, db_path):
        call(context, "create_handoff", kind="complaint", summary="Late delivery")
        other = connect(db_path)
        other.execute("PRAGMA busy_timeout = 0")
        other.execute(
            "INSERT INTO sessions (session_id, created_at, last_seen_at) VALUES ('o', 'x', 'x')"
        )
        other.commit()
        other.close()

    def test_handoff_summary_is_redacted(self, context):
        call(context, "create_handoff", kind="complaint", summary="Call me on (67) 99999-1234")
        row = context.connection.execute("SELECT summary FROM handoffs").fetchone()
        assert "99999" not in row["summary"]


class TestToolErrors:
    def test_bad_arguments_return_structure(self, context):
        result = call(context, "quote_price", product_id="abc", payment_method="pix")
        assert result["error"] == "invalid_arguments"

    def test_malformed_json_is_reported(self, context):
        run = run_tool(TOOLS["get_order"], "{not json", context)
        assert json.loads(run.output)["ok"] is False
        assert run.ok is False
