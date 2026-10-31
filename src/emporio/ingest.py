"""Build the SQLite database from the provided files: `make ingest`."""

from pathlib import Path

from emporio.config import Settings
from emporio.data.db import session_scope
from emporio.data.loader import SCHEMA, LoadReport, load_csvs
from emporio.policies.extract import extract_sections

POLICY_PDF = "políticas_da_loja.pdf"


def ingest(db_path: Path, data_dir: Path) -> LoadReport:
    """Rebuild from scratch. Conversations live in the same file and are reset too."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    with session_scope(db_path) as connection:
        connection.executescript(SCHEMA.read_text(encoding="utf-8"))
        report = load_csvs(connection, data_dir)
        sections = extract_sections(data_dir / POLICY_PDF)
        connection.executemany(
            "INSERT INTO policy_sections VALUES (?, ?, ?)",
            [(s.section_id, s.title, s.body) for s in sections],
        )
    report.counts["policy_sections"] = len(sections)
    return report


def main() -> None:
    settings = Settings()
    print(ingest(settings.db_path, settings.data_dir).render())
    print(f"Database: {settings.db_path}")


if __name__ == "__main__":
    main()
