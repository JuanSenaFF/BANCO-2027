"""Persist job discoveries before they enter the public BANCO 2027 catalog.

Aggregators are discovery signals, never automatic publication authorities. The
script is deliberately a no-op without Supabase credentials so a successful
network request can never be mistaken for a persisted candidate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


USER_AGENT = "Banco2027JobRadar/2.0 (+https://github.com/JuanSenaFF/BANCO-2027)"
TIMEOUT = 25
PRIORITY_COMPANIES = (
    "itau", "bradesco", "santander", "btg pactual", "nubank", "banco inter", "c6 bank",
    "xp", "safra", "mercado pago", "stone", "pagbank", "b3", "nuclea", "cerc", "cielo",
    "rede", "getnet", "dock", "pismo", "banco bv", "daycoval", "banco abc brasil",
    "banco pan", "banco bmg", "neon", "picpay", "creditas", "will bank", "sicredi",
    "sicoob", "sinqia", "matera", "fitbank", "agibank", "ebanx", "cloudwalk", "asaas",
    "celcoin", "qi tech", "stark bank", "conta simples", "recargapay", "zoop", "vindi",
    "fiserv", "microsoft", "google",
)
JUNIOR_TERMS = ("junior", " jr", "estagio", "estagiario", "trainee", "intern", "entry level", "analista i")
SENIOR_TERMS = ("senior", " sr", "pleno", "especialista", "specialist", "lead", "principal", "staff", "gerente")
TECH_TERMS = (
    "software", "desenvolv", "developer", "backend", "front-end", "frontend", "dados", "data ",
    "cloud", "sre", "devops", "sistemas", "tecnologia", "infraestrutura", "security", "seguranca",
    "python", "java", "sql", "api", "qa", "automacao", "engenheir",
)
FINANCE_TERMS = (
    "banco", "bancario", "fintech", "financeir", "pagamento", "credito", "risco", "fraude",
    "open finance", "mercado de capitais", "investimento",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def resilient_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET", "POST")),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session


def first(record: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", []):
            return value
    return default


def nested_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(first(value, "display_name", "name", "title"))
    return str(value or "")


@dataclass
class Candidate:
    provider: str
    external_id: str
    source_url: str
    title: str
    company: str = ""
    location: str = ""
    description: str = ""
    apply_url: str = ""
    published_at: str | None = None
    source_updated_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def candidate_key(self) -> str:
        identity = self.external_id or self.source_url
        return f"{self.provider}:{stable_hash(identity)[:32]}"

    @property
    def dedupe_key(self) -> str:
        value = "|".join((normalized(self.company), normalized(self.title), normalized(self.location)))
        return stable_hash(value)


@dataclass
class CollectionResult:
    source_id: str
    candidates: list[Candidate] = field(default_factory=list)
    request_count: int = 0
    errors: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


def qualification(candidate: Candidate) -> dict[str, Any]:
    title = normalized(candidate.title)
    body = normalized(candidate.description)
    company = normalized(candidate.company)
    combined = f"{title} {body}"
    junior_title = any(term in f" {title}" for term in JUNIOR_TERMS)
    junior_body = any(term in f" {body}" for term in JUNIOR_TERMS)
    senior_title = any(term in f" {title}" for term in SENIOR_TERMS)
    technology = any(term in combined for term in TECH_TERMS)
    priority_company = any(term == company or term in company for term in PRIORITY_COMPANIES)
    finance_context = any(term in combined for term in FINANCE_TERMS)
    target_context = priority_company or finance_context

    reasons: list[str] = []
    if senior_title:
        status, confidence = "rejected", 0.05
        reasons.append("seniority_conflict_in_title")
    elif junior_title and technology and target_context:
        status, confidence = "qualified", 0.9 if priority_company else 0.78
        reasons.extend(("entry_level_title", "technology_signal"))
        reasons.append("priority_company" if priority_company else "financial_context")
    elif technology and target_context and (junior_title or junior_body):
        status, confidence = "review_required", 0.6
        reasons.extend(("entry_level_signal", "technology_signal"))
        reasons.append("priority_company" if priority_company else "financial_context")
    elif technology and priority_company:
        status, confidence = "review_required", 0.5
        reasons.extend(("priority_company", "technology_signal", "seniority_not_confirmed"))
    else:
        status, confidence = "discovered", 0.25
        reasons.append("insufficient_evidence")
    return {
        "status": status,
        "confidence": confidence,
        "signals": {
            "junior_title": junior_title,
            "junior_body": junior_body,
            "senior_title": senior_title,
            "technology": technology,
            "finance": finance_context,
            "target_context": target_context,
            "priority_company": priority_company,
        },
        "reasons": reasons,
        "qualified_at": utcnow(),
        "policy_version": "2026-09-16.1",
    }


def candidate_row(candidate: Candidate) -> dict[str, Any]:
    evaluation = qualification(candidate)
    now = utcnow()
    return {
        "candidate_key": candidate.candidate_key,
        "provider": candidate.provider,
        "external_id": candidate.external_id or None,
        "source_url": candidate.source_url,
        "apply_url": candidate.apply_url or None,
        "title_raw": candidate.title,
        "company_raw": candidate.company,
        "location_raw": candidate.location,
        "description_raw": candidate.description,
        "published_at": candidate.published_at,
        "source_updated_at": candidate.source_updated_at,
        "last_discovered_at": now,
        "processing_status": evaluation["status"],
        "payload_hash": stable_hash(candidate.raw),
        "dedupe_key": candidate.dedupe_key,
        "qualification": evaluation,
        "raw_payload": candidate.raw,
        "rejection_reason": "seniority_conflict_in_title" if evaluation["status"] == "rejected" else None,
    }


class ApiBrAdapter:
    source_id = "api_br"
    provider = "api_br"
    endpoint = "https://apibr.com/vagas/api/v2/issues"

    def __init__(self, session: requests.Session, terms: Iterable[str] = ("junior", "estagio"), max_pages: int = 5):
        self.session = session
        self.terms = tuple(terms)
        self.max_pages = max_pages

    def collect(self) -> CollectionResult:
        result = CollectionResult(self.source_id)
        seen: set[str] = set()
        for term in self.terms:
            for page in range(1, self.max_pages + 1):
                try:
                    response = self.session.get(
                        self.endpoint,
                        params={"page": page, "per_page": 100, "term": term, "includeBody": "true"},
                        timeout=TIMEOUT,
                    )
                    result.request_count += 1
                    response.raise_for_status()
                    payload = response.json()
                    records = payload if isinstance(payload, list) else first(payload, "data", "results", "items", "issues", default=[])
                    if not isinstance(records, list):
                        raise ValueError("resposta sem lista de vagas")
                    for record in records:
                        candidate = self._map(record)
                        if candidate.candidate_key not in seen:
                            seen.add(candidate.candidate_key)
                            result.candidates.append(candidate)
                    if len(records) < 100:
                        break
                    if page == self.max_pages:
                        result.errors.append(f"term={term}: pagination_limit_reached={self.max_pages}")
                except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError) as exc:
                    result.errors.append(f"term={term} page={page}: {exc}")
                    break
        return result

    def _map(self, record: dict[str, Any]) -> Candidate:
        external_id = str(first(record, "id", "number", "issueId", "node_id"))
        url = str(first(record, "html_url", "url", "issueUrl", "sourceUrl"))
        repository = first(record, "repository", "organization", "owner")
        return Candidate(
            provider=self.provider,
            external_id=external_id or url,
            source_url=url,
            apply_url=str(first(record, "applyUrl", "apply_url")),
            title=str(first(record, "title", "name")),
            company=nested_name(first(record, "company", "organization", default=repository)),
            location=str(first(record, "location", "local")),
            description=str(first(record, "body", "description")),
            published_at=first(record, "created_at", "createdAt", "published_at", default=None),
            source_updated_at=first(record, "updated_at", "updatedAt", default=None),
            raw=record,
        )


class AdzunaAdapter:
    source_id = "adzuna_br"
    provider = "adzuna"
    endpoint = "https://api.adzuna.com/v1/api/jobs/br/search/{page}"

    def __init__(self, session: requests.Session, app_id: str, app_key: str, queries: Iterable[str], max_pages: int = 1):
        self.session, self.app_id, self.app_key = session, app_id, app_key
        self.queries, self.max_pages = tuple(queries), max_pages

    def collect(self) -> CollectionResult:
        if not self.app_id or not self.app_key:
            return CollectionResult(self.source_id, skipped_reason="credentials_missing")
        result = CollectionResult(self.source_id)
        seen: set[str] = set()
        for query in self.queries:
            for page in range(1, self.max_pages + 1):
                try:
                    response = self.session.get(self.endpoint.format(page=page), params={
                        "app_id": self.app_id, "app_key": self.app_key, "what": query,
                        "results_per_page": 20, "content-type": "application/json",
                    }, timeout=TIMEOUT)
                    result.request_count += 1
                    response.raise_for_status()
                    records = response.json().get("results", [])
                    for record in records:
                        candidate = self._map(record)
                        if candidate.candidate_key not in seen:
                            seen.add(candidate.candidate_key)
                            result.candidates.append(candidate)
                    if len(records) < 20:
                        break
                except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError) as exc:
                    result.errors.append(f"query={query} page={page}: {exc}")
                    break
        return result

    def _map(self, record: dict[str, Any]) -> Candidate:
        return Candidate(
            provider=self.provider,
            external_id=str(first(record, "id", "redirect_url")),
            source_url=str(first(record, "redirect_url", "url")),
            title=str(first(record, "title")),
            company=nested_name(first(record, "company")),
            location=nested_name(first(record, "location")),
            description=str(first(record, "description")),
            published_at=first(record, "created", default=None),
            raw=record,
        )


class JoobleAdapter:
    source_id = "jooble_br"
    provider = "jooble"

    def __init__(self, session: requests.Session, api_key: str, queries: Iterable[str]):
        self.session, self.api_key, self.queries = session, api_key, tuple(queries)

    def collect(self) -> CollectionResult:
        if not self.api_key:
            return CollectionResult(self.source_id, skipped_reason="credentials_missing")
        result = CollectionResult(self.source_id)
        seen: set[str] = set()
        for query in self.queries:
            try:
                response = self.session.post(
                    f"https://br.jooble.org/api/{self.api_key}",
                    json={"keywords": query, "location": "Brasil", "page": 1}, timeout=TIMEOUT,
                )
                result.request_count += 1
                response.raise_for_status()
                records = response.json().get("jobs", [])
                for record in records:
                    candidate = self._map(record)
                    if candidate.candidate_key not in seen:
                        seen.add(candidate.candidate_key)
                        result.candidates.append(candidate)
            except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError) as exc:
                result.errors.append(f"query={query}: {exc}")
        return result

    def _map(self, record: dict[str, Any]) -> Candidate:
        return Candidate(
            provider=self.provider,
            external_id=str(first(record, "id", "link")),
            source_url=str(first(record, "link", "url")),
            title=str(first(record, "title")),
            company=str(first(record, "company")),
            location=str(first(record, "location")),
            description=str(first(record, "snippet", "description")),
            published_at=first(record, "updated", default=None),
            raw=record,
        )


class SupabaseInbox:
    def __init__(self, url: str, service_key: str, session: requests.Session | None = None):
        self.url = url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        })

    def _endpoint(self, table: str) -> str:
        return f"{self.url}/rest/v1/{table}"

    def post(self, table: str, rows: list[dict[str, Any]], *, upsert: bool = False) -> None:
        if not rows:
            return
        headers = {"Prefer": "resolution=merge-duplicates,return=minimal"} if upsert else {"Prefer": "return=minimal"}
        for start in range(0, len(rows), 200):
            response = self.session.post(self._endpoint(table), json=rows[start:start + 200], headers=headers, timeout=TIMEOUT)
            if not response.ok:
                raise RuntimeError(f"Supabase {table}: HTTP {response.status_code}: {response.text[:300]}")

    def persist(self, result: CollectionResult, started_at: str) -> int:
        rows = [candidate_row(candidate) for candidate in result.candidates if candidate.source_url]
        self.post("job_candidates", rows, upsert=True)
        if result.skipped_reason:
            status = "skipped"
        elif result.errors and not rows:
            status = "failed"
        elif result.errors:
            status = "partial"
        else:
            status = "success"
        self.post("source_runs", [{
            "source_id": result.source_id,
            "started_at": started_at,
            "finished_at": utcnow(),
            "status": status,
            "request_count": result.request_count,
            "discovered_count": len(result.candidates),
            "persisted_count": len(rows),
            "error_count": len(result.errors),
            "error": " | ".join(result.errors)[:2000] or result.skipped_reason,
        }])
        health = "credentials_missing" if result.skipped_reason == "credentials_missing" else (
            "unavailable" if status == "failed" else "degraded" if status == "partial" else "healthy"
        )
        registry = {
            "id": result.source_id,
            "enabled": result.skipped_reason is None,
            "health_status": health,
            "last_error": " | ".join(result.errors)[:2000] or result.skipped_reason,
            "updated_at": utcnow(),
        }
        if status == "success":
            registry.update({"last_success_at": utcnow(), "consecutive_failures": 0})
        elif status in ("failed", "partial"):
            registry["last_failure_at"] = utcnow()
        response = self.session.patch(
            self._endpoint("source_registry"), params={"id": f"eq.{result.source_id}"},
            json=registry, headers={"Prefer": "return=minimal"}, timeout=TIMEOUT,
        )
        if not response.ok:
            raise RuntimeError(f"Supabase source_registry: HTTP {response.status_code}: {response.text[:300]}")
        return len(rows)


def csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, default).split(",") if value.strip())


def main() -> int:
    supabase_url = os.getenv("SUPABASE_URL", "")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_key:
        print("Caixa de entrada não configurada: coleta externa ignorada para não perder resultados.")
        return 0

    session = resilient_session()
    adapters = [
        ApiBrAdapter(session, csv_env("API_BR_TERMS", "junior,estagio"), int(os.getenv("API_BR_MAX_PAGES", "10"))),
        AdzunaAdapter(session, os.getenv("ADZUNA_APP_ID", ""), os.getenv("ADZUNA_APP_KEY", ""),
                      csv_env("ADZUNA_QUERIES", "tecnologia junior banco,dados junior fintech"),
                      int(os.getenv("ADZUNA_MAX_PAGES", "1"))),
        JoobleAdapter(session, os.getenv("JOOBLE_API_KEY", ""),
                      csv_env("JOOBLE_QUERIES", "tecnologia junior banco")),
    ]
    inbox = SupabaseInbox(supabase_url, service_key)
    failures = 0
    for adapter in adapters:
        started_at = utcnow()
        result = adapter.collect()
        try:
            persisted = inbox.persist(result, started_at)
            print(f"[{result.source_id}] requests={result.request_count} encontrados={len(result.candidates)} persistidos={persisted} erros={len(result.errors)}")
        except RuntimeError as exc:
            failures += 1
            print(f"[{result.source_id}] falha de persistência: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
