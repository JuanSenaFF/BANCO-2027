"""Turn recent API discoveries into validated catalog jobs, then link them in Supabase.

Prepare runs before validate_auto/build_catalog; finalize runs only after the
catalog has been synchronized. A third-party API is never publication evidence:
the actual employer's current public job posting must confirm the vacancy.
"""
from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import update_vagas as core
from candidate_pipeline import Candidate, MAX_POSTING_AGE_DAYS, SupabaseInbox, posting_age_days, qualification
from company_policy import COMPANIES, is_target_company, normalize_company
from official_sources import OFFICIAL_BOARDS, OFFICIAL_COMPANY_HOSTS, provider_for_url, source_metadata
from quality import extract_jobposting, safe_fetch, split_requirements, verify
from source_resolution import board_for
from validate_auto import canonical_url, valid


ROOT = Path(__file__).resolve().parents[1]
AUTO_FILE = ROOT / "data-auto.js"
BASE_FILES = [ROOT / f"data-{i}.js" for i in range(1, 8)]
OFFICIAL_PROVIDERS = {"company", "greenhouse", "lever", "ashby", "gupy"}
LINK_RE = re.compile(r"https://[^\s<>\"')]+", re.I)
BATCH_SIZE = 200
BOARD_COMPANIES = {(board.provider, board.token): board.company for board in OFFICIAL_BOARDS}
BOARD_COMPANIES[("lever", "pismo")] = "Pismo"
COMPANY_HOSTS = {
    "carreiras.itau.com.br": "Itaú",
    "santander-brasil.interviewhr.com": "Santander",
    "fitbank.vagas.solides.com.br": "FitBank",
}


