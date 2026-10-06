from __future__ import annotations

import html as htmllib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from quality import extract_jobposting, split_requirements, senior_conflict, location_fields, requirements_quality_conflict
from collection_audit import CandidateAudit, schedule, canonical_url as audit_url
from rules import DUPLICATE_SIMILARITY
from official_sources import (
    collect_official_postings,
    prefer_source,
    same_posting,
    same_company,
    source_metadata,
    source_priority,
)
from market_model import geography
from company_policy import (
    TARGET_COMPANIES,
    CORE_PRIORITY_COMPANIES,
    CONTEXT_COMPANIES as CONTEXT_ALLOWED_COMPANIES,
    normalize_company as canon_company,
    is_target_company as approved_company,
    is_contextual_company as contextual_company,
)

ROOT = Path(__file__).resolve().parents[1]
AUTO_FILE = ROOT / "data-auto.js"
BASE_FILES = [ROOT / f"data-{i}.js" for i in range(1, 8)]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36 Banco2027JobRadar/1.2"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
TIMEOUT = 20
FETCH_WORKERS = 8
OFFICIAL_POSTING_CACHE: dict[str, dict] = {}
OFFICIAL_DISCOVERY_REPORT: dict = {}
LINKEDIN_URL_BUCKET: dict[str, str] = {}
FETCH_FAILURES: dict[str, str] = {}

STRONG_FINANCE_PHRASES = [
    "segmento bancário", "segmento bancario", "setor bancário", "setor bancario", "mercado financeiro",
    "instituição financeira", "instituicao financeira", "instituições financeiras", "instituicoes financeiras",
    "banco de investimento", "bancos de investimento", "serviços financeiros", "servicos financeiros",
    "meios de pagamento", "infraestrutura financeira", "banking as a service", "banking-as-a-service",
    "produtos bancários", "produtos bancarios", "risco de crédito", "risco de credito", "políticas de crédito",
    "politicas de credito", "prevenção a fraudes", "prevencao a fraudes", "open finance", "mercado de capitais",
    "renda fixa", "investment banking", "financial services", "banking industry", "credit risk", "payments industry",
]

JUNIOR_TERMS = [
    "júnior", "junior", " jr", "jr ", "assistente", "associate", "nível i", "nivel i",
    "analyst i", "analista i", "level i", "nível 1", "nivel 1", "entry level", "entry-level",
    "estágio", "estagio", "estagiário", "estagiario", "estagiária", "estagiaria", "intern", "internship",
    "trainee", "early career", "graduate", "engineer i", "developer i",
]
SENIOR_TITLE_TERMS = ["sênior", "senior", "pleno", "specialist", "especialista", "lead", "principal", "staff"]
TECH_TERMS = [
    "software", "backend", "back-end", "desenvolvedor", "developer", "engenharia", "dados", "data",
    "sistemas", "cloud", "sre", "devops", "automação", "automacao", "python", "java", ".net", "c#",
    "sql", "api", "qa", "qualidade", "segurança", "security", "infraestrutura",
]

# A ocorrência de uma tecnologia em uma descrição longa não transforma uma
# vaga administrativa em vaga de tecnologia. O título precisa indicar uma
# área-alvo ou, em cargos genéricos de entrada, a descrição deve conter ao
# menos dois sinais técnicos fortes.
TARGET_TITLE_RE = re.compile(
    r"software|backend|back-end|front-?end|full\s*stack|developer|desenvolv|"
    r"engenheir|\bdata\b|dados|analytics|cientista|cloud|\bsre\b|devops|"
    r"automa[cç][aã]o|systems?|sistemas|tecnologia|\bti\b|\bit\b|security|seguran[cç]a|"
    r"cyber|\bqa\b|qualidade|risk|risco|credit|cr[eé]dito|fraud|fraude"
)
STRONG_TECH_TAGS = {
    "Python", "SQL", "Java", ".NET/C#", "JavaScript/Node", "REST/APIs", "Git",
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "CI/CD", "Microsserviços",
    "Mensageria", "Cloud", "Linux", "Terraform/IaC",
}

