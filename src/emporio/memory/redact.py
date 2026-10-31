"""Mask contact details before anything is stored."""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
PHONE = re.compile(r"(?<!\d)(?:\+?55\s?)?\(?\d{2}\)?[\s.-]?\d{4,5}[\s.-]?\d{4}(?!\d)")


def redact(text: str) -> str:
    return PHONE.sub("[phone]", EMAIL.sub("[email]", text))
