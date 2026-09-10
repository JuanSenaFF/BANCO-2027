from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from rules import DUPLICATE_SIMILARITY, REVIEW_SIMILARITY
from official_sources import prefer_source, same_posting, source_metadata

ROOT = Path(__file__).resolve().parents[1]
AUTO_FILE = ROOT / "data-auto.js"
BASE_FILES = [ROOT / f"data-{i}.js" for i in range(1, 7)]

APPROVED_COMPANIES = [
    "Itaú", "Itaú Unibanco", "Bradesco", "Santander", "Santander Brasil", "BTG Pactual", "Nubank",
    "Banco Inter", "Inter", "C6 Bank", "XP", "XP Inc.", "Safra", "Mercado Pago", "Stone", "PagBank",
    "B3", "Núclea", "CERC", "Cielo", "Rede", "Getnet", "Dock", "Pismo", "Banco BV", "Daycoval",
    "Banco Daycoval", "Banco ABC Brasil", "Banco PAN", "Banco BMG", "Neon", "PicPay", "Creditas",
    "Will Bank", "Genial Investimentos", "EQI", "EQI Investimentos", "Rico", "Clear", "Avenue",
    "Sicoob", "Sicredi", "Sinqia", "Matera", "FitBank", "ANBIMA", "BMP", "Grupo Bancorbrás",
    "Via Certa Promotora", "Nava | Tech for Business", "Nava",
    # Ecossistema financeiro adicional: não é prioridade de busca, mas pode entrar quando aparecer nas fontes.
    "Agibank", "Banco Carrefour", "Banco Mercantil", "Banco Sofisa", "Banco Pine", "Banco Rendimento",
    "Banco Bari", "Digio", "Banco Digio", "Banco Modal", "EBANX", "CloudWalk", "InfinitePay", "Asaas",
    "Celcoin", "QI Tech", "Stark Bank", "Conta Simples", "RecargaPay", "Zoop", "Vindi", "Fiserv",
]

CONTEXT_COMPANIES = ["Tata Consultancy Services", "TCS", "FCamara", "Qaracter", "Stefanini", "Capgemini", "Accenture"]
STRONG_FINANCE = [
    "segmento bancário", "segmento bancario", "setor bancário", "setor bancario", "mercado financeiro",
    "instituição financeira", "instituicao financeira", "serviços financeiros", "servicos financeiros",
    "banco de investimento", "meios de pagamento", "infraestrutura financeira", "banking as a service",
    "risco de crédito", "risco de credito", "políticas de crédito", "politicas de credito", "open finance",
    "mercado de capitais", "investment banking", "financial services", "banking industry", "credit risk",
]

# Vagas originalmente fornecidas pelo usuário: nunca devem reaparecer como “novas”.
# A vaga de Analista de Projetos de Tecnologia Júnior do Itaú deixou de ser excluída: ela deve ser
# tratada pelas mesmas regras de requisitos/deduplicação das demais vagas.
EXCLUDED = [
    ("btg", "backend", "recovery credit"),
    ("btg", "software engineer junior", "sustentacao"),
    ("bradesco", "analista suporte ti", "jr"),
    ("", "desenvolvedor backend", "it bsm"),
    ("btg", "desenvolvedor backend", "renda fixa"),
    ("xp", "engenheiro", "dados junior"),
    ("", "analista de negocios junior", "sistemas"),
]

SENIOR = ["senior", "pleno", "especialista", "specialist", "lead", "principal", "staff"]


def ascii_norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().replace("—", " ").replace("–", " ").replace("-", " ").replace("/", " ")
    return re.sub(r"[^a-z0-9+#.]+", " ", s).strip()


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", ascii_norm(s))


def company_approved(c: str) -> bool:
    cc = compact(c)
    if not cc:
        return False
    approved = {compact(x) for x in APPROVED_COMPANIES}
    if cc in approved:
        return True
    # Correspondência parcial só para nomes longos; evita casos como Clear x ClearSale.
    return any(len(cc) >= 8 and len(x) >= 8 and (cc in x or x in cc) for x in approved)