# As 8 vagas originalmente fornecidas pelo usuário não podem voltar como “novas”.
EXCLUDED_TITLE_FRAGMENTS = [
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
LINKEDIN_PRIORITY_COMPANIES = list(CORE_PRIORITY_COMPANIES)

GUPY_CAREERS = [
    "https://pagseguro.gupy.io/",
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
ITAU_CAREERS = "https://carreiras.itau.com.br/busca-de-vagas"
SANTANDER_WORKDAY = "https://santander.wd3.myworkdayjobs.com"
SANTANDER_SEARCHES = ("IT Analyst I", "Software Engineer Junior", "Data Analyst I", "Desenvolvedor Junior", "Analista Tecnologia Jr")
GOOGLE_CAREERS = "https://www.google.com/about/careers/applications/jobs/results/"

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
    "job-boards.greenhouse.io": "Greenhouse", "jobs.ashbyhq.com": "Ashby",
    "greenhouse.io": "Greenhouse",
    "querovagastech.com.br": "Quero Vagas Tech",
}

METADATA_PREFIXES = [
    "nível de experiência", "nivel de experiencia", "função ", "funcao ", "setores ", "tipo de emprego",
    "competências ", "competencias ", "indicações", "indicacoes",
]


def norm(s: str) -> str:
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip().lower()


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
    for company in LINKEDIN_PRIORITY_COMPANIES:
        for u in linkedin_query_urls(f'"{company}" junior tecnologia', (0,)):
            if u not in out:
                out.append(u)
            LINKEDIN_URL_BUCKET[u] = "core" if company in CORE_PRIORITY_COMPANIES else "priority"
    for kw in LINKEDIN_KEYWORDS:
        for u in linkedin_query_urls(kw, (0, 10)):
            if u not in out:
                out.append(u)
                LINKEDIN_URL_BUCKET[u] = "generic"
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
        urls = page_links(base, [r"\.gupy\.io/(?:job|jobs)/"], 500)
        if not urls:
            r = safe_get(base)
            if r and r.status_code < 400:
                host = urlparse(base).netloc
                for m in re.finditer(r"/jobs/(\d+)", r.text):
                    u = f"https://{host}/jobs/{m.group(1)}?jobBoardSource=gupy_public_page"
                    if u not in urls:
                        urls.append(u)
        for u in urls:
            if u not in out:
                out.append(u)
        time.sleep(0.1)
    print(f"[source] Gupy: {len(out)} URLs")
    return out


def lever_urls() -> list[str]:
    out = []
    for board in LEVER_BOARDS:
        for u in page_links(board, [r"jobs\.lever\.co/[^/]+/[a-z0-9-]+$"], 500):
            if u not in out:
                out.append(u)
    print(f"[source] Lever: {len(out)} URLs")
    return out


def official_ats_urls() -> list[str]:
    """Read public ATS feeds before using LinkedIn discovery."""
    global OFFICIAL_DISCOVERY_REPORT

    def fetch_json(url: str):
        response = safe_get(url, headers={"Accept": "application/json"})
        if response is None or response.status_code >= 400:
            code = response.status_code if response is not None else "unavailable"
            raise RuntimeError(f"HTTP {code}")
        return response.json()

    candidates, OFFICIAL_DISCOVERY_REPORT = collect_official_postings(fetch_json)
    out = []
    for candidate in candidates:
        url = candidate["url"]
        OFFICIAL_POSTING_CACHE[url] = candidate
        if url not in out:
            out.append(url)
    counts = OFFICIAL_DISCOVERY_REPORT.get("counts", {})
    OFFICIAL_DISCOVERY_REPORT["scheduled_for_audit"] = len(out)
    print(
        "[source] ATS oficiais: "
        f"{len(out)} URLs em {counts.get('boards_ok', 0)} boards; "
        f"{counts.get('boards_failed', 0)} falhas"
    )
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


def official_company_urls() -> list[str]:
    """Discover postings from the Itaú public results, including pagination."""
    out = []
    page = 1
    total_pages = 1
    while page <= min(total_pages, 20):
        response = safe_get(ITAU_CAREERS, params={"p": page})
        if response is None or response.status_code != 200:
            OFFICIAL_DISCOVERY_REPORT.setdefault("errors", []).append({"company": "Itaú", "provider": "company", "error": f"HTTP {response.status_code}" if response is not None else "fetch_unavailable"})
            break
        soup = BeautifulSoup(response.text, "html.parser")
        page_input = soup.select_one("input.pagination-current[max]")
        if page_input:
            total_pages = min(20, int(page_input.get("max", 1)))
        links = [urljoin(ITAU_CAREERS, a["href"]) for a in soup.select('a[href*="/vaga/"]')]
        links = [u for u in links if urlparse(u).hostname == "carreiras.itau.com.br" and
                 re.search(r"/vaga/[^/]+/[^/]+/\d+/\d+/?$", urlparse(u).path)]
        if not links:
            break
        out.extend(u for u in links if u not in out)
        page += 1
    print(f"[source] Páginas oficiais: {len(out)} URLs")
    return out


def workday_urls() -> list[str]:
    """Search Santander's public Workday feed with a bounded set of entry titles."""
    out = []
    endpoint = f"{SANTANDER_WORKDAY}/wday/cxs/santander/SantanderCareers/jobs"
    for query in SANTANDER_SEARCHES:
        offset = 0
        while offset < 100:
            try:
                response = SESSION.post(endpoint, json={"appliedFacets": {}, "limit": 20,
                                                        "offset": offset, "searchText": query}, timeout=TIMEOUT)
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                OFFICIAL_DISCOVERY_REPORT.setdefault("errors", []).append({
                    "company": "Santander", "provider": "company", "query": query, "error": type(exc).__name__})
                break
            records = payload.get("jobPostings", [])
            for row in records:
                path = row.get("externalPath", "")
                if re.fullmatch(r"/job/[^?#]+", path):
                    url = SANTANDER_WORKDAY + "/pt-BR/SantanderCareers" + path
                    if url not in out:
                        out.append(url)
            offset += len(records)
            if not records or offset >= payload.get("total", 0):
                break
    print(f"[source] Santander Workday: {len(out)} URLs")
    return out


def google_careers_urls() -> list[str]:
    out = []
    for query in ("early career", "software engineer junior", "data analyst"):
        response = safe_get(GOOGLE_CAREERS, params={"q": query, "location": "Brazil"})
        if response is None or response.status_code != 200:
            OFFICIAL_DISCOVERY_REPORT.setdefault("errors", []).append({
                "company": "Google", "provider": "company", "query": query,
                "error": f"HTTP {response.status_code}" if response is not None else "fetch_unavailable"})
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.select('a[href^="jobs/results/"]'):
            url = urljoin("https://www.google.com/about/careers/applications/", anchor["href"])
            if urlparse(url).hostname == "www.google.com" and re.match(r"/about/careers/applications/jobs/results/\d+-", urlparse(url).path):
                if url not in out:
                    out.append(url)
    print(f"[source] Google Careers: {len(out)} URLs")
    return out


def linkedin_job_id(url: str) -> str | None:
    ids = re.findall(r"(\d{7,})", url)
    return ids[-1] if ids else None


def fetch_page(url: str) -> tuple[BeautifulSoup | None, dict | None]:
    cached = OFFICIAL_POSTING_CACHE.get(url)
    if cached:
        posting = cached["posting"]
        return BeautifulSoup(str(posting.get("description") or ""), "html.parser"), posting
    parsed = urlparse(url)
    if parsed.hostname == "www.google.com" and parsed.path.startswith("/about/careers/applications/jobs/results/"):
        response = safe_get(url)
        if response is None or response.status_code != 200:
            FETCH_FAILURES[url] = f"fetch_{response.status_code}" if response is not None else "fetch_unavailable"
            return None, None
        page = BeautifulSoup(response.text, "html.parser")
        detail = page.select_one("div.DkhPwc")
        title = detail.select_one("h2.p1N2lc") if detail else None
        if not detail or not title:
            FETCH_FAILURES[url] = "parser_missing_detail"
            return None, None
        place = detail.select_one("span.pwO9Dc.vo5qdf")
        location_text = place.get_text(" ", strip=True) if place else ""
        location = "São Paulo, Brasil" if re.search(r"s[aã]o paulo", location_text, re.I) else location_text
        posting = {"@type": "JobPosting", "title": title.get_text(" ", strip=True),
                   "description": str(detail), "hiringOrganization": {"name": "Google"},
                   "jobLocation": {"address": {"addressLocality": location}} if location else {}}
        return detail, posting
    if (parsed.hostname == "santander.wd3.myworkdayjobs.com"
            and parsed.path.startswith("/pt-BR/SantanderCareers/job/")):
        detail_url = SANTANDER_WORKDAY + "/wday/cxs/santander/SantanderCareers" + parsed.path.split("/SantanderCareers", 1)[1]
        response = safe_get(detail_url, headers={"Accept": "application/json"})
        if response is None or response.status_code != 200:
            FETCH_FAILURES[url] = f"fetch_{response.status_code}" if response is not None else "fetch_unavailable"
            return None, None
        try:
            detail = response.json().get("jobPostingInfo", {})
        except ValueError:
            FETCH_FAILURES[url] = "fetch_invalid_json"
            return None, None
        posting = {"@type": "JobPosting", "title": detail.get("title"),
                   "description": detail.get("jobDescription"), "hiringOrganization": {"name": "Santander"},
                   "jobLocation": {"address": {"addressLocality": detail.get("location")}},
                   "datePosted": detail.get("startDate")}
        return BeautifulSoup(str(posting["description"] or ""), "html.parser"), posting
    fetch_url = url
    if "linkedin.com/jobs/view/" in url:
        jid = linkedin_job_id(url)
        if jid:
            fetch_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}"
    r = safe_get(fetch_url)
    if r is None or r.status_code >= 400:
        FETCH_FAILURES[url] = f"fetch_{r.status_code}" if r is not None else "fetch_unavailable"
        return None, None
    soup = BeautifulSoup(r.text, "html.parser")
    return soup, extract_jobposting(soup)


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
    if any(k in x for k in ["segurança", "seguranca", "security", "cyber", "fraude", "fraud"]):
        return "Segurança"
    if any(k in x for k in ["dados", "data scientist", "cientista de dados", "analytics", "data engineer"]):
        return "Dados & Analytics"
    if any(k in x for k in ["sre", "cloud", "infraestrutura", "devops"]):
        return "Cloud / SRE"
    if any(k in x for k in ["automação", "automacao", "rpa"]):
        return "Automação & IA"
    if any(k in x for k in ["qualidade", " qa", "testador"]):
        return "QA"
    if any(k in x for k in ["governança", "governanca", "governance", "power bi", "power platform"]):
        return "Governança & BI"
    if any(k in x for k in ["pagamento", "payments", "open finance", "crédito", "credito", "risco"]):
        return "Produtos Financeiros"
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
    if not TARGET_TITLE_RE.search(title_n):
        strong_tags = set(classify_tags(text)) & STRONG_TECH_TAGS
        if len(strong_tags) < 2:
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
    aliases = {
        "restful": "rest", "restapi": "api", "restapis": "api",
        "postgres": "postgresql", "nodejs": "node", "microservices": "microservice",
        "microsservicos": "microservice", "amazonwebservices": "aws",
        "googlecloud": "gcp", "microsoftazure": "azure",
    }
    A = {aliases.get(x, x) for x in req_tokens(a)}
    B = {aliases.get(x, x) for x in req_tokens(b)}
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
    # Strongest evidence first. LinkedIn remains useful for discovering a job,
    # but an official ATS candidate wins when both represent the same posting.
    for bucket in [official_ats_urls(), official_company_urls(), workday_urls(), google_careers_urls(), gupy_urls(), lever_urls(), linkedin_urls(), other_source_urls()]:
        for u in bucket:
            if u not in out:
                out.append(u)
    print(f"[info] URLs candidatas totais: {len(out)}")
    return out


