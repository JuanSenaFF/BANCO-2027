from __future__ import annotations

import html as htmllib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
AUTO_FILE = ROOT / "data-auto.js"
BASE_FILES = [ROOT / f"data-{i}.js" for i in range(1, 7)]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36 Banco2027JobRadar/1.0"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
TIMEOUT = 20
MAX_NEW = 12

TARGET_COMPANIES = [
    "Itaú", "Bradesco", "Santander", "BTG Pactual", "Nubank", "Banco Inter", "C6 Bank",
    "XP", "Safra", "Mercado Pago", "Stone", "PagBank", "B3", "Núclea", "CERC", "Cielo",
    "Rede", "Getnet", "Dock", "Pismo", "Banco BV", "Daycoval", "Banco ABC Brasil", "Banco PAN",
    "Banco BMG", "Neon", "PicPay", "Creditas", "Will Bank", "Genial Investimentos", "EQI",
    "Rico", "Clear", "Avenue", "Sicoob", "Sicredi", "Sinqia", "Matera", "FitBank",
]

FINANCE_TERMS = [
    "banco", "bancário", "bancaria", "fintech", "pagamentos", "payment", "financeiro", "financial",
    "crédito", "credito", "investimentos", "investimento", "trading", "cobrança", "cobranca", "baas",
    "mercado de capitais", "seguros", "seguradora", "adquirência", "adquirencia", "pix", "cartões", "cartoes",
]
JUNIOR_TERMS = ["júnior", "junior", "jr", "assistente", "associate", "nível i", "nivel i", "trainee"]
TECH_TERMS = [
    "software", "backend", "back-end", "desenvolvedor", "developer", "engenharia", "dados", "data",
    "sistemas", "cloud", "sre", "devops", "automação", "automacao", "python", "java", ".net", "c#",
    "sql", "api", "qa", "qualidade", "segurança", "security", "infraestrutura",
]

SEARCH_QUERIES = [
    'site:br.linkedin.com/jobs/view (junior OR júnior OR assistente) (backend OR software OR dados OR cloud OR sre OR automação) (banco OR fintech OR pagamentos OR investimentos) Brasil',
    'site:gupy.io/jobs (junior OR júnior) (desenvolvedor OR software OR dados OR sistemas OR tecnologia) (banco OR fintech OR crédito OR pagamentos OR investimentos)',
    'site:jobs.lever.co Brazil junior software engineer fintech payments',
    'site:boards.greenhouse.io Brazil junior software engineer fintech payments',
    'site:remotar.com.br/job junior tecnologia banco fintech',
    'site:querovagastech.com.br/vagas junior banco fintech tecnologia',
]
for company in TARGET_COMPANIES[:14]:
    SEARCH_QUERIES.append(f'site:br.linkedin.com/jobs/view "{company}" (junior OR júnior OR jr OR assistente) (software OR backend OR dados OR tecnologia OR cloud)')

