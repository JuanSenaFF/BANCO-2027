from __future__ import annotations

import html as htmllib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
AUTO_FILE = ROOT / "data-auto.js"
BASE_FILES = [ROOT / f"data-{i}.js" for i in range(1, 7)]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36 Banco2027JobRadar/1.2"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
TIMEOUT = 20
MAX_NEW = 10

TARGET_COMPANIES = [
    "Itaú", "Itaú Unibanco", "Bradesco", "Santander", "Santander Brasil", "BTG Pactual", "Nubank",
    "Banco Inter", "Inter", "C6 Bank", "XP", "XP Inc.", "Safra", "Mercado Pago", "Stone", "PagBank",
    "B3", "Núclea", "CERC", "Cielo", "Rede", "Getnet", "Dock", "Pismo", "Banco BV", "Daycoval",
    "Banco Daycoval", "Banco ABC Brasil", "Banco PAN", "Banco BMG", "Neon", "PicPay", "Creditas",
    "Will Bank", "Genial Investimentos", "EQI", "EQI Investimentos", "Rico", "Clear", "Avenue",
    "Sicoob", "Sicredi", "Sinqia", "Matera", "FitBank",
    # empresas do ecossistema já validadas pela pesquisa
    "ANBIMA", "BMP", "Grupo Bancorbrás", "Via Certa Promotora", "Nava | Tech for Business", "Nava",
]

# Consultorias/techs só entram quando o anúncio deixa explícito que o projeto é bancário/financeiro.
CONTEXT_ALLOWED_COMPANIES = ["Tata Consultancy Services", "FCamara", "Qaracter", "Stefanini", "Capgemini", "Accenture"]

STRONG_FINANCE_PHRASES = [
    "segmento bancário", "segmento bancario", "setor bancário", "setor bancario", "mercado financeiro",
    "instituição financeira", "instituicao financeira", "instituições financeiras", "instituicoes financeiras",
    "banco de investimento", "bancos de investimento", "serviços financeiros", "servicos financeiros",
    "meios de pagamento", "infraestrutura financeira", "banking as a service", "banking-as-a-service",
    "produtos bancários", "produtos bancarios", "risco de crédito", "risco de credito", "políticas de crédito",
    "politicas de credito", "prevenção a fraudes", "prevencao a fraudes", "open finance", "mercado de capitais",
    "renda fixa", "investment banking", "financial services", "banking industry", "credit risk", "payments industry",
]

JUNIOR_TERMS = ["júnior", "junior", " jr", "jr ", "assistente", "associate", "nível i", "nivel i", "trainee"]
SENIOR_TITLE_TERMS = ["sênior", "senior", "pleno", "specialist", "especialista", "lead", "principal", "staff"]
TECH_TERMS = [
    "software", "backend", "back-end", "desenvolvedor", "developer", "engenharia", "dados", "data",
    "sistemas", "cloud", "sre", "devops", "automação", "automacao", "python", "java", ".net", "c#",
    "sql", "api", "qa", "qualidade", "segurança", "security", "infraestrutura",
]

# As 8 vagas originalmente fornecidas pelo usuário não podem voltar como “novas”.
EXCLUDED_TITLE_FRAGMENTS = [
    "analista de projetos de tecnologia júnior",
    "backend jr recovery credit",
    "software engineer junior it sustentação",
    "analista suporte ti jr",
    "desenvolvedor backend júnior pleno it bsm",
    "desenvolvedor backend junior pleno it bsm",
    "desenvolvedor backend junior pleno renda fixa",
    "desenvolvedor backend júnior pleno renda fixa",
    "engenheiro a de dados júnior",
    "engenheiro de dados júnior",
    "analista de negócios júnior sistemas",
    "analista de negocios junior sistemas",
]

LINKEDIN_KEYWORDS = [
    "backend junior banco", "software engineer junior fintech", "desenvolvedor junior mercado financeiro",
    "analista sistemas junior banco", "dados junior banco", "data engineer junior fintech",
    "automacao python junior banco", "cloud sre junior fintech", "java junior banco", ".net junior banco",
    "payments software junior", "credit risk junior python sql",
]

# Buscas adicionais em empresas prioritárias. Uma consulta por empresa mantém o custo do workflow controlado.
LINKEDIN_PRIORITY_COMPANIES = [
    "Itaú", "Bradesco", "Santander", "BTG Pactual", "Nubank", "Banco Inter", "C6 Bank", "XP",
    "Mercado Pago", "Stone", "PagBank", "B3", "Cielo", "Pismo", "PicPay", "Sicredi",
]