def company_contextual(c: str) -> bool:
    cc = compact(c)
    return bool(cc) and any(compact(x) in cc or cc in compact(x) for x in CONTEXT_COMPANIES)


def finance_context(job: dict) -> bool:
    text = ascii_norm(" ".join(job.get("requirements", []) + job.get("differentials", []) + [job.get("reason", "")]))
    return any(ascii_norm(p) in text for p in STRONG_FINANCE)


def original_excluded(job: dict) -> bool:
    c = ascii_norm(job.get("company", ""))
    t = ascii_norm(job.get("role", ""))
    for company_frag, a, b in EXCLUDED:
        if company_frag and company_frag not in c:
            continue
        if ascii_norm(a) in t and ascii_norm(b) in t:
            return True
    return False


def canonical_url(url: str) -> str:
    if "linkedin.com/jobs/view" in url:
        ids = re.findall(r"(\d{7,})", url)
        if ids:
            return "linkedin:" + ids[-1]
    if ".gupy.io/" in url:
        m = re.search(r"/jobs?/(\d+)", url)
        if m:
            return urlparse(url).netloc.lower() + ":" + m.group(1)
    p = urlparse(url)
    return (p.netloc.lower().replace("www.", "") + p.path.rstrip("/")).lower()


def tokens(reqs: list[str]) -> set[str]:
    stop = {"conhecimento", "experiencia", "vivencia", "basico", "intermediario", "avancado", "para", "com", "uma", "das", "dos", "que", "atuar", "desenvolver"}
    aliases = {
        "restful": "rest",
        "restapi": "api",
        "restapis": "api",
        "postgres": "postgresql",
        "postgresql": "postgresql",
        "javascript": "javascript",
        "nodejs": "node",
        "node": "node",
        "amazonwebservices": "aws",
        "googlecloud": "gcp",
        "microsoftazure": "azure",
        "microservices": "microservice",
        "microsservicos": "microservice",
    }
    out = set()
    for r in reqs:
        out.update(
            aliases.get(w, w)
            for w in re.findall(r"[a-z0-9+#.]+", ascii_norm(r))
            if len(w) > 2 and w not in stop
        )
    return out


def req_similarity(a: list[str], b: list[str]) -> float:
    A, B = tokens(a), tokens(b)
    return len(A & B) / len(A | B) if A and B else 0.0


def similarity_band(a: list[str], b: list[str]) -> str | None:
    score = req_similarity(a, b)
    if score >= DUPLICATE_SIMILARITY:
        return "duplicate"
    if score >= REVIEW_SIMILARITY:
        return "review"
    return None


def parse_jobs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    m = re.search(r"jobs\.push\(\.\.\.(\[.*\])\);", text, re.S)
    return json.loads(m.group(1)) if m else []


