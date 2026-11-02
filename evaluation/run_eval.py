"""Live evaluation against MiniMax: `make eval`. Use --only id,id to run some cases."""

import argparse
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import partial
from pathlib import Path

from emporio.config import ROOT, Settings
from emporio.ingest import ingest
from emporio.llm.factory import ConfigurationError, build_provider
from evaluation.harness import CaseResult, load_cases, render_report, run_case

RESULTS = ROOT / "evaluation" / "results" / "latest.md"
WORKERS = 1  # MiniMax Token Plans rate-limit parallel calls


def git_commit() -> str:
    output = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    )
    return output.stdout.strip() or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Comma-separated case ids")
    arguments = parser.parse_args()

    settings = Settings()
    try:
        build_provider(settings)
    except ConfigurationError as error:
        print(f"NOT RUN: {error}\nNo evaluation results were produced.", file=sys.stderr)
        return 2

    patient = settings.model_copy(update={"llm_max_retries": 6})
    cases = load_cases()
    if arguments.only:
        wanted = set(arguments.only.split(","))
        cases = [case for case in cases if case["id"] in wanted]

    with tempfile.TemporaryDirectory() as temporary:
        workdir = Path(temporary)
        seed = workdir / "seed.db"
        ingest(seed, settings.data_dir)
        run = partial(
            run_case,
            settings=settings,
            provider_factory=lambda: build_provider(patient),
            seed_db=seed,
            workdir=workdir,
        )
        results: list[CaseResult] = []
        with ThreadPoolExecutor(WORKERS) as pool:
            for result in pool.map(run, cases):
                label = "SKIP" if result.not_evaluated else "PASS" if result.passed else "FAIL"
                print(f"{label} {result.case['id']}", flush=True)
                results.append(result)

    header = (
        f"Date: {date.today()}. Model: {settings.llm_model}. Thinking: {settings.llm_thinking}. "
        f"Commit: {git_commit()}."
    )
    report = render_report(results, header)
    if not arguments.only:
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        RESULTS.write_text(report, encoding="utf-8")
        print(f"\nWrote {RESULTS}")
    print(report)
    critical_failed = any(r.case.get("critical") and not r.passed for r in results)
    incomplete = any(r.not_evaluated for r in results)
    if incomplete:
        print("INCOMPLETE: some cases could not reach the model.", file=sys.stderr)
    return 1 if critical_failed or incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
