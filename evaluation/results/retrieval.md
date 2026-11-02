Retrieval benchmark: 28 questions, 25 sections, top 3.
Embedding model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

| Strategy | Recall@3 | MRR | Latency per query | Context tokens per query |
|---|---:|---:|---:|---:|
| BM25 | 0.86 | 0.77 | 0.3 ms | 257 |
| Embeddings | 0.64 | 0.62 | 6.2 ms | 291 |
| Hybrid (RRF) | 0.86 | 0.74 | 6.2 ms | 292 |
| Whole manual in the prompt | 1.00 | n/a | 0 ms | 2444 |
