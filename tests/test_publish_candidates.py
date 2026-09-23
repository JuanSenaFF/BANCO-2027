import html
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_catalog
import candidate_pipeline
import publish_candidates as publisher
import update_vagas as collector
import validate_auto
from candidate_pipeline import ApiBrAdapter, Candidate, qualification


OFFICIAL_URL = "https://boards.greenhouse.io/stone/jobs/123456789"
NOW = datetime.now(timezone.utc).isoformat()


class Response:
    def __init__(self, payload=None, text="", status=200):
        self.payload, self.text, self.status_code = payload, text, status
        self.ok = status < 400

    def json(self):
        return self.payload


def posting(*, company="Stone", title="Data Analyst Junior", location="São Paulo", date=NOW):
    description = (
        "<h2>Requisitos</h2><ul><li>Experiência com Python para análise de dados</li>"
        "<li>SQL para consultas e modelagem</li><li>Desenvolvimento de APIs REST</li>"
        "<li>Conhecimento em AWS e Git</li></ul>"
        "<p>Atuação em dados, integração de sistemas e suporte à engenharia de produto em São Paulo.</p>"
    )
    data = {"@context": "https://schema.org", "@type": "JobPosting", "title": title,
            "hiringOrganization": {"name": company}, "datePosted": date,
            "description": description,
            "jobLocation": {"address": {"addressLocality": location, "addressRegion": "SP" if location == "São Paulo" else "PR", "addressCountry": "BR"}}}
    return Response(text=f'<script type="application/ld+json">{html.escape(json.dumps(data, ensure_ascii=False))}</script>')


def candidate_row(**overrides):
    return {
        "candidate_key": "api_br:known", "provider": "api_br",
        "title_raw": "Data Analyst Junior", "company_raw": "Stone",
        "description_raw": "Veja a vaga oficial em " + OFFICIAL_URL,
        "location_raw": "São Paulo", "source_url": "https://github.com/company/vagas/issues/1",
        "apply_url": OFFICIAL_URL, "published_at": NOW,
        "processing_status": "qualified", "attempt_count": 0, "next_retry_at": None,
        **overrides,
    }


class FakeInbox:
    def __init__(self, rows):
        self.rows = {row["candidate_key"]: row.copy() for row in rows}
        self.catalog_keys = set()
        self.session = self

    def _endpoint(self, table):
        return table

    def get(self, table, *, params, timeout):
        if table == "jobs":
            key = params["key"].removeprefix("eq.")
            return Response([{"key": key}] if key in self.catalog_keys else [])
        active = sorted((row for row in self.rows.values()
                         if row["processing_status"] in ("qualified", "review_required", "discovered")),
                        key=lambda row: row["candidate_key"])
        offset, limit = int(params["offset"]), int(params["limit"])
        return Response(active[offset:offset + limit])

    def patch(self, table, *, params, json, headers, timeout):
        key = params["candidate_key"].removeprefix("eq.")
        row = self.rows.get(key)
        if not row or row["processing_status"] not in ("qualified", "review_required", "discovered"):
            return Response([])
        row.update(json)
        return Response([row.copy()] if headers["Prefer"] == "return=representation" else [])


