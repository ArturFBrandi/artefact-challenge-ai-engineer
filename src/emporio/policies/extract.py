"""Turn the policy PDF into numbered sections.

Chunks follow the manual's section numbers rather than pages: sections 5.2 and 9 cross page
boundaries. Tables are read as text because PyMuPDF's find_tables() drops the spaces in cells.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

PAGE_HEADER = "Empório da Música Manual de Políticas e Procedimentos"
INVISIBLE = "​‌‍﻿"
HEADING = re.compile(r"^(\d{1,2}(?:\.\d)?)\.?\s+([A-ZÀ-Ú].{2,70})$")
BULLET = "•"

# Section 2 and the tables of 3 and 5.2 are read as flat cells, one per line.
TABLE_ROWS = {
    "2": (["Dia", "Horário"], 2),
    "3": (["Forma", "Condições", "Observações"], 3),
    "5.2": (["Modalidade", "Prazo Estimado", "Rastreamento", "Seguro"], 4),
    "1.2": (["Campo", "Informação"], 2),
}


@dataclass(frozen=True)
class Section:
    section_id: str
    title: str
    body: str


def _clean_page(text: str) -> list[str]:
    for character in INVISIBLE:
        text = text.replace(character, "")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not re.fullmatch(r"Página \d+", line)]
    if lines and lines[0] == PAGE_HEADER:
        lines = lines[1:]
    return lines


def _join_wrapped(lines: list[str]) -> list[str]:
    """Rejoin lines broken by the PDF layout, keeping bullets as separate items."""
    joined: list[str] = []
    for line in lines:
        if line == BULLET:
            joined.append(BULLET)
        elif joined and joined[-1] == BULLET:
            joined[-1] = f"{BULLET} {line}"
        elif joined and joined[-1].startswith(BULLET) and not joined[-1].endswith((".", ":")):
            joined[-1] = f"{joined[-1]} {line}"
        else:
            joined.append(line)
    return joined


def _merge_table(section_id: str, lines: list[str]) -> list[str]:
    """Rebuild 'a | b | c' rows when a table's header cells are found."""
    if section_id not in TABLE_ROWS:
        return lines
    header, columns = TABLE_ROWS[section_id]
    try:
        start = next(
            index for index in range(len(lines)) if lines[index : index + columns] == header
        )
    except StopIteration:
        return lines
    prefix, cells = lines[:start], lines[start + columns :]
    return prefix + _rows_from_cells(section_id, cells, columns)


def _rows_from_cells(section_id: str, cells: list[str], columns: int) -> list[str]:
    # Long cells wrap onto a second line. Each table's first column has known labels.
    row_starts = {
        "2": ("Segunda", "Sábado", "Domingo"),
        "3": ("PIX", "Cartão de Débito", "Cartão de Crédito", "Boleto"),
        "5.2": ("PAC", "SEDEX", "Jadlog"),
        "1.2": (
            "Razão Social",
            "Nome Fantasia",
            "CNPJ",
            "Endereço",
            "Telefone / WhatsApp",
            "E-mail",
            "Fundação",
        ),
    }[section_id]
    rows: list[list[str]] = []
    remainder: list[str] = []
    for cell in cells:
        if cell.startswith(row_starts):
            rows.append([cell])
        elif rows and not remainder:
            current = rows[-1]
            if len(current) < columns:
                current.append(cell)
            elif _is_prose(cell):
                remainder.append(cell)
            else:
                current[-1] = f"{current[-1]} {cell}"  # a long cell wrapped onto a second line
        else:
            remainder.append(cell)
    return [" | ".join(row) for row in rows] + remainder


def _is_prose(cell: str) -> bool:
    return len(cell) > 60


def extract_sections(pdf_path: Path) -> list[Section]:
    document: Any = pymupdf.open(pdf_path)  # type: ignore[no-untyped-call]
    with document:
        pages = [_clean_page(page.get_text()) for page in document]

    sections: list[tuple[str, str, list[str]]] = []
    for line in (line for page in pages[1:] for line in page):
        match = HEADING.match(line)
        if match and not line.endswith((".", ";")):
            sections.append((match[1], match[2].strip(), []))
        elif sections:
            sections[-1][2].append(line)

    result = []
    for section_id, title, lines in sections:
        merged = _merge_table(section_id, _join_wrapped(lines))
        result.append(Section(section_id, title, "\n".join(merged).strip()))
    return [section for section in result if section.body]
