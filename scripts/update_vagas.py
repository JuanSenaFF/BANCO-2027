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
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36 Banco2027JobRadar/1.1"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
TIMEOUT = 20
MAX_NEW = 12

TARGET_COMPANIES = [
    "Itaú", "Bradesco", "Santander", "BTG Pactual", "Nubank", "Banco Inter", "Inter", "C6 Bank",
    "XP", "Safra", "Mercado Pago", "Stone", "PagBank", "B3", "Núclea", "CERC", "Cielo",
    "Rede", "Getnet", "Dock", "Pismo", "Banco BV", "Daycoval", "Banco ABC Brasil", "Banco PAN",
    "Banco BMG", "Neon", "PicPay", "Creditas", "Will Bank", "Genial Investimentos", "EQI",
    "Rico", "Clear", "Avenue", "Sicoob", "Sicredi", "Sinqia", "Matera", "FitBank",
    "ANBIMA", "BMP", "Bancorbrás", "Nava", "FCamara", "Serasa Experian",
]

FINANCE_TERMS = [
    "banco", "bancário", "bancaria", "fintech", "pagamentos", "payment", "financeiro", "financial",
    "crédito", "credito", "investimentos", "investimento", "trading", "cobrança", "cobranca", "baas",
    "mercado de capitais", "seguros", "seguradora", "adquirência", "adquirencia", "pix", "cartões", "cartoes",
    "open finance", "risco", "fraude",
]
JUNIOR_TERMS = ["júnior", "junior", " jr", "jr ", "assistente", "associate", "nível i", "nivel i", "trainee"]
TECH_TERMS = [
    "software", "backend", "back-end", "desenvolvedor", "developer", "engenharia", "dados", "data",
    "sistemas", "cloud", "sre", "devops", "automação", "automacao", "python", "java", ".net", "c#",
    "sql", "api", "qa", "qualidade", "segurança", "security", "infraestrutura",
]

LINKEDIN_KEYWORDS = [
    "backend junior", "software engineer junior", "desenvolvedor junior", "analista sistemas junior",
    "dados junior", "data engineer junior", "automacao python junior", "cloud sre junior",
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

LEVER_BOARDS = [
    "https://jobs.lever.co/pismo",
]

SITEMAPS = [
    "https://remotar.com.br/sitemap.xml",
    "https://querovagastech.com.br/sitemap.xml",
]

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
    return re.sub(r"\s+", " ", s).strip().lower()


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    for d in SOURCE_NAME:
        if host.endswith(d):
            return d
    return host


def safe_get(url: str, **kwargs):
    try:
        r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True, **kwargs)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(1.5)
            r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True, **kwargs)
        return r
    except Exception as exc:
        print(f"[fetch] {url} -> {exc}")
        return None


def linkedin_urls() -> list[str]:
    out = []
    endpoint = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for kw in LINKEDIN_KEYWORDS:
        for start in (0, 10):
            params = {
                "keywords": kw,
                "geoId": "106057199",  # Brasil
                "f_TPR": "r2592000",   # últimos 30 dias
                "f_E": "2",            # entry level
                "sortBy": "DD",
                "start": str(start),
            }
            r = safe_get(endpoint, params=params)
            if not r or r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("li") or [soup]
            for card in cards:
                urn = card.get("data-entity-urn", "") if hasattr(card, "get") else ""
                m = re.search(r"jobPosting:(\d+)", urn)
                if not m:
                    a = card.select_one("a[href*='/jobs/view/']") if hasattr(card, "select_one") else None
                    href = a.get("href", "") if a else ""
                    m = re.search(r"(?:-|/)(\d+)(?:\?|$)", href)
                if m:
                    url = f"https://www.linkedin.com/jobs/view/{m.group(1)}"
                    if url not in out:
                        out.append(url)
            time.sleep(0.25)
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
    # fallback for links serialized in scripts
    if len(out) < 5:
        for p in patterns:
            for m in re.finditer(r"https?://[^\"'<> ]+", r.text):
                u = htmllib.unescape(m.group(0))
                if re.search(p, u, re.I) and u not in out:
                    out.append(u)
                    if len(out) >= limit:
                        break
    return out


def gupy_urls() -> list[str]:
    out = []
    for base in GUPY_CAREERS:
        urls = page_links(base, [r"\.gupy\.io/(?:job|jobs)/"])
        # many career pages use relative /jobs/<id> links hidden in page data
        if not urls:
            r = safe_get(base)
            if r and r.status_code < 400:
                host = urlparse(base).netloc
                for m in re.finditer(r"/jobs/(\d+)", r.text):
                    u = f"https://{host}/jobs/{m.group(1)}?jobBoardSource=gupy_public_page"
                    if u not in urls:
                        urls.append(u)
        for u in urls[:40]:
            if u not in out:
                out.append(u)
        time.sleep(0.2)
    print(f"[source] Gupy: {len(out)} URLs")
    return out


def lever_urls() -> list[str]:
    out = []
    for board in LEVER_BOARDS:
        for u in page_links(board, [r"jobs\.lever\.co/[^/]+/[a-z0-9-]+$"], 80):
            if u not in out:
                out.append(u)
    print(f"[source] Lever: {len(out)} URLs")
    return out