GUPY_CAREERS = [
    "https://anbima.gupy.io/",
    "https://bancorbras.gupy.io/",
    "https://acertapromotora.gupy.io/",
    "https://bancobmg.gupy.io/",
    "https://nuclea.gupy.io/",
    "https://sicredi.gupy.io/",
    "https://sicoob.gupy.io/",
    "https://bancobv.gupy.io/",
    "https://picpay.gupy.io/",
]

LEVER_BOARDS = ["https://jobs.lever.co/pismo"]
SITEMAPS = ["https://remotar.com.br/sitemap.xml", "https://querovagastech.com.br/sitemap.xml"]

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
    "linkedin.com": "LinkedIn", "gupy.io": "Gupy", "jobs.lever.co": "Lever",
    "boards.greenhouse.io": "Greenhouse", "remotar.com.br": "Remotar",
    "querovagastech.com.br": "Quero Vagas Tech",
}

METADATA_PREFIXES = [
    "nível de experiência", "nivel de experiencia", "função ", "funcao ", "setores ", "tipo de emprego",
    "competências ", "competencias ", "indicações", "indicacoes",
]


def norm(s: str) -> str:
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip().lower()


def canon_company(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", norm(s))


def approved_company(company: str) -> bool:
    c = canon_company(company)
    return any(c == canon_company(t) or (len(c) >= 5 and c in canon_company(t)) or (len(canon_company(t)) >= 5 and canon_company(t) in c) for t in TARGET_COMPANIES)


def contextual_company(company: str) -> bool:
    c = canon_company(company)
    return any(c == canon_company(t) or canon_company(t) in c for t in CONTEXT_ALLOWED_COMPANIES)


def strong_finance_context(text: str) -> bool:
    x = norm(text)
    return any(p in x for p in STRONG_FINANCE_PHRASES)


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "").replace("br.", "", 1)
    for d in SOURCE_NAME:
        if host.endswith(d):
            return d
    return host


def canonical_source(url: str) -> str:
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


def excluded_title(title: str) -> bool:
    t = norm(title).replace("/", " ").replace("–", " ").replace("—", " ").replace("-", " ")
    t = re.sub(r"\s+", " ", t)
    return any(re.sub(r"\s+", " ", f.replace("/", " ").replace("-", " ")) in t for f in EXCLUDED_TITLE_FRAGMENTS)


def safe_get(url: str, **kwargs):
    try:
        r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True, **kwargs)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(1.2)
            r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True, **kwargs)
        return r
    except Exception as exc:
        print(f"[fetch] {url} -> {exc}")
        return None


def linkedin_query_urls(keyword: str, starts=(0,)) -> list[str]:
    out = []
    endpoint = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for start in starts:
        params = {
            "keywords": keyword, "geoId": "106057199", "f_TPR": "r2592000",
            "f_E": "2", "sortBy": "DD", "start": str(start),
        }
        r = safe_get(endpoint, params=params)
        if not r or r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select("li") or [soup]:
            urn = card.get("data-entity-urn", "") if hasattr(card, "get") else ""
            m = re.search(r"jobPosting:(\d+)", urn)
            if not m:
                a = card.select_one("a[href*='/jobs/view/']") if hasattr(card, "select_one") else None
                href = a.get("href", "") if a else ""
                ids = re.findall(r"(\d{7,})", href)
                m = re.match(r"(.*)", ids[-1]) if ids else None
            if m:
                jid = m.group(1)
                u = f"https://www.linkedin.com/jobs/view/{jid}"
                if u not in out:
                    out.append(u)
        time.sleep(0.15)
    return out


def linkedin_urls() -> list[str]:
    out = []
    for kw in LINKEDIN_KEYWORDS:
        for u in linkedin_query_urls(kw, (0, 10)):
            if u not in out:
                out.append(u)
    for company in LINKEDIN_PRIORITY_COMPANIES:
        for u in linkedin_query_urls(f'"{company}" junior tecnologia', (0,)):
            if u not in out:
                out.append(u)
    print(f"[source] LinkedIn: {len(out)} URLs")
    return out


