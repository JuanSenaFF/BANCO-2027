from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

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
EXCLUDED = [
    ("ita", "analista de projetos", "tecnologia"),
    ("ita", "analista de projetos", "tenologia"),
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
    return bool(cc) and any(cc == compact(x) or (len(cc) >= 5 and cc in compact(x)) or (len(compact(x)) >= 5 and compact(x) in cc) for x in APPROVED_COMPANIES)


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
    out = set()
    for r in reqs:
        out.update(w for w in re.findall(r"[a-z0-9+#.]+", ascii_norm(r)) if len(w) > 2 and w not in stop)
    return out


def req_similarity(a: list[str], b: list[str]) -> float:
    A, B = tokens(a), tokens(b)
    return len(A & B) / len(A | B) if A and B else 0.0


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
    from quality import senior_conflict
    if senior_conflict(role, " ".join(reqs)):
        return False, "senioridade fora do recorte"
    if len(reqs) < 3:
        return False, "requisitos insuficientes"
    if not company_approved(company) and not (company_contextual(company) and finance_context(job)):
        return False, "fora do ecossistema financeiro validado"
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
        ok, why = valid(job)
        if not ok:
            removed.append((job.get("company"), job.get("role"), why))
            continue
        cu = canonical_url(job.get("source", ""))
        if cu and cu in seen_urls:
            removed.append((job.get("company"), job.get("role"), "URL/ID já existente"))
            continue
        if any(req_similarity(job.get("requirements", []), x.get("requirements", [])) >= 0.90 for x in reference):
            removed.append((job.get("company"), job.get("role"), "exigências essencialmente idênticas"))
            continue
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
    print(f"[validate] mantidas {len(kept)} vagas automáticas; removidas {len(removed)}")


if __name__ == "__main__":
    main()
