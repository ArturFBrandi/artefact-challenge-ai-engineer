"""One command to check everything that can be checked: `make verify`."""

import subprocess
import sys

from emporio.config import Settings

STEPS = [
    ("lint", ["make", "--no-print-directory", "lint"]),
    ("tests", ["make", "--no-print-directory", "test"]),
    ("ingest", ["make", "--no-print-directory", "ingest"]),
]
LIVE_STEPS = [
    ("llm-test", ["make", "--no-print-directory", "llm-test"]),
    ("eval", ["make", "--no-print-directory", "eval"]),
]


def main() -> int:
    has_key = bool(Settings().llm_api_key.get_secret_value())
    summary: list[tuple[str, str]] = []
    for name, command in STEPS + (LIVE_STEPS if has_key else []):
        print(f"\n=== {name} ===", flush=True)
        code = subprocess.run(command, check=False).returncode
        summary.append((name, "ok" if code == 0 else f"FAILED ({code})"))
    if not has_key:
        summary += [("llm-test", "SKIPPED: no LLM_API_KEY"), ("eval", "SKIPPED: no LLM_API_KEY")]

    print("\n=== summary ===")
    for name, status in summary:
        print(f"{name:10} {status}")
    return 1 if any("FAILED" in status for _, status in summary) else 0


if __name__ == "__main__":
    sys.exit(main())
