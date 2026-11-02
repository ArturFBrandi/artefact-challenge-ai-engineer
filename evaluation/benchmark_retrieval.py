"""Compare retrieval strategies on evaluation/retrieval.yaml: `make benchmark-retrieval`."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from fastembed import TextEmbedding

from emporio.config import ROOT, Settings
from emporio.policies.extract import Section, extract_sections
from emporio.policies.retrieve import Bm25Retriever

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
TOP_K = 3
RRF_K = 60
OUTPUT = ROOT / "evaluation" / "results" / "retrieval.md"

Ranker = Callable[[str], list[str]]


@dataclass
class Row:
    name: str
    recall: float
    mrr: float
    latency_ms: float
    context_tokens: int


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def score(name: str, ranker: Ranker, questions: list[dict], lookup: dict[str, Section]) -> Row:
    hits, reciprocal, spent, context = 0, 0.0, 0.0, 0
    for item in questions:
        started = time.perf_counter()
        ranked = ranker(item["q"])
        spent += time.perf_counter() - started
        top = ranked[:TOP_K]
        hits += any(section in top for section in item["expected"])
        ranks = [i + 1 for i, s in enumerate(ranked) if s in item["expected"]]
        reciprocal += 1 / ranks[0] if ranks else 0
        context += sum(estimate_tokens(lookup[s].body) for s in top)
    n = len(questions)
    return Row(name, hits / n, reciprocal / n, 1000 * spent / n, context // n)


def main() -> None:
    settings = Settings()
    questions = yaml.safe_load((ROOT / "evaluation" / "retrieval.yaml").read_text("utf-8"))
    sections = extract_sections(Path(settings.data_dir) / "políticas_da_loja.pdf")
    lookup = {s.section_id: s for s in sections}
    ids = [s.section_id for s in sections]

    bm25 = Bm25Retriever(sections)

    def bm25_rank(query: str) -> list[str]:
        return [hit.section.section_id for hit in bm25.search(query, top_k=len(sections))]

    embedder = TextEmbedding(model_name=MODEL)
    matrix = np.array(list(embedder.embed([f"{s.title}. {s.body}" for s in sections])))
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)

    def dense_rank(query: str) -> list[str]:
        vector = next(iter(embedder.embed([query])))
        scores = matrix @ (vector / np.linalg.norm(vector))
        return [ids[i] for i in np.argsort(-scores)]

    def hybrid_rank(query: str) -> list[str]:
        totals: dict[str, float] = {}
        for ranking in (bm25_rank(query), dense_rank(query)):
            for position, section_id in enumerate(ranking):
                totals[section_id] = totals.get(section_id, 0) + 1 / (RRF_K + position + 1)
        return sorted(totals, key=lambda key: -totals[key])

    rows = [
        score("BM25", bm25_rank, questions, lookup),
        score("Embeddings", dense_rank, questions, lookup),
        score("Hybrid (RRF)", hybrid_rank, questions, lookup),
    ]
    whole_manual = sum(estimate_tokens(s.body) for s in sections)

    lines = [
        f"Retrieval benchmark: {len(questions)} questions, {len(sections)} sections, top {TOP_K}.",
        f"Embedding model: `{MODEL}`.",
        "",
        "| Strategy | Recall@3 | MRR | Latency per query | Context tokens per query |",
        "|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {r.name} | {r.recall:.2f} | {r.mrr:.2f} | {r.latency_ms:.1f} ms | {r.context_tokens} |"
        for r in rows
    ]
    lines.append(f"| Whole manual in the prompt | 1.00 | n/a | 0 ms | {whole_manual} |")
    report = "\n".join(lines) + "\n"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