def page_links(base: str, patterns: list[str], limit: int = 60) -> list[str]:
    r = safe_get(base)
    if not r or r.status_code >= 400:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        u = urljoin(base, a["href"])
        if any(re.search(p, u, re.I) for p in patterns) and u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    if len(out) < 5:
        for m in re.finditer(r"https?://[^\"'<> ]+", r.text):
            u = htmllib.unescape(m.group(0))
            if any(re.search(p, u, re.I) for p in patterns) and u not in out:
                out.append(u)
                if len(out) >= limit:
                    break
    return out


def gupy_urls() -> list[str]:
    out = []
    for base in GUPY_CAREERS:
        urls = page_links(base, [r"\.gupy\.io/(?:job|jobs)/"])
        if not urls:
            r = safe_get(base)
            if r and r.status_code < 400:
                host = urlparse(base).netloc
                for m in re.finditer(r"/jobs/(\d+)", r.text):
                    u = f"https://{host}/jobs/{m.group(1)}?jobBoardSource=gupy_public_page"
                    if u not in urls:
                        urls.append(u)
        for u in urls[:50]:
            if u not in out:
                out.append(u)
        time.sleep(0.1)
    print(f"[source] Gupy: {len(out)} URLs")
    return out


def lever_urls() -> list[str]:
    out = []
    for board in LEVER_BOARDS:
        for u in page_links(board, [r"jobs\.lever\.co/[^/]+/[a-z0-9-]+$"], 100):
            if u not in out:
                out.append(u)
    print(f"[source] Lever: {len(out)} URLs")
    return out


def sitemap_job_urls(url: str, max_urls: int = 60) -> list[str]:
    r = safe_get(url)
    if not r or r.status_code >= 400:
        return []
    try:
        root = ET.fromstring(r.text)
    except Exception:
        return []
    locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
    if locs and all(x.endswith(".xml") or "sitemap" in x for x in locs[: min(5, len(locs))]):
        nested = []
        for child in locs[-4:]:
            nested.extend(sitemap_job_urls(child, max_urls=max_urls))
            if len(nested) >= max_urls:
                break
        return nested[:max_urls]
    return [u for u in locs if re.search(r"/(?:job|vagas?)/", u, re.I)][-max_urls:]


def other_source_urls() -> list[str]:
    out = []
    for sm in SITEMAPS:
        for u in sitemap_job_urls(sm, 50):
            if u not in out:
                out.append(u)
    print(f"[source] Remotar/Quero Vagas Tech: {len(out)} URLs")
    return out


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


def linkedin_job_id(url: str) -> str | None:
    ids = re.findall(r"(\d{7,})", url)
    return ids[-1] if ids else None


def fetch_page(url: str) -> tuple[BeautifulSoup | None, dict | None]:
    fetch_url = url
    if "linkedin.com/jobs/view/" in url:
        jid = linkedin_job_id(url)
        if jid:
            fetch_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}"
    r = safe_get(fetch_url)
    if not r or r.status_code >= 400:
        return None, None
    soup = BeautifulSoup(r.text, "html.parser")
    posting = None
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            posting = find_jobposting(json.loads(script.string or script.get_text()))
            if posting:
                break
        except Exception:
            continue
    return soup, posting


def text_from_posting(posting: dict | None, soup: BeautifulSoup | None) -> str:
    if posting and posting.get("description"):
        return norm(str(posting.get("description")))
    if soup:
        desc = soup.select_one(".show-more-less-html__markup, .description__text, [class*='description']")
        return norm((desc or soup).get_text(" ", strip=True))
    return ""


def company_from(posting: dict | None, soup: BeautifulSoup | None) -> str:
    if posting:
        org = posting.get("hiringOrganization")
        if isinstance(org, dict) and org.get("name"):
            return str(org["name"]).strip()
    if soup:
        for sel in [".topcard__org-name-link", ".topcard__flavor", "[class*='company-name']"]:
            node = soup.select_one(sel)
            if node:
                val = node.get_text(" ", strip=True).strip()
                if val:
                    return val
    return ""


def title_from(posting: dict | None, soup: BeautifulSoup | None) -> str:
    if posting and posting.get("title"):
        return str(posting["title"]).strip()
    if soup:
        for sel in ["h1", ".top-card-layout__title", "[class*='job-title']"]:
            node = soup.select_one(sel)
            if node and node.get_text(" ", strip=True):
                return node.get_text(" ", strip=True)
    return ""


