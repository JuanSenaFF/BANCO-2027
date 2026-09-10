"""Official job-source adapters and provenance rules for BANCO 2027.

LinkedIn is useful for discovery, but an employer career page or a public ATS
feed is the stronger source of truth.  This module keeps that distinction out
of the collector's parsing code and makes source preference deterministic.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable
from urllib.parse import urlparse


@dataclass(frozen=True)
class Board:
    company: str
    provider: str
    token: str
    region: str = "global"


# Only boards verified against their public endpoint are enabled.  Adding a
# company is data-only: no collector change is required.
OFFICIAL_BOARDS = (
    Board("Stone", "greenhouse", "stone"),
    Board("Banco Inter", "greenhouse", "inter"),
    Board("Getnet", "greenhouse", "getnet"),
    Board("Nubank", "ashby", "nubank"),
)


PROVIDER_LABELS = {
    "company": "Página oficial",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "gupy": "Gupy",
    "jobposting": "Página oficial",
    "linkedin": "LinkedIn",
    "aggregator": "Agregador",
    "unknown": "Fonte não classificada",
}

PROVIDER_PRIORITY = {
    "company": 5,
    "greenhouse": 4,
    "lever": 4,
    "ashby": 4,
    "gupy": 4,
    "jobposting": 3,
    "linkedin": 1,
    "aggregator": 0,
    "unknown": 0,
}

OFFICIAL_COMPANY_HOSTS = {
    "carreiras.itau.com.br",
    "santander-brasil.interviewhr.com",
    "fitbank.vagas.solides.com.br",
}


def _norm(value: Any) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def provider_for_url(url: str, *, structured: bool = False) -> str:
    host = urlparse(str(url or "")).netloc.lower().removeprefix("www.")
    if host in OFFICIAL_COMPANY_HOSTS:
        return "company"
    if host.endswith("linkedin.com"):
        return "linkedin"
    if host.endswith("greenhouse.io") and (host.startswith("boards") or host.startswith("job-boards")):
        return "greenhouse"
    if host in {"api.lever.co", "api.eu.lever.co", "jobs.lever.co", "jobs.eu.lever.co"}:
        return "lever"
    if host in {"api.ashbyhq.com", "jobs.ashbyhq.com"}:
        return "ashby"
    if host.endswith("gupy.io"):
        return "gupy"
    if host in {"remotar.com.br", "querovagastech.com.br"}:
        return "aggregator"
    if structured and host:
        return "jobposting"
    return "unknown"


def source_metadata(url: str, *, structured: bool = False) -> dict[str, Any]:
    provider = provider_for_url(url, structured=structured)
    priority = PROVIDER_PRIORITY[provider]
    return {
        "name": PROVIDER_LABELS[provider],
        "provider": provider,
        "official": priority >= 3,
        "priority": priority,
    }


def source_priority(job: dict) -> int:
    explicit = job.get("sourcePriority")
    if isinstance(explicit, int):
        return explicit
    return source_metadata(
        job.get("source", ""),
        structured=bool(job.get("sourceStructured")),
    )["priority"]


def prefer_source(candidate: dict, current: dict) -> bool:
    """Return True when candidate is a stronger source for the same posting."""
    candidate_rank = source_priority(candidate)
    current_rank = source_priority(current)
    if candidate_rank != current_rank:
        return candidate_rank > current_rank
    candidate_verified = bool(candidate.get("lastVerifiedAt"))
    current_verified = bool(current.get("lastVerifiedAt"))
    return candidate_verified and not current_verified


def same_posting(a: dict, b: dict, requirement_similarity: Callable[[list[str], list[str]], float]) -> bool:
    """Conservative cross-source identity match used only for source promotion."""
    company_a, company_b = _norm(a.get("company")), _norm(b.get("company"))
    if not company_a or not company_b:
        return False
    if company_a != company_b and company_a not in company_b and company_b not in company_a:
        aliases = ({"banco inter", "inter"}, {"xp", "xp inc"}, {"itau", "itau unibanco"})
        if not any(company_a in group and company_b in group for group in aliases):
            return False
    title_a = set(_norm(a.get("role")).split())
    title_b = set(_norm(b.get("role")).split())
    title_score = len(title_a & title_b) / len(title_a | title_b) if title_a and title_b else 0
    req_score = requirement_similarity(a.get("requirements", []), b.get("requirements", []))
    return title_score >= 0.72 and req_score >= 0.45


def merge_source_records(*jobs: dict) -> list[dict]:
    """Preserve source lineage while keeping the preferred URL first."""
    by_url: dict[str, dict] = {}
    for job in jobs:
        candidates = list(job.get("sources") or [])
        if job.get("source"):
            meta = source_metadata(
                job["source"],
                structured=bool(job.get("sourceStructured")),
            )
            candidates.append({
                "url": job["source"],
                "name": job.get("sourceName") or meta["name"],
                "provider": job.get("sourceProvider") or meta["provider"],
                "official": job.get("sourceOfficial", meta["official"]),
                "priority": job.get("sourcePriority", meta["priority"]),
            })
        for record in candidates:
            url = str(record.get("url") or "").strip()
            if not url:
                continue
            previous = by_url.get(url, {})
            by_url[url] = {**previous, **record, "url": url}
    return sorted(by_url.values(), key=lambda x: (-int(x.get("priority", 0)), x["url"]))


def _location(name: str | None) -> dict:
    return {"address": {"addressLocality": name}} if name else {}


def _greenhouse(board: Board, payload: Any) -> Iterable[dict]:
    for job in (payload or {}).get("jobs", []):
        url = job.get("absolute_url")
        if not url:
            continue
        yield {
            "url": url,
            "posting": {
                "@type": "JobPosting",
                "title": job.get("title"),
                "description": html.unescape(str(job.get("content") or "")),
                "hiringOrganization": {"name": board.company},
                "jobLocation": _location((job.get("location") or {}).get("name")),
                "datePosted": job.get("first_published") or job.get("updated_at"),
                "validThrough": job.get("application_deadline"),
            },
        }


def _lever(board: Board, payload: Any) -> Iterable[dict]:
    for job in payload if isinstance(payload, list) else []:
        url = job.get("hostedUrl")
        if not url:
            continue
        categories = job.get("categories") or {}
        workplace = job.get("workplaceType")
        yield {
            "url": url,
            "posting": {
                "@type": "JobPosting",
                "title": job.get("text"),
                "description": job.get("description") or job.get("descriptionPlain") or "",
                "hiringOrganization": {"name": board.company},
                "jobLocation": _location(categories.get("location")),
                "jobLocationType": "TELECOMMUTE" if workplace == "remote" else None,
            },
        }


def _ashby(board: Board, payload: Any) -> Iterable[dict]:
    for job in (payload or {}).get("jobs", []):
        url = job.get("jobUrl")
        if not url:
            continue
        yield {
            "url": url,
            "posting": {
                "@type": "JobPosting",
                "title": job.get("title"),
                "description": job.get("descriptionHtml") or job.get("descriptionPlain") or "",
                "hiringOrganization": {"name": board.company},
                "jobLocation": _location(job.get("location")),
                "jobLocationType": "TELECOMMUTE" if job.get("isRemote") else None,
                "datePosted": job.get("publishedAt"),
            },
        }


def board_endpoint(board: Board) -> str:
    if board.provider == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{board.token}/jobs?content=true"
    if board.provider == "lever":
        host = "api.eu.lever.co" if board.region == "eu" else "api.lever.co"
        return f"https://{host}/v0/postings/{board.token}?mode=json"
    if board.provider == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{board.token}"
    raise ValueError(f"Provedor oficial não suportado: {board.provider}")


ADAPTERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


def collect_official_postings(
    fetch_json: Callable[[str], Any],
    boards: Iterable[Board] = OFFICIAL_BOARDS,
) -> tuple[list[dict], dict]:
    """Fetch enabled public ATS boards and return normalized posting candidates."""
    candidates: list[dict] = []
    stats = Counter()
    errors: list[dict] = []
    for board in boards:
        endpoint = board_endpoint(board)
        try:
            payload = fetch_json(endpoint)
            rows = list(ADAPTERS[board.provider](board, payload))
            for row in rows:
                row.update({
                    "company": board.company,
                    "provider": board.provider,
                    "sourceName": PROVIDER_LABELS[board.provider],
                    "sourceOfficial": True,
                    "sourcePriority": PROVIDER_PRIORITY[board.provider],
                    "sourceStructured": True,
                })
            candidates.extend(rows)
            stats[board.provider] += len(rows)
            stats["boards_ok"] += 1
            stats["official"] += len(rows)
        except Exception as exc:
            stats["boards_failed"] += 1
            errors.append({"company": board.company, "provider": board.provider, "error": type(exc).__name__})
    return candidates, {"counts": dict(stats), "errors": errors}
