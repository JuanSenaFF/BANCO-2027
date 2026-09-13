"""Career-market classification for the BANCO 2027 vacancy catalog.

The market sample stays broad, while the personal learning plan remains centered
on Python, data and automation.  The annotations produced here are deliberately
plain data so the browser and future database consumers can use the same model.
"""
from __future__ import annotations

import re
import unicodedata


FOCUS_SKILLS = {"python", "sql", "data", "auto", "api"}
OTHER_STACK_SKILLS = {"java", "spring", "dotnet", "js"}

REFERENCE_INSTITUTIONS = {
    "itau", "itauunibanco", "bradesco", "santander", "santanderbrasil",
    "btgpactual", "nubank", "bancointer", "inter", "c6bank", "xp", "xpinc",
    "safra", "mercadopago", "stone", "pagbank", "b3", "cielo", "getnet",
    "bancobv", "bv",
}
CONSULTANCIES = {
    "tataconsultancyservices", "tcs", "fcamara", "qaracter", "stefanini",
    "capgemini", "accenture", "nava", "navatechforbusiness",
}

CORE_TECH_TITLE_RE = re.compile(
    r"software|backend|back.?end|front.?end|full.?stack|developer|desenvolv|"
    r"engenheir[oa] (?:de )?(?:dados|data|software|machine learning)|"
    r"data (?:analyst|engineer|scientist)|cientista de dados|analista de dados|"
    r"cloud|\bsre\b|devops|automa(?:c|ç)(?:a|ã)o|sistemas|tecnologia|\bti\b|"
    r"cyber|seguran(?:c|ç)a|\bqa\b|\bdba\b|banco de dados|qualidade de software|infraestrutura"
)
FINANCE_ROLE_RE = re.compile(
    r"risco|cr[eé]dito|fraude|compliance|opera(?:c|ç)(?:a|ã)o|financeir|"
    r"tesouraria|investimento|pricing|produto|canais|neg[oó]cio|auditoria|controladoria"
)
SAO_PAULO_RE = re.compile(
    r"s[aã]o paulo|\bsp\b|barueri|osasco|alphaville|campinas|jundia[ií]|"
    r"santo andr[eé]|s[aã]o bernardo|guarulhos|sorocaba"
)
OTHER_LOCATION_RE = re.compile(
    r"rio de janeiro|\brj\b|minas gerais|\bmg\b|belo horizonte|paran[aá]|\bpr\b|"
    r"curitiba|rio grande do sul|\brs\b|porto alegre|santa catarina|\bsc\b|"
    r"florian[oó]polis|recife|pernambuco|\bpe\b|bahia|\bba\b|salvador|"
    r"bras[ií]lia|distrito federal|\bdf\b|fortaleza|cear[aá]|\bce\b|m[eé]xico|mexico"
)


def norm(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if unicodedata.category(char) != "Mn").lower()


def compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", norm(value))


def geography(job: dict) -> dict:
    """Classify São Paulo/remote eligibility without inventing a location."""
    location = norm(job.get("location"))
    modality = norm(job.get("modality"))
    search_scope = norm(job.get("searchScopeLocation"))
    if "remot" in modality or "remot" in location:
        return {
            "geographyScope": "remote_brazil",
            "geographyLabel": "Remoto no Brasil",
            "geographyEligible": True,
            "geographyWeight": 1.0,
        }
    if SAO_PAULO_RE.search(location):
        return {
            "geographyScope": "sao_paulo",
            "geographyLabel": "São Paulo",
            "geographyEligible": True,
            "geographyWeight": 1.0,
        }
    if OTHER_LOCATION_RE.search(location):
        return {
            "geographyScope": "outside_scope",
            "geographyLabel": "Fora de São Paulo",
            "geographyEligible": False,
            "geographyWeight": 0.0,
        }
    # LinkedIn discovery is always executed with the São Paulo geoId. Older
    # records predate the explicit searchScopeLocation field, so preserve that
    # query evidence while still marking the actual workplace as unverified.
    linkedin_scope = norm(job.get("sourceProvider")) == "linkedin"
    if "sao paulo" in search_scope or "são paulo" in str(job.get("searchScopeLocation") or "").lower() or linkedin_scope:
        return {
            "geographyScope": "sao_paulo_unverified",
            "geographyLabel": "Busca São Paulo · local a confirmar",
            "geographyEligible": True,
            "geographyWeight": 0.7,
        }
    return {
        "geographyScope": "unverified",
        "geographyLabel": "Local a confirmar",
        "geographyEligible": False,
        "geographyWeight": 0.0,
    }


def institution(job: dict) -> dict:
    company = compact(job.get("company"))
    if company in REFERENCE_INSTITUTIONS:
        return {
            "institutionTier": "reference",
            "institutionTierLabel": "Instituição de referência",
            "institutionWeight": 1.25,
        }
    if company in CONSULTANCIES:
        return {
            "institutionTier": "consulting",
            "institutionTierLabel": "Consultoria do ecossistema",
            "institutionWeight": 0.75,
        }
    return {
        "institutionTier": "ecosystem",
        "institutionTierLabel": "Ecossistema financeiro",
        "institutionWeight": 1.0,
    }


def _skill_sets(job: dict) -> tuple[set[str], set[str]]:
    required: set[str] = set()
    differential: set[str] = set()
    records = job.get("requirementsStructured") or []
    for record in records:
        if not isinstance(record, dict) or record.get("category") != "technical":
            continue
        target = differential if record.get("requirementType") == "differential" else required
        target.update(str(skill) for skill in (record.get("profileSkillIds") or []) if skill)
    return required, differential


def classify(job: dict) -> dict:
    required, differential = _skill_sets(job)
    title = norm(job.get("role"))
    core_title = bool(CORE_TECH_TITLE_RE.search(title))
    finance_title = bool(FINANCE_ROLE_RE.search(title))
    required_focus = required & FOCUS_SKILLS
    differential_focus = differential & FOCUS_SKILLS

    if core_title:
        segment = "core_technology"
        segment_label = "Tecnologia principal"
    elif required_focus:
        segment = "finance_with_technology"
        segment_label = "Negócio financeiro com tecnologia"
    elif differential_focus:
        segment = "technology_differential"
        segment_label = "Tecnologia como diferencial"
    else:
        segment = "market_context"
        segment_label = "Contexto de mercado"

    if required_focus and (core_title or len(required_focus) >= 2):
        alignment, alignment_label, career_weight = "target", "Alinhada ao foco", 1.0
    elif required_focus:
        alignment, alignment_label, career_weight = "adjacent", "Adjacente ao foco", 0.55
    elif differential_focus:
        alignment, alignment_label, career_weight = "context", "Contexto útil", 0.15
    elif core_title and required & OTHER_STACK_SKILLS:
        alignment, alignment_label, career_weight = "other_stack", "Outra stack", 0.0
    else:
        alignment, alignment_label, career_weight = "context", "Contexto de mercado", 0.0

    geo = geography(job)
    if not geo["geographyEligible"]:
        career_weight = 0.0
    else:
        career_weight *= geo["geographyWeight"]
    inst = institution(job)
    return {
        "marketSegment": segment,
        "marketSegmentLabel": segment_label,
        "careerAlignment": alignment,
        "careerAlignmentLabel": alignment_label,
        "careerWeight": round(career_weight, 3),
        "requiredSkillIds": sorted(required),
        "differentialSkillIds": sorted(differential),
        **geo,
        **inst,
    }


def annotate(job: dict) -> dict:
    job.update(classify(job))
    return job