def extract_bullets(soup: BeautifulSoup | None, posting: dict | None) -> list[str]:
    raw = []
    if soup:
        for li in soup.find_all("li"):
            t = re.sub(r"\s+", " ", li.get_text(" ", strip=True)).strip()
            if 8 <= len(t) <= 280:
                raw.append(t)
    if not raw and posting and posting.get("description"):
        ds = BeautifulSoup(str(posting["description"]), "html.parser")
        raw = [re.sub(r"\s+", " ", li.get_text(" ", strip=True)).strip() for li in ds.find_all("li")]

    benefit_words = ["vale ", "assistência", "assistencia", "seguro de vida", "gympass", "wellhub", "plr", "benefício", "beneficio", "day off", "licença", "licenca"]
    out, seen = [], set()
    for t in raw:
        lt = norm(t)
        if any(lt.startswith(p) for p in METADATA_PREFIXES) or any(b in lt for b in benefit_words):
            continue
        tech_or_req = any(re.search(p, lt, re.I) for p in TAG_PATTERNS.values()) or any(k in lt for k in [
            "conhecimento", "experiência", "experiencia", "vivência", "vivencia", "familiaridade", "formação", "formacao",
            "desenvolver", "atuar", "manutenção", "manutencao", "implementar", "construir", "criar", "integrar",
        ])
        if not tech_or_req:
            continue
        if lt not in seen:
            seen.add(lt)
            out.append(t)
        if len(out) >= 18:
            break
    return out


def classify_tags(text: str) -> list[str]:
    return [tag for tag, pat in TAG_PATTERNS.items() if re.search(pat, text, re.I)]


def classify_area(title: str, text: str) -> str:
    x = norm(title + " " + text[:1600])
    if "backend" in x or "back-end" in x:
        return "Backend"
    if any(k in x for k in ["dados", "data scientist", "cientista de dados", "analytics", "data engineer"]):
        return "Dados & Analytics"
    if any(k in x for k in ["sre", "cloud", "infraestrutura", "devops"]):
        return "Cloud / SRE"
    if any(k in x for k in ["automação", "automacao", "rpa"]):
        return "Automação & IA"
    if any(k in x for k in ["qualidade", " qa", "testador"]):
        return "QA"
    if any(k in x for k in ["sistemas", "sustentação", "sustentacao"]):
        return "Sistemas / Sustentação"
    return "Engenharia de Software"


def classify_stack(tags: list[str], title: str) -> str:
    x = norm(title)
    mapping = [("Python", "Python", ["python"]), ("Java", "Java", ["java", "spring"]), (".NET / C#", ".NET/C#", [".net", "c#"]), ("JavaScript / Node", "JavaScript/Node", ["node", "javascript", "typescript"])]
    for stack, tag, words in mapping:
        if tag in tags and any(w in x for w in words):
            return stack
    for stack, tag in [("Python", "Python"), ("Java", "Java"), (".NET / C#", ".NET/C#")]:
        if tag in tags:
            return stack
    if "Dados/BI" in tags:
        return "Dados / BI"
    if "Cloud" in tags:
        return "Cloud / SRE"
    return "Multistack"


def is_relevant(title: str, company: str, text: str) -> bool:
    title_n = norm(title)
    merged = norm(" ".join([title, company, text[:6000]]))
    if excluded_title(title):
        return False
    if any(t in title_n for t in SENIOR_TITLE_TERMS):
        return False
    # Algumas páginas do LinkedIn exibem senioridade contraditória ao título.
    if any(x in merged for x in ["nível de experiência pleno-sênior", "nivel de experiencia pleno-senior", "nível de experiência sênior", "nivel de experiencia senior"]):
        return False
    junior = any(t in title_n for t in JUNIOR_TERMS) or any(t in merged[:1200] for t in JUNIOR_TERMS)
    tech = any(t in merged for t in TECH_TERMS)
    if not (junior and tech):
        return False
    if approved_company(company):
        return True
    # Consultorias e novas empresas só entram com contexto financeiro forte explícito no anúncio.
    return strong_finance_context(merged) and (contextual_company(company) or len([p for p in STRONG_FINANCE_PHRASES if p in merged]) >= 2)


def req_tokens(reqs: Iterable[str]) -> set[str]:
    stop = {"conhecimento", "experiência", "experiencia", "vivência", "vivencia", "básico", "basico", "intermediário", "intermediario", "avançado", "avancado", "com", "em", "de", "do", "da", "e", "ou", "para", "atuar", "desenvolver"}
    toks = set()
    for r in reqs:
        toks.update(w for w in re.findall(r"[a-z0-9+#.]+", norm(r)) if len(w) > 2 and w not in stop)
    return toks


