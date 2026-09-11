import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_catalog import apply_source_preference, reconcile_prior_records
from official_sources import (
    Board,
    collect_official_postings,
    prefer_source,
    same_posting,
    source_metadata,
)
from validate_auto import req_similarity, valid
import update_vagas


class OfficialSourceTests(unittest.TestCase):
    def test_source_authority_separates_official_from_discovery(self):
        greenhouse = source_metadata("https://job-boards.greenhouse.io/stone/jobs/123")
        linkedin = source_metadata("https://www.linkedin.com/jobs/view/123456789")
        aggregator = source_metadata("https://remotar.com.br/job/123")
        company = source_metadata("https://carreiras.itau.com.br/busca-de-vagas/123")
        greenhouse_eu = source_metadata("https://job-boards.eu.greenhouse.io/getnet/jobs/456")
        self.assertTrue(greenhouse["official"])
        self.assertEqual(greenhouse_eu["provider"], "greenhouse")
        self.assertEqual(company["provider"], "company")
        self.assertGreater(company["priority"], greenhouse["priority"])
        self.assertGreater(greenhouse["priority"], linkedin["priority"])
        self.assertGreater(linkedin["priority"], aggregator["priority"])

    def test_greenhouse_adapter_normalizes_public_feed(self):
        board = Board("Stone", "greenhouse", "stone")
        payload = {"jobs": [{
            "id": 7,
            "title": "Analista de Dados Júnior",
            "content": "&lt;h2&gt;Requisitos&lt;/h2&gt;<p>Python</p>",
            "location": {"name": "São Paulo"},
            "updated_at": "2026-09-01T00:00:00Z",
            "absolute_url": "https://job-boards.greenhouse.io/stone/jobs/7",
        }]}
        rows, report = collect_official_postings(lambda _: payload, [board])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["posting"]["hiringOrganization"]["name"], "Stone")
        self.assertIn("<h2>", rows[0]["posting"]["description"])
        self.assertTrue(rows[0]["sourceOfficial"])
        self.assertEqual(report["counts"]["greenhouse"], 1)

    def test_lever_and_ashby_adapters_use_hosted_job_urls(self):
        payloads = {
            "lever": [{
                "text": "Backend Junior",
                "hostedUrl": "https://jobs.lever.co/example/abc",
                "description": "<h2>Requirements</h2><li>Python</li>",
                "categories": {"location": "Remote"},
                "workplaceType": "remote",
            }],
            "ashby": {"jobs": [{
                "title": "Data Analyst I",
                "jobUrl": "https://jobs.ashbyhq.com/example/abc",
                "descriptionHtml": "<h2>Requirements</h2><li>SQL</li>",
                "location": "Brazil",
                "isRemote": True,
                "publishedAt": "2026-09-01T00:00:00Z",
            }]},
        }

        def fetch(url):
            return payloads["lever" if "lever.co" in url else "ashby"]

        rows, report = collect_official_postings(fetch, [
            Board("Pismo", "lever", "pismo"),
            Board("Nubank", "ashby", "nubank"),
        ])
        self.assertEqual({row["provider"] for row in rows}, {"lever", "ashby"})
        self.assertTrue(all(row["posting"]["jobLocationType"] == "TELECOMMUTE" for row in rows))
        self.assertEqual(report["counts"]["boards_ok"], 2)

    def test_board_failure_is_reported_without_stopping_other_boards(self):
        def fetch(url):
            if "broken" in url:
                raise RuntimeError("blocked")
            return {"jobs": []}

        _, report = collect_official_postings(fetch, [
            Board("Broken", "greenhouse", "broken"),
            Board("Empty", "greenhouse", "empty"),
        ])
        self.assertEqual(report["counts"]["boards_failed"], 1)
        self.assertEqual(report["counts"]["boards_ok"], 1)
        self.assertEqual(report["errors"][0]["company"], "Broken")

    def test_admin_title_is_not_admitted_by_incidental_technology_word(self):
        self.assertFalse(update_vagas.is_relevant(
            "Editor & Motion Designer Junior",
            "Banco Inter",
            "Uso eventual de inteligência artificial generativa.",
        ))
        self.assertFalse(update_vagas.is_relevant(
            "Financial Planning Analyst I",
            "Banco Inter",
            "Planejamento financeiro, Excel e consultas simples em SQL.",
        ))

    def test_generic_entry_title_requires_two_strong_technical_signals(self):
        self.assertTrue(update_vagas.is_relevant(
            "Payment Performance Associate",
            "Getnet",
            "Processamento de dados com Python e SQL no setor de pagamentos.",
        ))

    def test_validation_removes_old_false_positive_from_auto_catalog(self):
        ok, reason = valid({
            "company": "Banco Inter",
            "role": "Editor & Motion Designer Junior",
            "requirements": [
                "Ensino superior completo",
                "Experiência com edição de vídeo",
                "Interesse em inteligência artificial generativa",
            ],
            "differentials": [],
            "reason": "Coletada automaticamente em Greenhouse.",
        })
        self.assertFalse(ok)
        self.assertEqual(reason, "cargo fora do recorte técnico")

    def test_catalog_retires_only_invalid_included_automatic_history(self):
        technical = {
            "id": 62,
            "key": "linkedin:4458259681",
            "company": "Sicredi",
            "role": "Analista de Desenvolvimento de Sistemas - Toledo/PR",
            "level": "Júnior / entrada",
            "statusRaw": "Coleta automática — LinkedIn",
            "requirements": ["Python", "SQL", "Integração com APIs REST"],
            "differentials": [],
            "reason": "Coletada automaticamente em LinkedIn.",
            "source": "https://www.linkedin.com/jobs/view/4458259681",
            "auto": True,
            "excluded": False,
        }
        administrative = {
            "id": 70,
            "key": "boards.greenhouse.io/inter/jobs/4713263005",
            "company": "Banco Inter",
            "role": "BACK OFFICE ANALYST I - STOCK OPERATIONS BR",
            "level": "Júnior / entrada",
            "requirements": ["Excel", "Rotinas operacionais", "Comunicação"],
            "differentials": [],
            "reason": "Coletada automaticamente em Greenhouse.",
            "source": "https://boards.greenhouse.io/inter/jobs/4713263005",
            "auto": True,
            "excluded": False,
        }
        already_excluded = {**administrative, "key": "historical:excluded", "id": 71, "excluded": True}
        curated = {**administrative, "key": "historical:curated", "id": 72, "auto": False}

        retained, retired = reconcile_prior_records({
            technical["key"]: technical,
            administrative["key"]: administrative,
            already_excluded["key"]: already_excluded,
            curated["key"]: curated,
        }, [])

        self.assertIn(technical["key"], retained)
        self.assertIn(already_excluded["key"], retained)
        self.assertIn(curated["key"], retained)
        self.assertNotIn(administrative["key"], retained)
        self.assertEqual(retired, [{
            "key": administrative["key"],
            "company": "Banco Inter",
            "role": administrative["role"],
            "reason": "cargo fora do recorte técnico",
        }])

    def test_current_automatic_record_is_not_retired_by_reconciliation(self):
        job = {
            "id": 70,
            "key": "boards.greenhouse.io/inter/jobs/4713263005",
            "company": "Banco Inter",
            "role": "BACK OFFICE ANALYST I - STOCK OPERATIONS BR",
            "requirements": ["Excel", "Rotinas operacionais", "Comunicação"],
            "differentials": [],
            "source": "https://boards.greenhouse.io/inter/jobs/4713263005",
            "auto": True,
            "excluded": False,
        }
        retained, retired = reconcile_prior_records({job["key"]: job}, [job])
        self.assertIn(job["key"], retained)
        self.assertEqual(retired, [])

    def test_official_source_can_supersede_linkedin_for_same_posting(self):
        requirements = ["Python", "SQL", "APIs REST"]
        linkedin = {
            "key": "linkedin:123456789",
            "company": "Stone",
            "role": "Analista de Dados Júnior",
            "requirements": requirements,
            "source": "https://linkedin.com/jobs/view/123456789",
        }
        official = {
            "key": "job-boards.greenhouse.io/stone/jobs/7",
            "company": "Stone",
            "role": "Analista de Dados Junior",
            "requirements": requirements,
            "source": "https://job-boards.greenhouse.io/stone/jobs/7",
        }
        self.assertTrue(same_posting(official, linkedin, req_similarity))
        self.assertTrue(prefer_source(official, linkedin))
        apply_source_preference([linkedin, official])
        self.assertEqual(linkedin["duplicateOf"], official["key"])
        self.assertIn(linkedin["source"], {x["url"] for x in official["sources"]})
        self.assertIn(linkedin["key"], official["sourceAliases"])

    @patch.object(update_vagas, "official_ats_urls", return_value=["official"])
    @patch.object(update_vagas, "gupy_urls", return_value=["gupy"])
    @patch.object(update_vagas, "lever_urls", return_value=["lever"])
    @patch.object(update_vagas, "linkedin_urls", return_value=["linkedin"])
    @patch.object(update_vagas, "other_source_urls", return_value=["aggregator"])
    def test_discovery_orders_official_sources_before_linkedin(self, *_):
        self.assertEqual(
            update_vagas.discover_urls(),
            ["official", "gupy", "lever", "linkedin", "aggregator"],
        )


if __name__ == "__main__":
    unittest.main()
