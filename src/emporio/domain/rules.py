"""Typed access to config/policy_rules.yaml and config/store_facts.yaml."""

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class InstallmentTier(_Frozen):
    up_to: int
    min_installment_brl: Decimal


class PaymentRules(_Frozen):
    pix_discount_percent: Decimal
    combined_payment_above_brl: Decimal
    installment_tiers: tuple[InstallmentTier, ...]


class ShippingModality(_Frozen):
    name: str
    days: str


class ShippingRules(_Frozen):
    metro_free_above_brl: Decimal
    metro_flat_fee_brl: Decimal
    metro_days: str
    other_cities: tuple[ShippingModality, ...]


class ReturnRules(_Frozen):
    regret_days: int
    defect_exchange_days: int
    preference_exchange_days: int
    legal_warranty_days: int
    refund_business_days: int
    estimate_margin_days: int


class HandoffRules(_Frozen):
    complaint_response: str


class PolicyRules(_Frozen):
    payment: PaymentRules
    shipping: ShippingRules
    returns: ReturnRules
    handoff: HandoffRules


class StoreFacts(_Frozen):
    name: str
    tagline: str
    founded: int
    address: str
    phone: str
    whatsapp: str
    email: str
    hours: dict[int, tuple[str, str]]
    holidays_fixed: tuple[str, ...]
    holidays_movable: tuple[str, ...]


def load_rules(config_dir: Path) -> PolicyRules:
    text = (config_dir / "policy_rules.yaml").read_text(encoding="utf-8")
    return PolicyRules.model_validate(yaml.safe_load(text))


def load_facts(config_dir: Path) -> StoreFacts:
    text = (config_dir / "store_facts.yaml").read_text(encoding="utf-8")
    return StoreFacts.model_validate(yaml.safe_load(text))