def discovery_rows(urls: list[str]) -> list[dict]:
    rows = []
    for url in urls:
        provider = source_metadata(url, structured=url in OFFICIAL_POSTING_CACHE)["provider"]
        bucket = ("aggregator" if provider == "aggregator" else
                  LINKEDIN_URL_BUCKET.get(url, "generic") if provider == "linkedin" else "official")
        host = urlparse(url).hostname or ""
        source = ("Itaú Careers" if host == "carreiras.itau.com.br" else
                  "Santander Workday" if host == "santander.wd3.myworkdayjobs.com" else
                  "Google Careers" if host == "www.google.com" else provider)
        rows.append({"url": url, "source": source, "bucket": bucket})
    return rows


def requirements_for(soup, posting):
    req, diff = split_requirements(soup, posting)
    method = "section"
    if len(req) < 3:
        # JSON-LD may carry a structured qualification field even when its
        # description has no recognized heading. Do not split free-form prose.
        raw = (posting or {}).get("qualifications") or (posting or {}).get("skills")
        if isinstance(raw, list):
            structured = [str(item).strip() for item in raw if isinstance(item, str) and item.strip()]
            if len(structured) >= 3:
                req, method = structured, "json_ld"
        if len(req) < 3:
            bullets = extract_bullets(soup, posting)
            # A responsibilities list can mention many technologies. Require
            # explicit qualification wording before treating loose bullets as
            # candidate requirements without a recognized heading.
            qualification_cues = r"conhecimento|experi[eê]ncia|familiaridade|forma[cç][aã]o|proficiency|knowledge|experience|required"
            if (len(bullets) >= 3 and any(re.search(qualification_cues, item, re.I) for item in bullets)
                    and not requirements_quality_conflict((posting or {}).get("title", ""), bullets)):
                req, method = bullets, "technical_bullets"
    return req, diff, method