class PublicationTests(unittest.TestCase):
    def test_api_does_not_invent_employer_from_github_organization(self):
        record = {"id": "1", "html_url": "https://github.com/someone/vagas/issues/1",
                  "title": "Data Analyst Junior", "organization": {"name": "vagas"},
                  "body": "Trabalhar com banco de dados SQL e Python"}
        mapped = ApiBrAdapter(None)._map(record)
        self.assertEqual(mapped.company, "")
        evaluation = qualification(mapped)
        self.assertFalse(evaluation["signals"]["finance"])
        self.assertFalse(evaluation["signals"]["priority_company"])
        self.assertEqual(evaluation["status"], "discovered")

    def test_old_publication_is_rejected_in_qualification(self):
        old = (datetime.now(timezone.utc) - timedelta(days=150)).isoformat()
        row = candidate_pipeline.candidate_row(Candidate(
            provider="api_br", external_id="old", source_url="https://example.org/old",
            title="Data Analyst Junior", company="Stone", description="Python e SQL", published_at=old,
        ))
        self.assertEqual(row["processing_status"], "rejected")
        self.assertEqual(row["rejection_reason"], "stale_publication")

    def test_official_link_is_required_and_old_queue_item_is_rejected(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        inbox = FakeInbox([
            candidate_row(candidate_key="old", published_at=old),
            candidate_row(candidate_key="senior", title_raw="Data Analyst Sr."),
            candidate_row(candidate_key="no-link", apply_url=None, description_raw="GitHub issue"),
        ])
        with tempfile.TemporaryDirectory() as directory, patch.multiple(
            publisher, ROOT=Path(directory), AUTO_FILE=Path(directory) / "data-auto.js", BASE_FILES=[],
        ), patch.object(collector, "AUTO_FILE", Path(directory) / "data-auto.js"):
            result = publisher.prepare(inbox, session=object())
            self.assertEqual(result, {"examined": 3, "staged": 0, "rejected": 2, "review": 1})
        self.assertEqual(inbox.rows["old"]["processing_status"], "rejected")
        self.assertEqual(inbox.rows["senior"]["processing_status"], "rejected")
        self.assertEqual(inbox.rows["no-link"]["processing_status"], "review_required")
        self.assertTrue(inbox.rows["no-link"]["next_retry_at"])

    def test_cannot_publish_other_employer_or_other_city(self):
        inbox = FakeInbox([candidate_row()])
        with patch.object(publisher, "safe_fetch", return_value=posting(company="Google")):
            job, reason = publisher.job_from_official(inbox.rows["api_br:known"], OFFICIAL_URL, object())
        self.assertIsNone(job)
        self.assertIn("empresa divergente", reason)
        with patch.object(publisher, "safe_fetch", return_value=posting(location="Curitiba")):
            job, reason = publisher.job_from_official(inbox.rows["api_br:known"], OFFICIAL_URL, object())
        self.assertIsNone(job)
        self.assertIn("local fora", reason)
        unregistered = "https://boards.greenhouse.io/unknown/jobs/123456789"
        with patch.object(publisher, "safe_fetch", return_value=posting()):
            job, reason = publisher.job_from_official(inbox.rows["api_br:known"], unregistered, object())
        self.assertIsNone(job)
        self.assertIn("board não cadastrado", reason)
        redirected = posting()
        redirected.url = "https://outro-site.example/anuncio"
        with patch.object(publisher, "safe_fetch", return_value=redirected):
            job, reason = publisher.job_from_official(inbox.rows["api_br:known"], OFFICIAL_URL, object())
        self.assertIsNone(job)
        self.assertIn("redirecionado", reason)

    def test_full_publication_requires_verified_job_and_synced_foreign_key(self):
        inbox = FakeInbox([candidate_row()])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auto_file = root / "data-auto.js"
            with patch.multiple(publisher, ROOT=root, AUTO_FILE=auto_file, BASE_FILES=[]), patch.object(
                collector, "AUTO_FILE", auto_file,
            ), patch.object(publisher, "safe_fetch", return_value=posting()):
                counts = publisher.prepare(inbox, session=object())
                self.assertEqual(counts, {"examined": 1, "staged": 1, "rejected": 0, "review": 0})
                self.assertEqual(inbox.rows["api_br:known"]["processing_status"], "qualified")
                with patch.multiple(validate_auto, ROOT=root, AUTO_FILE=auto_file, BASE_FILES=[]):
                    validate_auto.main()
                with patch.object(build_catalog, "ROOT", root):
                    catalog = build_catalog.run(online=False)
                self.assertEqual(catalog["meta"]["included"], 1)
                job = catalog["jobs"][0]
                self.assertEqual(job["validationState"], "confirmed")
                self.assertEqual(job["source"], OFFICIAL_URL)
                self.assertIn("https://github.com/company/vagas/issues/1", {x["url"] for x in job["sources"]})
                with self.assertRaisesRegex(RuntimeError, "ausente"):
                    publisher.finalize(inbox)
                self.assertEqual(inbox.rows["api_br:known"]["processing_status"], "qualified")
                inbox.catalog_keys.add(job["key"])
                self.assertEqual(publisher.finalize(inbox), 1)
                self.assertEqual(inbox.rows["api_br:known"]["published_job_key"], job["key"])
                self.assertEqual(inbox.rows["api_br:known"]["processing_status"], "published")
                self.assertEqual(publisher.finalize(inbox), 0)

    def test_workflow_finishes_queue_only_after_catalog_sync(self):
        workflow = (ROOT / ".github/workflows/update-vagas.yml").read_text(encoding="utf-8")
        order = ["candidate_pipeline.py", "publish_candidates.py prepare", "validate_auto.py",
                 "build_catalog.py --verify", "sync_database.py", "publish_candidates.py finalize"]
        self.assertEqual([workflow.index(fragment) for fragment in order],
                         sorted(workflow.index(fragment) for fragment in order))


if __name__ == "__main__":
    unittest.main()