def sitemap_job_urls(url: str, max_urls: int = 50) -> list[str]:
    r = safe_get(url)
    if not r or r.status_code >= 400:
        return []
    try:
        root = ET.fromstring(r.text)
    except Exception:
        return []
    locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
    # sitemap index: inspect a small number of child maps
    if locs and all(x.endswith(".xml") or "sitemap" in x for x in locs[: min(5, len(locs))]):
        nested = []
        for child in locs[-3:]:
            nested.extend(sitemap_job_urls(child, max_urls=max_urls))
            if len(nested) >= max_urls:
                break
        return nested[:max_urls]
    jobs = [u for u in locs if re.search(r"/(?:job|vagas?)/", u, re.I)]
    return jobs[-max_urls:]


def other_source_urls() -> list[str]:
    out = []
    for sm in SITEMAPS:
        for u in sitemap_job_urls(sm, 40):
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
    m = re.search(r"(?:-|/)(\d+)(?:\?|$)", url)
    return m.group(1) if m else None


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
            data = json.loads(script.string or script.get_text())
            posting = find_jobposting(data)
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
        if desc:
            return norm(desc.get_text(" ", strip=True))
        return norm(soup.get_text(" ", strip=True))
    return ""


def company_from(posting: dict | None, soup: BeautifulSoup | None) -> str:
    if posting:
        org = posting.get("hiringOrganization")
        if isinstance(org, dict) and org.get("name"):
            return str(org["name"]).strip()
    if soup:
        for sel in [".topcard__org-name-link", ".topcard__flavor", "[class*='company-name']", "meta[property='og:site_name']"]:
            node = soup.select_one(sel)
            if node:
                val = (node.get("content") or node.get_text(" ", strip=True)).strip()
                if val:
                    return val
    return ""


def title_from(posting: dict | None, soup: BeautifulSoup | None) -> str:
    if posting and posting.get("title"):
        return str(posting["title"]).strip()
    if soup:
        for sel in ["h1", ".top-card-layout__title", "[class*='job-title']"]:
            node = soup.select_one(sel)
            if node:
                val = node.get_text(" ", strip=True)
                if val:
                    return val
        if soup.title:
            return soup.title.get_text(" ", strip=True)
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
    techish = []
    for t in raw:
        lt = t.lower()
        if any(b in lt for b in benefit_words):
            continue
        if any(re.search(p, lt, re.I) for p in TAG_PATTERNS.values()) or any(k in lt for k in ["conhecimento", "experiência", "experiencia", "vivência", "vivencia", "familiaridade", "formação", "formacao"]):
            techish.append(t)
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
    if any(k in x for k in ["qualidade", "qa", "testador"]):
        return "QA"
    if any(k in x for k in ["sistemas", "sustentação", "sustentacao"]):
        return "Sistemas / Sustentação"
    return "Engenharia de Software"


def classify_stack(tags: list[str], title: str) -> str:
    x = norm(title)
    for stack, tag, words in [
        ("Python", "Python", ["python"]),
        ("Java", "Java", ["java", "spring"]),
        (".NET / C#", ".NET/C#", [".net", "c#"]),
        ("JavaScript / Node", "JavaScript/Node", ["node", "javascript", "typescript"]),
    ]:
        if tag in tags and any(w in x for w in words):
            return stack
    if "Python" in tags and "Java" not in tags and ".NET/C#" not in tags:
        return "Python"
    if "Java" in tags and ".NET/C#" not in tags:
        return "Java"
    if ".NET/C#" in tags:
        return ".NET / C#"
    if "Dados/BI" in tags:
        return "Dados / BI"
    if "Cloud" in tags:
        return "Cloud / SRE"
    return "Multistack"


def is_relevant(title: str, company: str, text: str) -> bool:
    merged = norm(" ".join([title, company, text[:5000]]))
    title_n = norm(title)
    junior = any(t in title_n for t in JUNIOR_TERMS) or any(t in merged[:1200] for t in JUNIOR_TERMS)
    tech = any(t in merged for t in TECH_TERMS)
    finance = any(norm(t) in merged for t in TARGET_COMPANIES) or any(t in merged for t in FINANCE_TERMS)
    # reject explicitly senior-only / pleno-only titles
    if any(t in title_n for t in ["sênior", "senior", "pleno", "specialist", "especialista", "lead"]):
        return False
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


def existing_auto_domains() -> dict[str, str]:
    if not AUTO_FILE.exists():
        return {}
    text = AUTO_FILE.read_text(encoding="utf-8")
    m = re.search(r"Object\.assign\(window\.BANCO2027\.domains,(\{.*?\})\);", text, re.S)
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
    buckets = [linkedin_urls(), gupy_urls(), lever_urls(), other_source_urls()]
    out = []
    for bucket in buckets:
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
    known_urls = {j.get("source", "") for j in existing if j.get("source")}

    candidate_urls = discover_urls()
    new_jobs = []
    domains = existing_auto_domains()
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

        # Regra principal de duplicidade: exigências essencialmente idênticas.
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
            "reason": f"Coletada automaticamente em {source_label}. Revise o anúncio original antes de se candidatar; a compatibilidade é calculada pelas exigências extraídas.",
            "source": url,
            "collectedAt": collected_at,
            "auto": True,
        }
        new_jobs.append(job)
        dom = infer_domain(posting)
        if company and dom:
            domains[company] = dom
        print(f"[novo] {company} — {title}")
        time.sleep(0.18)

    if not new_jobs:
        print("[info] Nenhuma vaga nova distinta por exigências nesta execução.")
        return 0

    all_auto = auto_existing + new_jobs
    AUTO_FILE.write_text(render_auto(all_auto, domains or None), encoding="utf-8")
    print(f"[ok] {len(new_jobs)} novas vagas adicionadas. Total auto: {len(all_auto)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
