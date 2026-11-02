from datetime import date, datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from emporio.domain.availability import Availability, availability_of
from emporio.domain.hours import store_status
from emporio.domain.money import format_brl, to_money
from emporio.domain.pricing import (
    PaymentMethod,
    installments_valid,
    max_installments,
    promotional_price,
    quote,
)
from emporio.domain.returns import (
    PurchaseChannel,
    ReturnReason,
    ReturnRequest,
    Verdict,
    evaluate_return,
)
from emporio.domain.shipping import shipping_for

ZONE = ZoneInfo("America/Campo_Grande")


class TestMoney:
    def test_rounds_half_up(self):
        assert to_money("1.005") == D("1.01")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (D("2199"), "R$ 2.199,00"),
            (D("159.9"), "R$ 159,90"),
            (D("19567"), "R$ 19.567,00"),
        ],
    )
    def test_brazilian_format(self, value, expected):
        assert format_brl(value) == expected


class TestPricing:
    def test_pix_discount_without_promotion(self, rules):
        result = quote(D("2199"), None, PaymentMethod.PIX, 1, rules.payment)
        assert result.final_price == D("2089.05")
        assert result.pix_discount_percent == 5

    def test_pix_does_not_stack_on_promotion(self, rules):
        result = quote(D("2399"), 18, PaymentMethod.PIX, 1, rules.payment)
        assert result.final_price == D("1967.18")
        assert result.pix_discount_percent is None
        assert result.notes

    def test_promotional_price_values(self):
        assert promotional_price(D("549"), 20) == D("439.20")
        assert promotional_price(D("359"), 10) == D("323.10")
        assert promotional_price(D("5999"), 8) == D("5519.08")

    @pytest.mark.parametrize(
        ("total", "installments", "valid"),
        [
            (D("150.00"), 3, True),  # exactly R$ 50 each
            (D("149.99"), 3, False),
            (D("320.00"), 4, True),  # exactly R$ 80 each
            (D("319.99"), 4, False),
            (D("480.00"), 6, True),
            (D("479.99"), 6, False),
            (D("700.00"), 7, True),  # exactly R$ 100 each, tier changes at 7x
            (D("699.99"), 7, False),
            (D("1200.00"), 12, True),
            (D("1199.99"), 12, False),
            (D("10000"), 13, False),
            (D("10"), 1, True),
        ],
    )
    def test_installment_boundaries(self, rules, total, installments, valid):
        assert installments_valid(total, installments, rules.payment) is valid

    def test_section_3_1_beats_the_flat_minimum_in_the_table(self, rules):
        assert installments_valid(D("400"), 5, rules.payment)

    @pytest.mark.parametrize(
        ("total", "expected"),
        [(D("459.90"), 5), (D("159.90"), 3), (D("120.00"), 2), (D("590"), 6), (D("2199"), 12)],
    )
    def test_max_installments(self, rules, total, expected):
        assert max_installments(total, rules.payment) == expected

    def test_refused_installments_explain_the_limit(self, rules):
        result = quote(D("459.90"), None, PaymentMethod.CREDIT, 6, rules.payment)
        assert not result.installments_allowed
        assert result.installment_value is None
        assert result.max_installments == 5

    def test_installments_use_promotional_price(self, rules):
        result = quote(D("2399"), 18, PaymentMethod.CREDIT, 12, rules.payment)
        assert result.final_price == D("1967.18")
        assert result.installment_value == D("163.93")

    def test_boleto_has_no_installments(self, rules):
        result = quote(D("1000"), None, PaymentMethod.BOLETO, 3, rules.payment)
        assert not result.installments_allowed


class TestAvailability:
    @pytest.mark.parametrize(
        ("status", "stock", "expected"),
        [
            ("active", 5, Availability.AVAILABLE),
            ("active", 0, Availability.OUT_OF_STOCK),
            ("discontinued", 13, Availability.DISCONTINUED),
            ("discontinued", 0, Availability.DISCONTINUED),
            ("coming_soon", 2, Availability.COMING_SOON),
        ],
    )
    def test_status_beats_quantity(self, status, stock, expected):
        assert availability_of(status, stock) is expected


class TestShipping:
    @pytest.mark.parametrize(
        ("value", "free", "fee", "undefined"),
        [
            (D("499.99"), False, D("35.00"), False),
            (D("500.00"), None, None, True),
            (D("500.01"), True, D("0.00"), False),
        ],
    )
    def test_metro_threshold(self, rules, value, free, fee, undefined):
        result = shipping_for("Campo Grande", value, rules.shipping)
        assert (result.free, result.fee, result.threshold_undefined) == (free, fee, undefined)

    def test_other_cities_never_get_a_price(self, rules):
        result = shipping_for("Dourados", D("10000"), rules.shipping)
        assert result.fee is None
        assert result.free is None
        assert len(result.modalities) == 3

    def test_city_matching_ignores_case_and_accents(self, rules):
        assert shipping_for("CAMPO GRANDE ", None, rules.shipping).region == "metro_campo_grande"


