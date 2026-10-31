"""Section retrieval over the manual. The strategy was picked by evaluation/benchmark_retrieval."""

from dataclasses import dataclass
from typing import Protocol

from rank_bm25 import BM25Okapi

from emporio.policies.extract import Section
from emporio.text import analyze


@dataclass(frozen=True)
class Hit:
    section: Section
    score: float


class Retriever(Protocol):
    def search(self, query: str, top_k: int = 3) -> list[Hit]: ...


class Bm25Retriever:
    def __init__(self, sections: list[Section]) -> None:
        self._sections = sections
        corpus = [analyze(f"{s.title} {s.title} {s.body}") for s in sections]
        self._index = BM25Okapi(corpus)

    def search(self, query: str, top_k: int = 3) -> list[Hit]:
        analyzed = analyze(query)
        if not analyzed:
            return []
        scores = self._index.get_scores(analyzed)
        ranked = sorted(zip(self._sections, scores, strict=True), key=lambda p: -p[1])
        return [Hit(section, float(score)) for section, score in ranked[:top_k] if score > 0]