TAG_PATTERNS = {
    "Python": r"\bpython\b|\bpyspark\b",
    "SQL": r"\bsql\b|\bplsql\b|\bpl/sql\b|\bpostgresql\b|\bmysql\b|\bsql server\b|\boracle\b",
    "Java": r"\bjava\b|spring boot|java ee|\bjunit\b",
    ".NET/C#": r"\.net|\bc#\b|asp\.net",
    "JavaScript/Node": r"javascript|node\.js|typescript|angular|react",
    "REST/APIs": r"\bapi\b|\bapis\b|\brest\b|soap|openapi|swagger|webhook",
    "Git": r"\bgit\b|github|gitlab",
    "Testes": r"teste|testes|unitário|unitario|tdd|pytest|junit|xunit|phpunit",
    "AWS": r"\baws\b|amazon web services|\bs3\b|lambda|\bsqs\b|\bsns\b|\brds\b|cloudwatch",
    "Azure": r"\bazure\b",
    "GCP": r"\bgcp\b|google cloud|bigquery|vertex ai",
    "Docker": r"docker|podman",
    "Kubernetes": r"kubernetes|\beks\b",
    "CI/CD": r"ci/cd|continuous integration|continuous delivery|jenkins|github actions|azure devops",
    "Microsserviços": r"microsservi|microservice",
    "Mensageria": r"mensageria|rabbitmq|kafka|\bsqs\b|\bsns\b|\bjms\b|fila|eventos",
    "Observabilidade": r"observabilidade|grafana|splunk|dynatrace|new relic|datadog|cloudwatch|kibana|tracing|métricas|metricas",
    "Cloud": r"\bcloud\b|nuvem|\baws\b|\bazure\b|\bgcp\b|\boci\b",
    "Linux": r"\blinux\b|shell script|\bbash\b",
    "Terraform/IaC": r"terraform|infrastructure as code|iac|cloudformation",
    "Dados/BI": r"dados|\bdata\b|power bi|tableau|databricks|spark|pyspark|data lake|redshift|bigquery|etl|elt",
    "Automação": r"automação|automacao|\brpa\b|uipath|n8n|botcity|selenium|scripts?",
    "IA/ML": r"inteligência artificial|inteligencia artificial|\bia\b|machine learning|llm|generative ai|ia generativa|scikit-learn|nlp",
    "Segurança": r"segurança|seguranca|security|owasp|iam|lgpd|oauth|jwt",
    "Crédito/Risco": r"crédito|credito|risco|fraude|pld|fidc|cobrança|cobranca",
    "POO/Design": r"orientação a objetos|orientacao a objetos|design patterns|\bsolid\b|clean code|ddd",
    "Troubleshooting/Produção": r"troubleshooting|incidente|produção|producao|deploy|rollback|sustentação|sustentacao|alta disponibilidade|missão crítica|missao critica",
}

SOURCE_NAME = {
    "linkedin.com": "LinkedIn",
    "gupy.io": "Gupy",
    "jobs.lever.co": "Lever",
    "boards.greenhouse.io": "Greenhouse",
    "remotar.com.br": "Remotar",
    "querovagastech.com.br": "Quero Vagas Tech",
}


def norm(s: str) -> str:
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    for d in SOURCE_NAME:
        if host.endswith(d):
            return d
    return host


def decode_ddg(url: str) -> str:
    try:
        p = urlparse(url)
        if "duckduckgo.com" in p.netloc:
            q = parse_qs(p.query)
            if q.get("uddg"):
                return unquote(q["uddg"][0])
    except Exception:
        pass
    return url


