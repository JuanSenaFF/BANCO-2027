"""One company allowlist for discovery, API qualification and final validation.

Company identity uses exact normalized aliases, never substring matches. Being
an allowed company does not bypass role, seniority, requirements or geography
checks. Consultancies still need explicit financial context in the vacancy.
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TargetCompany:
    name: str
    aliases: tuple[str, ...] = ()
    search_tier: Literal["core", "expanded", "discovery"] = "expanded"


# Search tiers preserve the existing query budgets of both collector versions.
# "discovery" companies are allowed when found, without an extra LinkedIn query.
COMPANIES = (
    TargetCompany("Itaú", ("Itaú Unibanco",), "core"),
    TargetCompany("Bradesco", search_tier="core"),
    TargetCompany("Santander", ("Santander Brasil",), "core"),
    TargetCompany("BTG Pactual", search_tier="core"),
    TargetCompany("Nubank", search_tier="core"),
    TargetCompany("Banco Inter", ("Inter",), "core"),
    TargetCompany("C6 Bank", search_tier="core"),
    TargetCompany("XP", ("XP Inc.",), "core"),
    TargetCompany("Safra"),
    TargetCompany("Mercado Pago", search_tier="core"),
    TargetCompany("Stone", search_tier="core"),
    TargetCompany("PagBank", (
        "PagSeguro", "PagSeguro PagBank",
        "PagSeguro Internet Instituição de Pagamento S.A.",
    ), "core"),
    TargetCompany("B3", search_tier="core"),
    TargetCompany("Núclea"),
    TargetCompany("CERC"),
    TargetCompany("Cielo", search_tier="core"),
    TargetCompany("Rede"),
    TargetCompany("Getnet"),
    TargetCompany("Dock"),
    TargetCompany("Pismo", search_tier="core"),
    TargetCompany("Banco BV"),
    TargetCompany("Daycoval", ("Banco Daycoval",)),
    TargetCompany("Banco ABC Brasil"),
    TargetCompany("Banco PAN"),
    TargetCompany("Banco BMG"),
    TargetCompany("Neon"),
    TargetCompany("PicPay", search_tier="core"),
    TargetCompany("Creditas"),
    TargetCompany("Will Bank"),
    TargetCompany("Genial Investimentos"),
    TargetCompany("EQI Investimentos", ("EQI",)),
    TargetCompany("Rico"),
    TargetCompany("Clear"),
    TargetCompany("Avenue"),
    TargetCompany("Sicoob"),
    TargetCompany("Sicredi", search_tier="core"),
    TargetCompany("Sinqia"),
    TargetCompany("Matera"),
    TargetCompany("FitBank"),
    TargetCompany("Agibank"),
    TargetCompany("Banco Carrefour"),
    TargetCompany("Banco Mercantil"),
    TargetCompany("Banco Sofisa"),
    TargetCompany("Banco Pine"),
    TargetCompany("Banco Rendimento"),
    TargetCompany("Banco Bari"),
    TargetCompany("Digio", ("Banco Digio",)),
    TargetCompany("Banco Modal"),
    TargetCompany("EBANX"),
    TargetCompany("CloudWalk"),
    TargetCompany("InfinitePay"),
    TargetCompany("Asaas"),
    TargetCompany("Celcoin"),
    TargetCompany("QI Tech"),
    TargetCompany("Stark Bank"),
    TargetCompany("Conta Simples"),
    # Explicit technology targets: no financial context is required.
    TargetCompany("Microsoft", (
        "Microsoft Brasil", "Microsoft Brazil", "Microsoft do Brasil",
        "Microsoft Corporation", "Microsoft Corp.",
    ), "core"),
    TargetCompany("Google", (
        "Google Brasil", "Google Brazil", "Google do Brasil", "Google LLC",
    ), "core"),
    TargetCompany("RecargaPay"),
    TargetCompany("Zoop"),
    TargetCompany("Vindi"),
    TargetCompany("Fiserv"),
    TargetCompany("ANBIMA", search_tier="discovery"),
    TargetCompany("BMP", search_tier="discovery"),
    TargetCompany("Grupo Bancorbrás", search_tier="discovery"),
    TargetCompany("Via Certa Promotora", search_tier="discovery"),
    TargetCompany("Nava | Tech for Business", ("Nava",), "discovery"),
)

TARGET_COMPANIES = tuple(name for company in COMPANIES for name in (company.name, *company.aliases))
PRIORITY_COMPANIES = tuple(company.name for company in COMPANIES if company.search_tier != "discovery")
CORE_PRIORITY_COMPANIES = tuple(company.name for company in COMPANIES if company.search_tier == "core")
CONTEXT_COMPANIES = (
    "Tata Consultancy Services", "TCS", "FCamara", "Qaracter", "Stefanini", "Capgemini", "Accenture",
)


def normalize_company(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


COMPANY_CANONICAL_KEYS = {
    normalize_company(alias): normalize_company(company.name)
    for company in COMPANIES
    for alias in (company.name, *company.aliases)
}
TARGET_KEYS = frozenset(COMPANY_CANONICAL_KEYS)
CONTEXT_KEYS = frozenset(normalize_company(name) for name in CONTEXT_COMPANIES)


def is_target_company(company: str) -> bool:
    return normalize_company(company) in TARGET_KEYS


def company_identity(company: str) -> str:
    """Return an exact canonical identity for known aliases and unknown names."""
    key = normalize_company(company)
    return COMPANY_CANONICAL_KEYS.get(key, key)


def same_company_name(first: str, second: str) -> bool:
    """Compare employers without unsafe substring matching."""
    first_key = company_identity(first)
    second_key = company_identity(second)
    return bool(first_key and second_key and first_key == second_key)


def is_contextual_company(company: str) -> bool:
    return normalize_company(company) in CONTEXT_KEYS
