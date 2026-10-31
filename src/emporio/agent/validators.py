"""Deterministic checks on every reply before it reaches the customer."""

import re
from decimal import Decimal, InvalidOperation

from emporio.memory.redact import EMAIL, PHONE
from emporio.text import normalize_email, normalize_phone

_NUMBER = r"\d[\d.,]*\d|\d"
MONEY = re.compile(rf"R\$\s*({_NUMBER})")
PERCENT = re.compile(rf"({_NUMBER})\s*%")
ANY_NUMBER = re.compile(_NUMBER)


ENGLISH_WORDS = re.compile(
    r"\b(the|we're|within|would|your|you|details|please|refund|window|store|announcement)\b"
)
PORTUGUESE_MARKERS = re.compile(r"\b(não|você|está|são|também|pra|para|com)\b")
GLUED_CAPITALS = re.compile(r"[a-zà-ÿ][A-Z]{3,}")


def language_problems(reply: str) -> list[str]:
    """Generation glitches seen live: 'euCOMPARE', or English words in a Portuguese reply."""
    problems = [m[0] for m in GLUED_CAPITALS.finditer(reply)]
    lowered = reply.lower()
    if PORTUGUESE_MARKERS.search(lowered):
        problems += sorted({m[0] for m in ENGLISH_WORDS.finditer(lowered)})
    return problems


def clean_format(reply: str) -> str:
    """The chat shows plain text, so markdown emphasis would appear as literal asterisks."""
    return reply.replace("**", "").strip()


def parse_number(text: str) -> Decimal | None:
    """Read Brazilian or English number formats: 2.199,00 / 2,199.00 / 2199 / 2.199."""
    last_dot, last_comma = text.rfind("."), text.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        decimal_mark = "," if last_comma > last_dot else "."
    elif last_comma >= 0:
        decimal_mark = "," if len(text) - last_comma - 1 != 3 else ""
    elif last_dot >= 0:
        groups = text.split(".")
        decimal_mark = "." if len(groups) == 2 and len(groups[1]) != 3 else ""
    else:
        decimal_mark = ""

    integer, _, fraction = text.rpartition(decimal_mark) if decimal_mark else (text, "", "")
    digits = re.sub(r"\D", "", integer)
    try:
        return Decimal(f"{digits}.{fraction}" if fraction else digits).normalize() + 0
    except InvalidOperation:
        return None


def number_tokens(text: str) -> set[str]:
    """Every number in a text, normalized for comparison."""
    parsed = (parse_number(match) for match in ANY_NUMBER.findall(text))
    return {format(value, "f") for value in parsed if value is not None}


def unsupported_amounts(reply: str, evidence: set[str]) -> list[str]:
    """Money and percentages in the reply that no tool or fact supports."""
    found = []
    for match in (*MONEY.finditer(reply), *PERCENT.finditer(reply)):
        value = parse_number(match[1])
        if value is None or format(value, "f") not in evidence:
            found.append(match[0])
    return found


def leaked_contacts(reply: str, allowed: set[str]) -> list[str]:
    """Phones and e-mails the customer did not type and that are not the store's."""
    found = [m[0] for m in EMAIL.finditer(reply) if normalize_email(m[0]) not in allowed]
    found += [m[0] for m in PHONE.finditer(reply) if normalize_phone(m[0]) not in allowed]
    return found


def contacts_in(text: str) -> set[str]:
    return {normalize_email(m[0]) for m in EMAIL.finditer(text)} | {
        normalize_phone(m[0]) for m in PHONE.finditer(text)
    }