def ddg_search(query: str, limit: int = 6) -> list[str]:
    try:
        r = SESSION.get("https://html.duckduckgo.com/html/", params={"q": query}, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for a in soup.select("a.result__a"):
            href = decode_ddg(a.get("href", ""))
            if href.startswith("http") and href not in out:
                out.append(href)
            if len(out) >= limit:
                break
        return out
    except Exception as exc:
        print(f"[search] falha: {query[:70]}... -> {exc}")
        return []


def find_jobposting(obj):
    if isinstance(obj, dict):
        if obj.get("@type") == "JobPosting":
            return obj
        for v in obj.values():
            found = find_jobposting(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_jobposting(v)
            if found:
                return found
    return None


def fetch_page(url: str) -> tuple[BeautifulSoup | None, dict | None]:
    try:
        r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            return None, None
        soup = BeautifulSoup(r.text, "html.parser")
        posting = None
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or script.get_text())
                posting = find_jobposting(data)
                if posting:
                    break
            except Exception:
                continue
        return soup, posting
    except Exception as exc:
        print(f"[fetch] {url} -> {exc}")
        return None, None


def text_from_posting(posting: dict | None, soup: BeautifulSoup | None) -> str:
    if posting and posting.get("description"):
        return norm(str(posting.get("description")))
    if soup:
        main = soup.find("main") or soup.find("body")
        return norm(main.get_text(" ", strip=True) if main else soup.get_text(" ", strip=True))
    return ""


def company_from(posting: dict | None, soup: BeautifulSoup | None) -> str:
    if posting:
        org = posting.get("hiringOrganization")
        if isinstance(org, dict) and org.get("name"):
            return str(org["name"]).strip()
    if soup:
        for sel in [".topcard__org-name-link", ".topcard__flavor", "meta[property='og:site_name']"]:
            node = soup.select_one(sel)
            if node:
                return (node.get("content") or node.get_text(" ", strip=True)).strip()
    return ""


def title_from(posting: dict | None, soup: BeautifulSoup | None) -> str:
    if posting and posting.get("title"):
        return str(posting["title"]).strip()
    if soup:
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(" ", strip=True)
        if soup.title:
            return soup.title.get_text(" ", strip=True)
    return ""


def extract_bullets(soup: BeautifulSoup | None, posting: dict | None) -> list[str]:
    raw = []
    if soup:
        for li in soup.find_all("li"):
            t = re.sub(r"\s+", " ", li.get_text(" ", strip=True)).strip()
            if 8 <= len(t) <= 260:
                raw.append(t)
    if not raw and posting and posting.get("description"):
        ds = BeautifulSoup(str(posting["description"]), "html.parser")
        raw = [re.sub(r"\s+", " ", li.get_text(" ", strip=True)).strip() for li in ds.find_all("li")]
    benefit_words = ["vale ", "assistência", "assistencia", "seguro de vida", "gympass", "wellhub", "plr", "benefício", "beneficio", "day off", "licença", "licenca"]
    techish = []
    for t in raw:
        lt = t.lower()
        if any(b in lt for b in benefit_words):
            continue
        if any(re.search(p, lt, re.I) for p in TAG_PATTERNS.values()) or any(k in lt for k in ["conhecimento", "experiência", "experiencia", "vivência", "vivencia", "familiaridade", "formação", "formacao"]):
            techish.append(t)
    # preserve order and uniqueness
    seen, out = set(), []
    for t in techish:
        key = norm(t)
        if key not in seen:
            seen.add(key)
            out.append(t)
        if len(out) >= 18:
            break
    return out


def classify_tags(text: str) -> list[str]:
    return [tag for tag, pat in TAG_PATTERNS.items() if re.search(pat, text, re.I)]


def classify_area(title: str, text: str) -> str:
    x = norm(title + " " + text[:1500])
    if "backend" in x or "back-end" in x:
        return "Backend"
    if any(k in x for k in ["dados", "data scientist", "cientista de dados", "analytics", "data engineer"]):
        return "Dados & Analytics"
    if any(k in x for k in ["sre", "cloud", "infraestrutura", "devops"]):
        return "Cloud / SRE"
    if any(k in x for k in ["automação", "automacao", "rpa"]):
        return "Automação & IA"
    if any(k in x for k in ["qualidade", "qa"]):
        return "QA"
    if any(k in x for k in ["sistemas", "sustentação", "sustentacao"]):
        return "Sistemas / Sustentação"
    return "Engenharia de Software"


def classify_stack(tags: list[str], title: str) -> str:
    x = norm(title)
    for stack, aliases in [
        ("Python", ["Python"]), ("Java", ["Java"]), (".NET / C#", [".NET/C#"]),
        ("JavaScript / Node", ["JavaScript/Node"]),
    ]:
        if aliases[0] in tags and (aliases[0].lower().split("/")[0] in x or len(tags) <= 7):
            return stack
    if "Dados/BI" in tags:
        return "Dados / BI"
    if "Cloud" in tags:
        return "Cloud / SRE"
    return "Multistack"


def is_relevant(title: str, company: str, text: str) -> bool:
    merged = norm(" ".join([title, company, text[:4000]]))
    junior = any(t in merged for t in JUNIOR_TERMS)
    tech = any(t in merged for t in TECH_TERMS)
    finance = any(t.lower() in merged for t in TARGET_COMPANIES) or any(t in merged for t in FINANCE_TERMS)
    return junior and tech and finance


def req_tokens(reqs: Iterable[str]) -> set[str]:
    stop = {"conhecimento", "experiência", "experiencia", "vivência", "vivencia", "básico", "basico", "intermediário", "intermediario", "avançado", "avancado", "com", "em", "de", "do", "da", "e", "ou", "para"}
    toks = set()
    for r in reqs:
        toks.update(w for w in re.findall(r"[a-z0-9+#.]+", norm(r)) if len(w) > 2 and w not in stop)
    return toks


def similarity(a: list[str], b: list[str]) -> float:
    A, B = req_tokens(a), req_tokens(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def parse_js_array(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    m = re.search(r"jobs\.push\(\.\.\.(\[.*\])\);", text, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except Exception:
        return []


def render_auto(jobs: list[dict], domains: dict[str, str] | None = None) -> str:
    lines = []
    if domains:
        lines.append("window.BANCO2027.domains=Object.assign(window.BANCO2027.domains," + json.dumps(domains, ensure_ascii=False, separators=(",", ":")) + ");")
    lines.append("window.BANCO2027.jobs.push(..." + json.dumps(jobs, ensure_ascii=False, separators=(",", ":")) + ");")
    return "\n".join(lines) + "\n"


def infer_domain(posting: dict | None, company: str) -> str | None:
    if posting:
        org = posting.get("hiringOrganization")
        if isinstance(org, dict):
            same_as = org.get("sameAs") or org.get("url")
            if isinstance(same_as, str) and same_as.startswith("http"):
                host = urlparse(same_as).netloc.lower().replace("www.", "")
                if host and not any(x in host for x in ["linkedin.com", "gupy.io"]):
                    return host
    return None


def main() -> int:
    existing = []
    for p in BASE_FILES:
        existing.extend(parse_js_array(p))
    auto_existing = parse_js_array(AUTO_FILE)
    existing.extend(auto_existing)
    max_id = max([int(j.get("id", 0)) for j in existing] + [0])
    known_urls = {j.get("source", "") for j in existing if j.get("source")}

    candidate_urls = []
    for i, query in enumerate(SEARCH_QUERIES):
        for url in ddg_search(query, 5):
            if url not in candidate_urls:
                candidate_urls.append(url)
        time.sleep(0.35)
        if i and i % 10 == 0:
            time.sleep(1.0)

    print(f"[info] URLs candidatas: {len(candidate_urls)}")
    new_jobs = []
    new_domains = {}
    collected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    for url in candidate_urls:
        if len(new_jobs) >= MAX_NEW:
            break
        if url in known_urls:
            continue
        src_domain = domain_of(url)
        if not any(src_domain.endswith(d) for d in SOURCE_NAME):
            continue
        soup, posting = fetch_page(url)
        if not soup and not posting:
            continue
        title = title_from(posting, soup)
        company = company_from(posting, soup)
        text = text_from_posting(posting, soup)
        if not title or not is_relevant(title, company, text):
            continue
        requirements = extract_bullets(soup, posting)
        if len(requirements) < 2:
            continue

        # Deduplicação principal por exigências; URL idêntica já foi eliminada acima.
        if any(similarity(requirements, j.get("requirements", [])) >= 0.90 for j in existing + new_jobs):
            continue

        tags = classify_tags(" ".join([title, text, " ".join(requirements)]))
        if len(tags) < 2:
            continue
        max_id += 1
        area = classify_area(title, text)
        source_label = SOURCE_NAME.get(src_domain, src_domain)
        job = {
            "id": max_id,
            "company": company or "Empresa não identificada",
            "role": title,
            "level": "Júnior / entrada",
            "status": "Ativa",
            "statusRaw": f"Coleta automática em {collected_at[:10]} — {source_label}",
            "area": area,
            "stack": classify_stack(tags, title),
            "fit": "AUTO — NOVA",
            "tags": tags,
            "requirements": requirements[:14],
            "differentials": [],
            "reason": f"Coletada automaticamente em {source_label}. Revise o anúncio original antes de se candidatar; a compatibilidade é calculada pelas exigências extraídas.",
            "source": url,
            "collectedAt": collected_at,
            "auto": True,
        }
        new_jobs.append(job)
        dom = infer_domain(posting, company)
        if company and dom:
            new_domains[company] = dom
        print(f"[novo] {company} — {title}")
        time.sleep(0.25)

    if not new_jobs:
        print("[info] Nenhuma vaga nova distinta por exigências nesta execução.")
        return 0

    all_auto = auto_existing + new_jobs
    AUTO_FILE.write_text(render_auto(all_auto, new_domains or None), encoding="utf-8")
    print(f"[ok] {len(new_jobs)} novas vagas adicionadas. Total auto: {len(all_auto)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
