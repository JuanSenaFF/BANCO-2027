from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import update_vagas as core

# Empresas prioritárias definidas para o radar BANCO 2027.
PRIORITY_COMPANIES = [
    "Itaú", "Bradesco", "Santander", "BTG Pactual", "Nubank", "Banco Inter", "C6 Bank", "XP",
    "Safra", "Mercado Pago", "Stone", "PagBank", "B3", "Núclea", "CERC", "Cielo", "Rede",
    "Getnet", "Dock", "Pismo", "Banco BV", "Daycoval", "Banco ABC Brasil", "Banco PAN", "Banco BMG",
    "Neon", "PicPay", "Creditas", "Will Bank", "Genial Investimentos", "EQI Investimentos", "Rico",
    "Clear", "Avenue", "Sicoob", "Sicredi", "Sinqia", "Matera", "FitBank",
]

ENTRY_LEVEL_TERMS = [
    "analyst i", "analista i", "level i", "nível 1", "nivel 1", "entry level", "entry-level",
    "early career", "graduate", "estágio", "estagio", "estagiário", "estagiario", "estagiária",
    "estagiaria", "intern", "internship",
]

NON_ENTRY_TITLE_TERMS = [
    " spec ii", " spec iii", " spec iv", " spec v",
    " analyst ii", " analyst iii", " analyst iv", " analyst v",
    " analista ii", " analista iii", " analista iv", " analista v",
    " developer ii", " developer iii", " developer iv", " developer v",
    " desenvolvedor ii", " desenvolvedor iii", " desenvolvedor iv", " desenvolvedor v",
]

EXTRA_KEYWORDS = [
    "technology analyst i banco", "analista tecnologia nivel i banco", "software analyst i fintech",
    "data analyst i banco", "cloud analyst i fintech", "sre junior banco", "infraestrutura junior banco",
]

# Nomes curtos não devem ser aprovados por substring (ex.: Clear != ClearSale).
ALIASES = {
    "itau": {"itau", "itauunibanco"},
    "santander": {"santander", "santanderbrasil"},
    "inter": {"inter", "bancointer"},
    "xp": {"xp", "xpinc"},
    "daycoval": {"daycoval", "bancodaycoval"},
    "eqi": {"eqi", "eqiinvestimentos"},
}


def enhanced_approved_company(company: str) -> bool:
    c = core.canon_company(company)
    if not c:
        return False
    exact = {core.canon_company(name) for name in core.TARGET_COMPANIES}
    if c in exact:
        return True
    for values in ALIASES.values():
        if c in values:
            return True
    # Só aceita correspondência parcial quando ambos os lados são nomes longos.
    for target in core.TARGET_COMPANIES:
        t = core.canon_company(target)
        if len(c) >= 8 and len(t) >= 8 and (c in t or t in c):
            return True
    return False


def enhanced_linkedin_urls() -> list[str]:
    out: list[str] = []

    def add(urls: list[str]) -> None:
        for url in urls:
            if url not in out:
                out.append(url)

    # Buscas genéricas preservam descoberta fora da lista prioritária.
    for keyword in core.LINKEDIN_KEYWORDS:
        add(core.linkedin_query_urls(keyword, (0, 10)))

    # Uma consulta por empresa prioritária. Evitamos uma segunda tentativa redundante por empresa:
    # o objetivo é ampliar cobertura sem transformar o workflow numa coleta excessivamente longa.
    for company in PRIORITY_COMPANIES:
        query = f'"{company}" AND (software OR tecnologia OR dados OR data OR cloud OR sistemas OR backend OR sre)'
        add(core.linkedin_query_urls(query, (0,)))

    print(f"[source] LinkedIn: {len(out)} URLs")
    return out


def configure() -> None:
    core.MAX_NEW = 25
    core.TIMEOUT = 10
    core.LINKEDIN_PRIORITY_COMPANIES = PRIORITY_COMPANIES[:]
    core.LINKEDIN_KEYWORDS = list(dict.fromkeys(core.LINKEDIN_KEYWORDS + EXTRA_KEYWORDS))
    core.JUNIOR_TERMS = list(dict.fromkeys(core.JUNIOR_TERMS + ENTRY_LEVEL_TERMS))
    core.SENIOR_TITLE_TERMS = list(dict.fromkeys(core.SENIOR_TITLE_TERMS + NON_ENTRY_TITLE_TERMS))
    core.EXCLUDED_TITLE_FRAGMENTS = [
        fragment for fragment in core.EXCLUDED_TITLE_FRAGMENTS
        if core.norm(fragment) != core.norm("analista de projetos de tecnologia júnior")
    ]
    core.approved_company = enhanced_approved_company
    core.linkedin_urls = enhanced_linkedin_urls


def main() -> int:
    configure()
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