def main() -> int:
    existing = []
    for p in BASE_FILES:
        existing.extend(parse_js_array(p))
    auto_existing = parse_js_array(AUTO_FILE)
    existing.extend(auto_existing)
    max_id = max([int(j.get("id", 0)) for j in existing] + [0])
    known_sources = {audit_url(u) for j in existing for u in
                     [j.get("source"), *(row.get("url") for row in j.get("sources", []) if isinstance(row, dict))] if u}

    candidate_urls = discover_urls()
    new_jobs = []
    domains = existing_auto_domains()
    collected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    audit = CandidateAudit(ROOT / "candidate-history.json", discovery_rows(candidate_urls), collected_at)
    scan_urls = schedule(discovery_rows(candidate_urls), audit, known_sources,
                         lambda url: source_metadata(url, structured=url in OFFICIAL_POSTING_CACHE)["provider"] != "unknown")
    print(f"[info] URLs a validar: {len(scan_urls)} em até {FETCH_WORKERS} workers")
    def timed_fetch(url):
        started = time.monotonic()
        try:
            result = fetch_page(url)
        except Exception as exc:
            FETCH_FAILURES[url] = f"fetch_exception_{type(exc).__name__}"
            result = (None, None)
        return url, (result, round((time.monotonic() - started) * 1000))
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        fetched = dict(pool.map(timed_fetch, scan_urls))

    for url in scan_urls:
        try:
            csource = audit_url(url)
            (soup, posting), elapsed_ms = fetched[url]
            audit.records[url]["fetchMs"] = elapsed_ms
            if not soup and not posting:
                failure = FETCH_FAILURES.get(url, "fetch_empty")
                audit.mark(url, "retry" if failure in {"fetch_429", "fetch_500", "fetch_502", "fetch_503", "fetch_504"}
                           else "fetch_failed", failure)
                continue
            title = title_from(posting, soup)
            company = company_from(posting, soup)
            audit.records[url].update(company=company or None, role=title or None)
            text = text_from_posting(posting, soup)
            content = json.dumps(posting, ensure_ascii=False, sort_keys=True) if posting else str(soup)
            if not title:
                audit.mark(url, "rejected", "title_missing", content=content)
                continue
            if not company:
                audit.mark(url, "rejected", "company_missing", content=content)
                continue
            audit.transition(url, "parsed", "title_and_company_extracted")
            if not is_relevant(title, company, text):
                reason = ("seniority_conflict" if any(term in norm(title) for term in SENIOR_TITLE_TERMS) else
                          "company_not_target" if not approved_company(company) and not strong_finance_context(text) else
                          "role_irrelevant")
                audit.mark(url, "rejected", reason, content=content)
                continue
            if senior_conflict(title, text):
                audit.mark(url, "rejected", "seniority_conflict", content=content)
                continue
            requirements, differentials, method = requirements_for(soup, posting)
            if len(requirements) < 3:
                possible_review = source_metadata(url, structured=bool(posting))
                state = "retry" if possible_review["official"] and requirements and len(classify_tags(text)) >= 2 else "rejected"
                audit.mark(url, state, "requirements_review" if state == "retry" else "requirements_insufficient", content=content, method=method)
                continue
            if requirements_quality_conflict(title, requirements):
                audit.mark(url, "rejected", "requirements_quality_conflict", content=content, method=method)
                continue
            candidate_source = source_metadata(url, structured=bool(posting))
            candidate_identity = {
                "company": company,
                "role": title,
                "requirements": requirements,
                "source": url,
                "sourcePriority": candidate_source["priority"],
            }
            # Deduplicate by requirements, but allow an official source to replace
            # the LinkedIn/aggregator representation of the same posting.
            duplicate = next((
                j for j in existing + new_jobs
                if same_posting(candidate_identity, j, similarity) and (
                    similarity(requirements, j.get("requirements", [])) >= DUPLICATE_SIMILARITY
                    or source_priority(candidate_identity) != source_priority(j)
                )
            ), None)
            if duplicate and not prefer_source(candidate_identity, duplicate):
                audit.mark(url, "duplicate", "duplicate_requirements", content=content, method=method)
                continue
            tags = classify_tags(" ".join([title, text, " ".join(requirements)]))
            if len(tags) < 2:
                audit.mark(url, "rejected", "technical_tags_insufficient", content=content, method=method)
                continue

            source_label = candidate_source["name"]
            location = location_fields(posting, text)
            search_scope = "São Paulo" if candidate_source["provider"] == "linkedin" else None
            geo = geography({**location, "searchScopeLocation": search_scope})
            # The collector is a São Paulo/remote radar. Explicitly external or
            # unknown official-board locations remain outside; LinkedIn results are
            # retained with a clear "location to confirm" marker because the query
            # itself is scoped to São Paulo.
            if not geo["geographyEligible"]:
                reason = "geography_review" if geo["geographyScope"] in {"unverified", "remote_unverified"} else "outside_geography"
                audit.mark(url, "retry" if reason == "geography_review" else "rejected", reason, content=content, method=method)
                continue
            audit.transition(url, "qualified", "quality_and_geography_passed")
            max_id += 1
            job = {
                "id": max_id,
                "company": company or "Empresa não identificada",
                "role": title,
                "level": "Júnior / entrada",
                "status": "Possivelmente encerrada",
                "statusRaw": f"Coleta automática em {collected_at[:10]} — {source_label}",
                "area": classify_area(title, text),
                "stack": classify_stack(tags, title),
                "fit": "AUTO — NOVA",
                "tags": tags,
                "requirements": requirements[:14],
                "requirementsExtractionMethod": method,
                "differentials": differentials,
                **location,
                "searchScopeLocation": search_scope,
                "sourceName": source_label,
                "sourceProvider": candidate_source["provider"],
                "sourceOfficial": candidate_source["official"],
                "sourcePriority": candidate_source["priority"],
                "sourceStructured": bool(posting),
                "reason": f"Coletada automaticamente em {source_label}. A vaga passou pelos filtros de nível, tecnologia, empresa-alvo ou contexto financeiro e duplicidade por exigências; revise o anúncio original antes de se candidatar.",
                "source": url,
                "collectedAt": collected_at,
                "auto": True,
            }
            if duplicate:
                job["supersedesSource"] = duplicate.get("source")
            new_jobs.append(job)
            audit.mark(url, "accepted", "qualified_for_catalog", content=content, method=method)
            known_sources.add(csource)
            dom = infer_domain(posting)
            if company and dom:
                domains[company] = dom
            print(f"[novo] {company} — {title}")
        except Exception as exc:
            if audit.records[url]["status"] is None:
                audit.mark(url, "retry", f"processing_exception_{type(exc).__name__}")
            print(f"[candidate] {url} -> {type(exc).__name__}")

    funnel = audit.finish(scheduled=len(scan_urls), scanned=len(scan_urls))

    official_added = sum(source_priority(j) >= 3 for j in new_jobs)
    source_counts = {}
    for job in new_jobs:
        name = job.get("sourceName", "Não classificada")
        source_counts[name] = source_counts.get(name, 0) + 1
    (ROOT / "collection-report.json").write_text(json.dumps({
        "updatedAt": collected_at,
        "added": len(new_jobs),
        "candidateUrls": len(candidate_urls),
        "officialCandidateUrls": sum(source_metadata(u, structured=u in OFFICIAL_POSTING_CACHE)["official"] for u in candidate_urls),
        "linkedinCandidateUrls": sum("linkedin.com" in u for u in candidate_urls),
        "officialAdded": official_added,
        "fallbackAdded": len(new_jobs) - official_added,
        "sourceCounts": source_counts,
        "officialBoards": OFFICIAL_DISCOVERY_REPORT,
        **funnel,
    }, ensure_ascii=False), encoding="utf-8")
    if not new_jobs:
        print("[info] Nenhuma vaga nova e relevante, distinta por exigências, nesta execução.")
        return 0

    all_auto = auto_existing + new_jobs
    AUTO_FILE.write_text(render_auto(all_auto, domains or None), encoding="utf-8")
    print(f"[ok] {len(new_jobs)} novas vagas adicionadas. Total auto: {len(all_auto)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
