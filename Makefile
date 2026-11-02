.DEFAULT_GOAL := help
.PHONY: help setup ingest run llm-test test lint eval benchmark-retrieval examples verify

help: ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-22s %s\n", $$1, $$2}'

setup: ## Install dependencies and create .env if absent
	uv sync
	@test -f .env || (cp .env.example .env && echo "Created .env: add LLM_API_KEY")

ingest: ## Rebuild SQLite and the policy index from data/
	uv run python -m emporio.ingest

run: ## Start the chat app at http://127.0.0.1:8000
	uv run python -m emporio.web

llm-test: ## Real MiniMax check: auth, completion, tool call, usage
	uv run python -m emporio.llm.check

test: ## Offline test suite (no credentials or network)
	uv run pytest

lint: ## ruff and mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

eval: ## Live evaluation against MiniMax
	uv run python -m evaluation.run_eval

benchmark-retrieval: ## Compare retrieval strategies on labeled questions
	uv run --group benchmark python -m evaluation.benchmark_retrieval

examples: ## Regenerate example conversations with the real agent
	uv run python -m evaluation.make_examples

verify: ## Lint, test, ingest; live checks when a key exists
	uv run python -m evaluation.verify
