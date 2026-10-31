"""Text normalization shared by catalog search and verification."""

import re
import unicodedata

import snowballstemmer

_stemmer = snowballstemmer.stemmer("portuguese")

STOPWORDS = frozenset(
    [
        "a",
        "o",
        "as",
        "os",
        "um",
        "uma",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "por",
        "para",
        "com",
        "sem",
        "e",
        "ou",
        "que",
        "se",
        "eu",
        "me",
        "meu",
        "minha",
        "voce",
        "voces",
        "vcs",
        "tem",
        "ter",
        "ser",
        "estar",
        "qual",
        "quais",
        "como",
        "quando",
        "onde",
        "posso",
        "pode",
        "ao",
        "aos",
        "the",
        "is",
        "it",
    ]
)


def fold(text: str) -> str:
    """Lowercase and remove accents."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def tokens(text: str) -> list[str]:
    """Split into search tokens. 'D-28' and 'D28' give the same token."""
    joined = re.sub(r"(?<=[a-z0-9])-(?=[a-z0-9])", "", fold(text))
    return re.findall(r"[a-z0-9]+", joined)


def analyze(text: str) -> list[str]:
    """Search terms: folded, without stopwords, stemmed. Terms with digits stay intact."""
    words = [word for word in tokens(text) if word not in STOPWORDS]
    return [word if re.search(r"\d", word) else _stemmer.stemWord(word) for word in words]


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return digits[2:] if digits.startswith("55") and len(digits) > 11 else digits


def normalize_email(email: str) -> str:
    return email.strip().lower()