class TestHours:
    @pytest.mark.parametrize(
        ("moment", "is_open"),
        [
            ("2026-03-25 08:59", False),
            ("2026-03-25 09:00", True),
            ("2026-03-25 17:59", True),
            ("2026-03-25 18:00", False),
            ("2026-03-28 12:59", True),  # Saturday
            ("2026-03-28 13:00", False),
            ("2026-03-29 10:00", False),  # Sunday
            ("2026-05-01 10:00", False),  # fixed holiday, a Friday
            ("2026-04-03 10:00", False),  # Good Friday
        ],
    )
    def test_open_or_closed(self, facts, moment, is_open):
        now = datetime.fromisoformat(moment).replace(tzinfo=ZONE)
        assert store_status(now, facts).is_open is is_open

    def test_next_opening_after_saturday_close(self, facts):
        now = datetime(2026, 3, 28, 14, 0, tzinfo=ZONE)
        opening = store_status(now, facts).next_opening
        assert opening is not None
        assert (opening.date(), opening.hour) == (date(2026, 3, 30), 9)

    def test_next_opening_same_day_before_nine(self, facts):
        now = datetime(2026, 3, 25, 7, 0, tzinfo=ZONE)
        opening = store_status(now, facts).next_opening
        assert opening is not None
        assert (opening.date(), opening.hour) == (date(2026, 3, 25), 9)

    def test_next_opening_skips_a_holiday(self, facts):
        now = datetime(2026, 4, 2, 19, 0, tzinfo=ZONE)  # the evening before Good Friday
        opening = store_status(now, facts).next_opening
        assert opening is not None
        assert opening.date() == date(2026, 4, 4)


def delivered(
    reason: ReturnReason,
    channel: PurchaseChannel | None = PurchaseChannel.ONLINE,
    condition: bool | None = True,
    order: date = date(2026, 2, 3),
    delivery: date = date(2026, 2, 17),
) -> ReturnRequest:
    return ReturnRequest("delivered", order, delivery, reason, channel, condition)


class TestReturns:
    def test_regret_asks_for_channel_first(self, rules):
        request = delivered(ReturnReason.REGRET, channel=None)
        result = evaluate_return(request, date(2026, 2, 20), rules.returns)
        assert result.verdict is Verdict.NEEDS_INFO
        assert result.ask_customer == ("purchase_channel",)

    def test_regret_excludes_store_purchases(self, rules):
        request = delivered(ReturnReason.REGRET, PurchaseChannel.IN_STORE)
        result = evaluate_return(request, date(2026, 2, 20), rules.returns)
        assert result.verdict is Verdict.INELIGIBLE

    def test_regret_asks_for_condition(self, rules):
        request = delivered(ReturnReason.REGRET, condition=None)
        result = evaluate_return(request, date(2026, 2, 20), rules.returns)
        assert result.verdict is Verdict.NEEDS_INFO
        assert result.ask_customer == ("condition_ok",)

    def test_regret_rejected_when_used(self, rules):
        request = delivered(ReturnReason.REGRET, condition=False)
        result = evaluate_return(request, date(2026, 2, 20), rules.returns)
        assert result.verdict is Verdict.INELIGIBLE

    @pytest.mark.parametrize(
        ("today", "verdict"),
        [
            (date(2026, 2, 24), Verdict.ELIGIBLE),  # day 7
            (date(2026, 2, 25), Verdict.NEEDS_HUMAN),  # day 8: depends on the real delivery date
            (date(2026, 2, 27), Verdict.NEEDS_HUMAN),  # day 10
            (date(2026, 2, 28), Verdict.INELIGIBLE),  # day 11
        ],
    )
    def test_regret_window_limits(self, rules, today, verdict):
        result = evaluate_return(delivered(ReturnReason.REGRET), today, rules.returns)
        assert result.verdict is verdict

    def test_preference_exchange_needs_no_channel(self, rules):
        request = delivered(ReturnReason.PREFERENCE, channel=None)
        result = evaluate_return(request, date(2026, 2, 20), rules.returns)
        assert result.verdict is Verdict.ELIGIBLE
        assert "§4.4" in " ".join(result.caveats)

    @pytest.mark.parametrize(
        ("today", "verdict", "rule"),
        [
            (date(2026, 3, 5), Verdict.ELIGIBLE, "defect_exchange_4_2"),  # 30 days from purchase
            (date(2026, 3, 6), Verdict.NEEDS_HUMAN, "warranty_conflict_4_2_8_1"),
            (date(2026, 5, 18), Verdict.NEEDS_HUMAN, "warranty_conflict_4_2_8_1"),  # day 90
            (date(2026, 5, 21), Verdict.NEEDS_HUMAN, "warranty_conflict_4_2_8_1"),  # day 93
            (date(2026, 5, 22), Verdict.INELIGIBLE, "manufacturer_warranty_4_2"),
        ],
    )
    def test_defect_windows(self, rules, today, verdict, rule):
        result = evaluate_return(delivered(ReturnReason.DEFECT), today, rules.returns)
        assert (result.verdict, result.rule) == (verdict, rule)

    @pytest.mark.parametrize("status", ["pending", "confirmed", "shipped"])
    def test_undelivered_orders_go_to_a_human(self, rules, status):
        request = ReturnRequest(status, date(2026, 3, 1), None, ReturnReason.REGRET)
        result = evaluate_return(request, date(2026, 3, 25), rules.returns)
        assert result.verdict is Verdict.NEEDS_HUMAN

    def test_cancelled_orders_are_ineligible(self, rules):
        request = ReturnRequest("cancelled", date(2026, 3, 1), None, ReturnReason.DEFECT)
        result = evaluate_return(request, date(2026, 3, 25), rules.returns)
        assert result.verdict is Verdict.INELIGIBLE

    def test_every_date_based_verdict_discloses_the_proxy(self, rules):
        result = evaluate_return(delivered(ReturnReason.REGRET), date(2026, 3, 25), rules.returns)
        assert result.verdict is Verdict.INELIGIBLE
        assert "estimated delivery" in " ".join(result.caveats)
