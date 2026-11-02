import re

import pytest

from emporio.config import ROOT
from emporio.policies.extract import INVISIBLE, extract_sections
from emporio.policies.retrieve import Bm25Retriever


@pytest.fixture(scope="module")
def sections():
    return {s.section_id: s for s in extract_sections(ROOT / "data" / "políticas_da_loja.pdf")}


def test_sections_follow_the_manuals_numbering(sections):
    for section_id in ("1.2", "2", "3", "3.1", "4.1", "4.4", "5.2", "6.2", "7.3", "8.1", "9", "10"):
        assert section_id in sections


def test_noise_is_removed(sections):
    text = "\n".join(s.body for s in sections.values())
    assert not re.search(r"Página \d", text)
    assert "Manual de Políticas e Procedimentos" not in text
    assert not any(character in text for character in INVISIBLE)


def test_tables_survive_as_rows(sections):
    assert "Sábado | 09:00 às 13:00" in sections["2"].body
    assert "PIX | Pagamento à vista | 5% de desconto sobre o preço de tabela" in sections["3"].body
    assert "SEDEX (Correios) | 2 a 5 dias úteis | Sim | Incluído" in sections["5.2"].body
    assert "Telefone / WhatsApp | (67) 3341-4444" in sections["1.2"].body


def test_sections_crossing_pages_stay_whole(sections):
    assert "PAC (Correios)" in sections["5.2"].body
    assert "recusar o recebimento" in sections["5.2"].body
    assert "Lei nº" in sections["9"].body
    assert "exclusão de seus dados" in sections["9"].body


def test_rules_still_match_the_manual(sections, rules):
    payment, shipping, returns = rules.payment, rules.shipping, rules.returns
    assert f"{payment.pix_discount_percent}% de desconto" in sections["3"].body
    installments = sections["3.1"].body
    assert "até 3x" in installments and "R$ 50,00" in installments
    assert "4x a 6x" in installments and "R$ 80,00" in installments
    assert "7x a 12x" in installments and "R$ 100,00" in installments
    assert "R$ 2.000,00" in installments
    assert "acima de R$ 500,00" in sections["5.1"].body
    assert "R$ 35,00" in sections["5.1"].body
    assert f"até {returns.regret_days} (sete) dias corridos" in sections["4.1"].body
    assert f"{returns.refund_business_days} dias úteis" in sections["4.1"].body
    assert f"até {returns.defect_exchange_days} (trinta) dias" in sections["4.2"].body
    assert f"até {returns.preference_exchange_days} dias" in sections["4.3"].body
    warranty = " ".join(sections["8.1"].body.split())
    assert f"{returns.legal_warranty_days} (noventa) dias" in warranty
    assert rules.handoff.complaint_response.split()[0] in sections["7.3"].body
    assert all(m.days.split()[0] in sections["5.2"].body for m in shipping.other_cities)


def test_store_facts_match_the_manual(sections, facts):
    assert facts.phone in sections["1.2"].body
    assert facts.whatsapp in sections["7"].body
    assert "Rua 14 de Maio, 3200" in facts.address


def test_retrieval_finds_the_right_section(sections):
    retriever = Bm25Retriever(list(sections.values()))
    top = retriever.search("quero trocar a cor do violão", top_k=3)
    assert "4.3" in [hit.section.section_id for hit in top]


def test_retrieval_handles_accentless_queries(sections):
    retriever = Bm25Retriever(list(sections.values()))
    top = retriever.search("garantia legal dias", top_k=1)
    assert top[0].section.section_id == "8.1"


def test_empty_query_returns_nothing(sections):
    assert Bm25Retriever(list(sections.values())).search("de a o") == []