def official_urls(row: dict) -> list[str]:
    options = [row.get("apply_url"), row.get("source_url")]
    # Only follow recognized public employer boards linked in an API record.
    options.extend(LINK_RE.findall(str(row.get("description_raw") or "")))
    out = []
    for option in options:
        url = str(option or "").rstrip(".,;]")
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        trusted_host = (
            host in OFFICIAL_COMPANY_HOSTS
            or host in {"boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "jobs.eu.lever.co", "jobs.ashbyhq.com"}
            or (host.endswith(".gupy.io") and host.count(".") == 2)
        )
        if parsed.scheme == "https" and trusted_host and provider_for_url(url) in OFFICIAL_PROVIDERS and url not in out:
            out.append(url)
    return out[:4]


def employer_board_matches(url: str, company: str) -> bool:
    parsed = urlparse(url)
    provider = provider_for_url(url)
    if provider == "gupy":
        return parsed.hostname.split(".")[0] == board_for(company)
    if provider == "company":
        expected = COMPANY_HOSTS.get(parsed.hostname)
        return bool(expected) and match_company(expected, company)
    token = parsed.path.strip("/").split("/")[0].lower()
    expected = BOARD_COMPANIES.get((provider, token))
    return bool(expected) and match_company(expected, company)


def recent(value: str | None) -> bool:
    age = posting_age_days(value)
    return age is not None and -2 <= age <= MAX_POSTING_AGE_DAYS


def match_company(raw: str, verified: str) -> bool:
    if not verified or not is_target_company(verified):
        return False
    if not raw or not is_target_company(raw):
        # Repositories and aggregator names are not employer evidence.
        return True
    raw_key, verified_key = normalize_company(raw), normalize_company(verified)
    return any(
        raw_key in {normalize_company(name) for name in (item.name, *item.aliases)}
        and verified_key in {normalize_company(name) for name in (item.name, *item.aliases)}
        for item in COMPANIES
    )


def job_from_official(row: dict, url: str, session: requests.Session) -> tuple[dict | None, str]:
    try:
        response = safe_fetch(session, url)
    except (requests.RequestException, ValueError, OSError) as exc:
        return None, f"falha ao consultar anúncio oficial ({type(exc).__name__})"
    if response.status_code in (404, 410):
        return None, "anúncio oficial encerrado"
    if response.status_code != 200:
        return None, f"consulta inconclusiva (HTTP {response.status_code})"
    if getattr(response, "url", url) != url:
        return None, "anúncio redirecionado; origem exige revisão"
    soup = BeautifulSoup(response.text, "html.parser")
    posting = extract_jobposting(soup)
    if not posting:
        return None, "anúncio oficial sem JobPosting"
    company = core.company_from(posting, soup)
    title = core.title_from(posting, soup)
    if not match_company(str(row.get("company_raw") or ""), company):
        return None, "empresa divergente ou fora das empresas-alvo"
    if not employer_board_matches(url, company):
        return None, "anúncio em portal de outra empresa ou board não cadastrado"
    if not title or SequenceMatcher(None, core.norm(title), core.norm(row.get("title_raw") or "")).ratio() < 0.65:
        return None, "título diverge do anúncio oficial"
    if not recent(posting.get("datePosted") or row.get("published_at")):
        return None, "data do anúncio não recente ou ausente"
    requirements, differentials = split_requirements(soup, posting)
    text = core.text_from_posting(posting, soup)
    if len(requirements) < 3 or len(core.classify_tags(text)) < 2:
        return None, "requisitos técnicos insuficientes no anúncio oficial"
    source = source_metadata(url, structured=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    job = {
        "company": company, "role": title, "level": "Júnior / entrada",
        "statusRaw": f"Descoberta por {row.get('provider')} e conferida no anúncio oficial",
        "area": core.classify_area(title, text),
        "tags": core.classify_tags(text),
        "requirements": requirements[:14], "differentials": differentials,
        "source": url, "sourceName": source["name"], "sourceProvider": source["provider"],
        "sourceOfficial": True, "sourcePriority": source["priority"], "sourceStructured": True,
        "reason": f"Descoberta pela API {row.get('provider')}; empresa, data, nível e requisitos conferidos no anúncio oficial.",
        "collectedAt": now, "auto": True, "candidateKey": row["candidate_key"],
    }
    job["stack"] = core.classify_stack(job["tags"], title)
    if row.get("source_url") and row["source_url"] != url:
        job["sources"] = [{"url": row["source_url"], "name": "Descoberta por API", "provider": "aggregator", "official": False, "priority": 0}]
    # Reuse the same evidence check as catalog verification without a second fetch.
    checked = verify(job, session, response=response)
    job.update(checked)
    if job.get("status") != "Ativa":
        return None, job.get("verificationReason") or "atividade não confirmada"
    job.update(core.location_fields(posting, text))
    ok, reason = valid(job)
    return (job, "ok") if ok else (None, reason)


def candidates(inbox: SupabaseInbox) -> list[dict]:
    rows = []
    for offset in range(0, 5000, BATCH_SIZE):
        response = inbox.session.get(inbox._endpoint("job_candidates"), params={
            "select": "candidate_key,provider,source_url,apply_url,title_raw,company_raw,location_raw,description_raw,published_at,processing_status,attempt_count,next_retry_at",
            "processing_status": "in.(qualified,review_required,discovered)",
            "order": "candidate_key.asc", "limit": str(BATCH_SIZE), "offset": str(offset),
        }, timeout=30)
        if not response.ok:
            raise RuntimeError(f"Supabase job_candidates: HTTP {response.status_code}: {response.text[:300]}")
        page = response.json()
        if not isinstance(page, list):
            raise RuntimeError("Supabase job_candidates: resposta inválida")
        rows.extend(page)
        if len(page) < BATCH_SIZE:
            return rows
    raise RuntimeError("Fila acima de 5.000 registros; interrompida antes de paginação incompleta")


def update_candidate(inbox: SupabaseInbox, row: dict, *, status: str, reason: str | None, delay_days: int = 0) -> None:
    retry = datetime.now(timezone.utc) + timedelta(days=delay_days) if delay_days else None
    response = inbox.session.patch(inbox._endpoint("job_candidates"), params={
        "candidate_key": f"eq.{row['candidate_key']}",
        "processing_status": "in.(qualified,review_required,discovered)",
    }, json={
        "processing_status": status,
        "attempt_count": int(row.get("attempt_count") or 0) + 1,
        "rejection_reason": reason,
        "next_retry_at": retry.isoformat() if retry else None,
    }, headers={"Prefer": "return=minimal"}, timeout=30)
    if not response.ok:
        raise RuntimeError(f"Supabase job_candidates: HTTP {response.status_code}: {response.text[:300]}")


def prepare(inbox: SupabaseInbox, session: requests.Session) -> dict[str, int]:
    existing = core.parse_js_array(AUTO_FILE)
    known = {canonical_url(job.get("source", "")) for path in BASE_FILES for job in core.parse_js_array(path)}
    known.update(canonical_url(job.get("source", "")) for job in existing)
    tracked = {job.get("candidateKey") for job in existing}
    staged = []
    counts = {"examined": 0, "staged": 0, "rejected": 0, "review": 0}
    for row in candidates(inbox):
        if row["candidate_key"] in tracked:
            continue
        if row.get("next_retry_at") and datetime.fromisoformat(row["next_retry_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc):
            continue
        counts["examined"] += 1
        evaluation = qualification(Candidate(
            provider=str(row.get("provider") or ""), external_id=row["candidate_key"],
            source_url=str(row.get("source_url") or ""), title=str(row.get("title_raw") or ""),
            company=str(row.get("company_raw") or ""), location=str(row.get("location_raw") or ""),
            description=str(row.get("description_raw") or ""), published_at=row.get("published_at"),
        ))
        if evaluation["status"] == "rejected":
            update_candidate(inbox, row, status="rejected", reason=evaluation["reasons"][0])
            counts["rejected"] += 1
            continue
        urls = official_urls(row)
        if not urls:
            update_candidate(inbox, row, status="review_required", reason="sem anúncio oficial rastreável", delay_days=7)
            counts["review"] += 1
            continue
        reasons = []
        for url in urls:
            if canonical_url(url) in known:
                reasons.append("anúncio já consta do catálogo")
                continue
            job, reason = job_from_official(row, url, session)
            if job:
                staged.append(job)
                tracked.add(row["candidate_key"])
                known.add(canonical_url(url))
                break
            reasons.append(reason)
        if row["candidate_key"] not in tracked:
            update_candidate(inbox, row, status="review_required", reason="; ".join(reasons)[:500], delay_days=7)
            counts["review"] += 1
    if staged:
        AUTO_FILE.write_text(core.render_auto(existing + staged, core.existing_auto_domains()), encoding="utf-8")
    counts["staged"] = len(staged)
    return counts


def finalize(inbox: SupabaseInbox) -> int:
    import json
    catalog = json.loads((ROOT / "jobs.json").read_text(encoding="utf-8"))
    jobs = [job for job in catalog["jobs"] if job.get("candidateKey") and not job.get("excluded")
            and job.get("validationState") == "confirmed"]
    linked = 0
    for job in jobs:
        response = inbox.session.get(inbox._endpoint("jobs"), params={
            "select": "key", "key": f"eq.{job['key']}", "limit": "1",
        }, timeout=30)
        if not response.ok or not any(item.get("key") == job["key"] for item in response.json()):
            raise RuntimeError(f"Vaga API {job['key']} ausente no catálogo sincronizado")
        response = inbox.session.patch(inbox._endpoint("job_candidates"), params={
            "candidate_key": f"eq.{job['candidateKey']}",
            "processing_status": "in.(qualified,review_required,discovered)",
        }, json={"processing_status": "published", "published_job_key": job["key"],
                 "rejection_reason": None, "next_retry_at": None},
            headers={"Prefer": "return=representation"}, timeout=30)
        if not response.ok:
            raise RuntimeError(f"Supabase job_candidates: HTTP {response.status_code}: {response.text[:300]}")
        linked += len(response.json())
    return linked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "finalize"))
    phase = parser.parse_args().phase
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Publicação de candidatos ignorada: Supabase não configurado.")
        return 0
    inbox = SupabaseInbox(url, key)
    if phase == "prepare":
        with requests.Session() as session:
            session.headers["User-Agent"] = core.UA
            print(f"[api] preparação: {prepare(inbox, session)}")
    else:
        print(f"[api] candidatos vinculados ao catálogo: {finalize(inbox)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