def parse_domains(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    m = re.search(r"Object\.assign\(window\.BANCO2027\.domains,(\{.*?\})\);", text, re.S)
    return json.loads(m.group(1)) if m else {}


def render(jobs: list[dict], domains: dict) -> str:
    return (
        "window.BANCO2027.domains=Object.assign(window.BANCO2027.domains," +
        json.dumps(domains, ensure_ascii=False, separators=(",", ":")) + ");\n" +
        "window.BANCO2027.jobs.push(..." + json.dumps(jobs, ensure_ascii=False, separators=(",", ":")) + ");\n"
    )


def valid(job: dict) -> tuple[bool, str]:
    company = str(job.get("company", "")).strip()
    role = ascii_norm(job.get("role", ""))
    reqs = job.get("requirements", [])
    if not company or company.lower().startswith("empresa nao identificada"):
        return False, "empresa ausente"
    if original_excluded(job):
        return False, "vaga original do usuário"
    from quality import senior_conflict, requirements_quality_conflict
    if senior_conflict(role, " ".join(reqs)):
        return False, "senioridade fora do recorte"
    if len(reqs) < 3:
        return False, "requisitos insuficientes"
    if requirements_quality_conflict(job.get("role", ""), reqs):
        return False, "requisitos contaminados ou pouco informativos"
    # Reapply the collector's role filter to the persistent automatic catalog.
    # This removes records admitted by an older, more permissive version.
    from update_vagas import is_relevant
    relevance_text = " ".join(reqs + job.get("differentials", []) + [job.get("reason", "")])
    if not is_relevant(job.get("role", ""), company, relevance_text):
        return False, "cargo fora do recorte técnico"
    # Empresas prioritárias/adicionais passam pelo nome. Empresas novas só passam quando os dados
    # extraídos ainda preservam contexto financeiro explícito; consultorias também exigem esse contexto.
    if not company_approved(company) and not finance_context(job):
        return False, "fora do ecossistema financeiro validado"
    if company_contextual(company) and not finance_context(job):
        return False, "consultoria sem contexto financeiro explícito"
    return True, "ok"


def main() -> None:
    base = []
    for p in BASE_FILES:
        base.extend(parse_jobs(p))
    auto = parse_jobs(AUTO_FILE)
    domains = parse_domains(AUTO_FILE)

    kept = []
    seen_urls = {canonical_url(j.get("source", "")) for j in base if j.get("source")}
    reference = list(base)
    removed = []

    for job in auto:
        job.pop("reviewRequired", None)
        job.pop("reviewReason", None)
        ok, why = valid(job)
        if not ok:
            removed.append((job.get("company"), job.get("role"), why))
            continue
        cu = canonical_url(job.get("source", ""))
        if cu and cu in seen_urls:
            removed.append((job.get("company"), job.get("role"), "URL/ID já existente"))
            continue
        duplicate = next(
            (
                x
                for x in reference
                if req_similarity(job.get("requirements", []), x.get("requirements", []))
                >= DUPLICATE_SIMILARITY
                or (
                    source_metadata(job.get("source", ""))["priority"]
                    != source_metadata(x.get("source", ""))["priority"]
                    and same_posting(job, x, req_similarity)
                )
            ),
            None,
        )
        if duplicate and not prefer_source(job, duplicate):
            removed.append((job.get("company"), job.get("role"), "exigências essencialmente idênticas"))
            continue
        if duplicate:
            job["supersedesSource"] = duplicate.get("source")
        meta = source_metadata(job.get("source", ""), structured=bool(job.get("sourceStructured")))
        job.setdefault("sourceName", meta["name"])
        job.setdefault("sourceProvider", meta["provider"])
        job.setdefault("sourceOfficial", meta["official"])
        job.setdefault("sourcePriority", meta["priority"])
        review = next(
            (
                x
                for x in reference
                if similarity_band(job.get("requirements", []), x.get("requirements", [])) == "review"
            ),
            None,
        )
        if review:
            job["reviewRequired"] = True
            job["reviewReason"] = (
                "Exigências próximas de outra vaga; revisão humana recomendada "
                f"({review.get('company', 'empresa')} — {review.get('role', 'cargo')})."
            )
        kept.append(job)
        reference.append(job)
        if cu:
            seen_urls.add(cu)

    # Preserve IDs so saved favorites and applications do not point to another job.
    used_ids = {int(j["id"]) for j in base + kept if j.get("id")}
    next_id = max(used_ids or {47}) + 1
    for j in kept:
        if not j.get("id"):
            j["id"] = next_id
            next_id += 1

    used_companies = {j.get("company") for j in kept}
    domains = {k: v for k, v in domains.items() if k in used_companies or company_approved(k)}
    AUTO_FILE.write_text(render(kept, domains), encoding="utf-8")

    for company, role, why in removed:
        print(f"[remove] {company} — {role}: {why}")
    report_path = ROOT / "collection-report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        report.update({
            "validated": len(kept),
            "rejected": len(removed),
            "reviewRequired": sum(bool(j.get("reviewRequired")) for j in kept),
            "rejectionReasons": {
                reason: sum(1 for _, _, why in removed if why == reason)
                for reason in sorted({why for _, _, why in removed})
            },
        })
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    print(f"[validate] mantidas {len(kept)} vagas automáticas; removidas {len(removed)}")


if __name__ == "__main__":
    main()
