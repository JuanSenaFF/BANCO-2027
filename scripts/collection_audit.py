"""One terminal outcome for every discovered URL and a bounded candidate memory."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

POLICY_VERSION = "2026-10-06.1"
TERMINAL_STATES = {"accepted", "duplicate", "rejected", "fetch_failed", "retry", "already_known", "not_scanned"}
REJECTION_TTL = timedelta(days=1)
HISTORY_TTL = timedelta(days=180)
BUCKET_BUDGETS = {"official": None, "core": None, "priority": 180, "generic": 140, "aggregator": 40}
BUCKET_ORDER = tuple(BUCKET_BUDGETS)


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    if not p.scheme or not p.netloc:
        return url.strip()
    if p.hostname and (p.hostname == "linkedin.com" or p.hostname.endswith(".linkedin.com")) and "/jobs/view/" in p.path:
        ids = re.findall(r"\d{7,}", p.path)
        if ids:
            return "linkedin:" + ids[-1]
    if p.hostname and p.hostname.endswith(".gupy.io"):
        ids = re.search(r"/jobs?/(\d+)", p.path)
        if ids:
            return p.hostname.lower() + ":" + ids.group(1)
    if p.hostname in {"www.google.com", "google.com"} and p.path.startswith("/about/careers/applications/jobs/results/"):
        return urlunsplit(("https", "www.google.com", p.path.rstrip("/"), "", ""))
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if k.lower() not in
                              {"utm_source", "utm_medium", "utm_campaign", "trk", "trackingid", "jobboardsource"}))
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), query, ""))


class CandidateAudit:
    def __init__(self, path: Path, discovered: list[dict], at: str):
        self.path, self.at = path, at
        try:
            self.history = json.loads(path.read_text(encoding="utf-8")).get("candidates", {})
        except (OSError, ValueError, TypeError):
            self.history = {}
        self.records = {row["url"]: {**row, "canonical_url": canonical_url(row["url"]),
                                      "status": None, "reason": None,
                                      "transitions": [{"stage": "discovered", "reason": "source_discovery"}]} for row in discovered}

    def transition(self, url: str, stage: str, reason: str) -> None:
        if self.records[url]["status"] is not None:
            raise ValueError(f"Transition after terminal outcome: {url}")
        self.records[url]["transitions"].append({"stage": stage, "reason": reason})

    def mark(self, url: str, status: str, reason: str, *, content: str = "", method: str = "") -> None:
        if status not in TERMINAL_STATES:
            raise ValueError(status)
        row = self.records[url]
        if row["status"] is not None:
            raise ValueError(f"Duplicate outcome: {url}")
        row.update(status=status, reason=reason)
        self.records[url]["transitions"].append({"stage": status, "reason": reason})
        if method:
            row["requirements_extraction_method"] = method
        key = row["canonical_url"]
        previous = self.history.get(key, {})
        attempts = previous.get("attempt_count", 0) + int(status not in {"already_known", "not_scanned"} and reason != "recent_rejection")
        self.history[key] = {
            "canonical_url": key, "first_seen_at": previous.get("first_seen_at") or self.at,
            "last_seen_at": self.at, "last_processed_at": self.at if attempts > previous.get("attempt_count", 0) else previous.get("last_processed_at"),
            "status": status, "reason": previous.get("reason", reason) if reason == "recent_rejection" else reason,
            "content_hash": hashlib.sha256(content.encode()).hexdigest() if content else previous.get("content_hash"),
            "retry_after": previous.get("retry_after") if reason == "recent_rejection" else (
                (datetime.fromisoformat(self.at.replace("Z", "+00:00")) + REJECTION_TTL).isoformat()
                if status == "rejected" else None),
            "attempt_count": attempts, "policy_version": POLICY_VERSION,
            "source": row["source"], "requirements_extraction_method": method or previous.get("requirements_extraction_method"),
            "company": row.get("company") or previous.get("company"),
            "role": row.get("role") or previous.get("role"),
        }

    def recent_rejection(self, url: str) -> bool:
        previous = self.history.get(canonical_url(url), {})
        try:
            retry_after = datetime.fromisoformat(previous["retry_after"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            return False
        return (previous.get("status") == "rejected" and previous.get("policy_version") == POLICY_VERSION
                and retry_after > datetime.fromisoformat(self.at.replace("Z", "+00:00")))

    def finish(self, *, scheduled: int, scanned: int) -> dict:
        missing = [url for url, row in self.records.items() if row["status"] is None]
        if missing:
            raise AssertionError(f"Missing terminal outcomes for {len(missing)} URLs")
        counts = dict(Counter(row["status"] for row in self.records.values()))
        if sum(counts.values()) != len(self.records):
            raise AssertionError("Candidate funnel does not reconcile")
        cutoff = (datetime.fromisoformat(self.at.replace("Z", "+00:00")) - HISTORY_TTL).isoformat()
        self.history = {k: v for k, v in self.history.items() if v.get("last_seen_at", "") >= cutoff}
        self.path.write_text(json.dumps({"version": 1, "candidates": self.history}, ensure_ascii=False), encoding="utf-8")
        sources = defaultdict(Counter)
        durations = defaultdict(list)
        for row in self.records.values():
            sources[row["source"]][row["status"]] += 1
            if "fetchMs" in row:
                durations[row["source"]].append(row["fetchMs"])
        return {
            "discovered": len(self.records), "scheduled_for_scan": scheduled, "scanned": scanned,
            "not_scanned": counts.get("not_scanned", 0), "outcomes": counts,
            "reasons": dict(Counter(row["reason"] for row in self.records.values())),
            "sourceFunnel": {k: {**dict(v), "discovered": sum(v.values()),
                                 "scanned": len(durations[k]), "qualified": v.get("accepted", 0),
                                 "conversionPct": round(100 * v.get("accepted", 0) / max(1, len(durations[k])), 1),
                                 "averageFetchMs": round(sum(durations[k]) / len(durations[k])) if durations[k] else None}
                             for k, v in sources.items()},
            "candidates": list(self.records.values()),
            "stageDefinitions": {"discovered": "URL found by a source", "scheduled": "fetch budget reserved",
                                 "parsed": "title and company extracted", "qualified": "quality filters passed",
                                 "accepted": "added to the automatic input", "validated": "kept by catalog validator",
                                 "confirmed_active": "official live evidence checked", "published": "included in public catalog"},
        }


def schedule(rows: list[dict], audit: CandidateAudit, known: set[str], allowed) -> list[str]:
    ordered = sorted(rows, key=lambda row: BUCKET_ORDER.index(row["bucket"]))
    budget_used = Counter()
    selected = []
    seen_keys = set()
    for row in ordered:
        url, bucket = row["url"], row["bucket"]
        if canonical_url(url) in known:
            audit.mark(url, "already_known", "url_already_known")
        elif canonical_url(url) in seen_keys:
            audit.mark(url, "duplicate", "duplicate_url")
        elif not allowed(url):
            audit.mark(url, "rejected", "unsupported_source")
        elif audit.recent_rejection(url):
            audit.mark(url, "rejected", "recent_rejection")
        elif BUCKET_BUDGETS[bucket] is not None and budget_used[bucket] >= BUCKET_BUDGETS[bucket]:
            audit.mark(url, "not_scanned", "source_budget_exhausted")
        else:
            selected.append(url)
            budget_used[bucket] += 1
            seen_keys.add(canonical_url(url))
            audit.transition(url, "scheduled", "source_budget_reserved")
    return selected