def similarity(a: list[str], b: list[str]) -> float:
    A, B = req_tokens(a), req_tokens(b)
    return len(A & B) / len(A | B) if A and B else 0.0


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


def existing_auto_domains() -> dict[str, str]:
    if not AUTO_FILE.exists():
        return {}
    m = re.search(r"Object\.assign\(window\.BANCO2027\.domains,(\{.*?\})\);", AUTO_FILE.read_text(encoding="utf-8"), re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:
        return {}


def render_auto(jobs: list[dict], domains: dict[str, str] | None = None) -> str:
    lines = []
    if domains:
        lines.append("window.BANCO2027.domains=Object.assign(window.BANCO2027.domains," + json.dumps(domains, ensure_ascii=False, separators=(",", ":")) + ");")
    lines.append("window.BANCO2027.jobs.push(..." + json.dumps(jobs, ensure_ascii=False, separators=(",", ":")) + ");")
    return "\n".join(lines) + "\n"


def infer_domain(posting: dict | None) -> str | None:
    if posting:
        org = posting.get("hiringOrganization")
        if isinstance(org, dict):
            same_as = org.get("sameAs") or org.get("url")
            if isinstance(same_as, str) and same_as.startswith("http"):
                host = urlparse(same_as).netloc.lower().replace("www.", "")
                if host and not any(x in host for x in ["linkedin.com", "gupy.io"]):
                    return host
    return None


def discover_urls() -> list[str]:
    out = []
    for bucket in [linkedin_urls(), gupy_urls(), lever_urls(), other_source_urls()]:
        for u in bucket:
            if u not in out:
                out.append(u)
    print(f"[info] URLs candidatas totais: {len(out)}")
    return out


def main() -> int:
    existing = []
    for p in BASE_FILES:
        existing.extend(parse_js_array(p))
    auto_existing = parse_js_array(AUTO_FILE)
    existing.extend(auto_existing)
    max_id = max([int(j.get("id", 0)) for j in existing] + [0])
    known_sources = {canonical_source(j.get("source", "")) for j in existing if j.get("source")}

    candidate_urls = discover_urls()
    new_jobs = []
    domains = existing_auto_domains()
    collected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    for url in candidate_urls:
        if len(new_jobs) >= MAX_NEW:
            break
        csource = canonical_source(url)
        if csource in known_sources:
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
        if len(requirements) < 3:
            continue
        # Deduplicação principal solicitada pelo usuário: exigências essencialmente idênticas.
        if any(similarity(requirements, j.get("requirements", [])) >= 0.90 for j in existing + new_jobs):
            continue
        tags = classify_tags(" ".join([title, text, " ".join(requirements)]))
        if len(tags) < 2:
            continue

        max_id += 1
        source_label = SOURCE_NAME.get(src_domain, src_domain)
        job = {
            "id": max_id,
            "company": company or "Empresa não identificada",
            "role": title,
            "level": "Júnior / entrada",
            "status": "Ativa",
            "statusRaw": f"Coleta automática em {collected_at[:10]} — {source_label}",
            "area": classify_area(title, text),
            "stack": classify_stack(tags, title),
            "fit": "AUTO — NOVA",
            "tags": tags,
            "requirements": requirements[:14],
            "differentials": [],
            "reason": f"Coletada automaticamente em {source_label}. A vaga passou pelos filtros de nível, tecnologia, contexto financeiro e duplicidade por exigências; revise o anúncio original antes de se candidatar.",
            "source": url,
            "collectedAt": collected_at,
            "auto": True,
        }
        new_jobs.append(job)
        known_sources.add(csource)
        dom = infer_domain(posting)
        if company and dom:
            domains[company] = dom
        print(f"[novo] {company} — {title}")
        time.sleep(0.12)

    if not new_jobs:
        print("[info] Nenhuma vaga nova e relevante, distinta por exigências, nesta execução.")
        return 0

    all_auto = auto_existing + new_jobs
    AUTO_FILE.write_text(render_auto(all_auto, domains or None), encoding="utf-8")
    print(f"[ok] {len(new_jobs)} novas vagas adicionadas. Total auto: {len(all_auto)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
