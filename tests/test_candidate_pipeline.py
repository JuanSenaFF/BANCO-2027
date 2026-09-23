import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from candidate_pipeline import (  # noqa: E402
    AdzunaAdapter,
    ApiBrAdapter,
    Candidate,
    JoobleAdapter,
    SupabaseInbox,
    candidate_row,
)


class FakeResponse:
    def __init__(self, payload=None, status=200, text=""):
        self.payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = text

    def json(self):
        return self.payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeCollectionSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.pages.pop(0))


class FakeSupabaseSession:
    def __init__(self):
        self.headers = {}
        self.posts = []
        self.patches = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({})

    def patch(self, url, **kwargs):
        self.patches.append((url, kwargs))
        return FakeResponse({})


class CandidateQualificationTests(unittest.TestCase):
    def test_priority_bank_junior_technology_role_is_qualified(self):
        row = candidate_row(Candidate(
            provider="api_br", external_id="1", source_url="https://example.test/1",
            title="Analista de Tecnologia Júnior", company="Itaú", location="São Paulo",
            description="Atuação com APIs e Python.", raw={"id": 1},
        ))
        self.assertEqual(row["processing_status"], "qualified")
        self.assertGreaterEqual(row["qualification"]["confidence"], 0.8)

    def test_non_financial_priority_tech_companies_are_qualified(self):
        for company in ("Microsoft", "Google"):
            with self.subTest(company=company):
                row = candidate_row(Candidate(
                    provider="api_br", external_id=company.lower(),
                    source_url=f"https://example.test/{company.lower()}",
                    title="Software Engineer Junior", company=company,
                    description="Desenvolvimento de APIs e serviços cloud.", raw={"company": company},
                ))
                self.assertEqual(row["processing_status"], "qualified")
                self.assertTrue(row["qualification"]["signals"]["priority_company"])
                self.assertTrue(row["qualification"]["signals"]["target_context"])
                self.assertFalse(row["qualification"]["signals"]["finance"])
                self.assertIn("priority_company", row["qualification"]["reasons"])

    def test_senior_title_is_rejected_even_if_body_mentions_junior(self):
        row = candidate_row(Candidate(
            provider="api_br", external_id="2", source_url="https://example.test/2",
            title="Engenheiro de Software Sênior", company="Banco Inter",
            description="Mentoria para desenvolvedores junior; Java e APIs.", raw={"id": 2},
        ))
        self.assertEqual(row["processing_status"], "rejected")
        self.assertEqual(row["rejection_reason"], "seniority_conflict_in_title")

    def test_weak_aggregator_result_is_retained_as_discovered(self):
        row = candidate_row(Candidate(
            provider="api_br", external_id="3", source_url="https://example.test/3",
            title="Assistente administrativo", description="Vaga geral.", raw={"id": 3},
        ))
        self.assertEqual(row["processing_status"], "discovered")


class AdapterTests(unittest.TestCase):
    def test_api_br_paginates_and_deduplicates_before_persistence(self):
        first_page = [{
            "id": str(index), "title": "Dev Júnior", "html_url": f"https://github.test/{index}",
            "organization": {"name": "Banco Inter"}, "body": "Java API",
        } for index in range(100)]
        second_page = [first_page[0], {
            "id": "100", "title": "Dados Júnior", "html_url": "https://github.test/100",
            "company": "Itaú", "body": "Python SQL",
        }]
        session = FakeCollectionSession([{"data": first_page}, {"data": second_page}])
        result = ApiBrAdapter(session, terms=("junior",), max_pages=5).collect()
        self.assertEqual(result.request_count, 2)
        self.assertEqual(len(result.candidates), 101)
        self.assertEqual(result.candidates[0].company, "Banco Inter")

    def test_keyed_adapters_skip_without_spending_requests(self):
        session = FakeCollectionSession([])
        adzuna = AdzunaAdapter(session, "", "", ("junior",)).collect()
        jooble = JoobleAdapter(session, "", ("junior",)).collect()
        self.assertEqual(adzuna.skipped_reason, "credentials_missing")
        self.assertEqual(jooble.skipped_reason, "credentials_missing")
        self.assertEqual(session.calls, [])


class PersistenceTests(unittest.TestCase):
    def test_supabase_upsert_and_run_audit_are_written(self):
        session = FakeSupabaseSession()
        inbox = SupabaseInbox("https://project.supabase.co", "secret", session=session)
        candidate = Candidate(
            provider="api_br", external_id="9", source_url="https://example.test/9",
            title="Analista de Dados Júnior", company="Nubank", description="SQL e Python", raw={"id": 9},
        )
        from candidate_pipeline import CollectionResult
        count = inbox.persist(CollectionResult("api_br", [candidate], request_count=1), "2026-09-16T12:00:00+00:00")
        self.assertEqual(count, 1)
        tables = [url.rsplit("/", 1)[-1] for url, _ in session.posts]
        self.assertEqual(tables, ["job_candidates", "source_runs"])
        self.assertEqual(len(session.patches), 1)
        candidate_request = session.posts[0][1]
        self.assertIn("resolution=merge-duplicates", candidate_request["headers"]["Prefer"])


if __name__ == "__main__":
    unittest.main()
