import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import company_policy as policy
import update_vagas as collector
import update_vagas_v2 as enhanced
import validate_auto as validator
from candidate_pipeline import Candidate, qualification


def vacancy(company, **overrides):
    return {
        "company": company,
        "role": "Software Engineer Junior",
        "level": "Júnior / entrada",
        "requirements": ["Python para desenvolvimento", "SQL para consultas", "APIs REST"],
        "differentials": [],
        "location": "São Paulo, Brasil",
        "modality": "Híbrido",
        "source": "https://www.linkedin.com/jobs/view/9876543210",
        **overrides,
    }


def evaluate_candidate(company):
    job = vacancy(company)
    return qualification(Candidate(
        provider="api_br", external_id="fixture", source_url=job["source"],
        title=job["role"], company=company, location=job["location"],
        description=" ".join(job["requirements"]),
    ))


class CompanyPolicyTests(unittest.TestCase):
    def test_all_stages_share_the_same_company_rule(self):
        self.assertIs(collector.approved_company, policy.is_target_company)
        self.assertIs(enhanced.enhanced_approved_company, policy.is_target_company)
        self.assertIs(validator.company_approved, policy.is_target_company)
        self.assertIs(collector.contextual_company, validator.company_contextual)

    def test_all_registered_names_and_aliases_pass_every_stage(self):
        for company in policy.TARGET_COMPANIES:
            with self.subTest(company=company):
                job = vacancy(company)
                self.assertTrue(collector.is_relevant(job["role"], company, " ".join(job["requirements"])))
                self.assertEqual(validator.valid(job), (True, "ok"))
                evaluation = evaluate_candidate(company)
                self.assertEqual(evaluation["status"], "qualified")
                self.assertTrue(evaluation["signals"]["priority_company"])

    def test_technology_targets_do_not_need_financial_context(self):
        for company in ("Microsoft", "Microsoft Brasil", "Google", "Google Brasil", "Google LLC"):
            with self.subTest(company=company):
                job = vacancy(company)
                self.assertFalse(validator.finance_context(job))
                self.assertEqual(validator.valid(job), (True, "ok"))
                evaluation = evaluate_candidate(company)
                self.assertFalse(evaluation["signals"]["finance"])
                self.assertTrue(evaluation["signals"]["target_context"])

    def test_case_accents_html_and_punctuation_are_normalized(self):
        for company in ("  ITAU UNIBANCO  ", "Ita&uacute;", "<b>Microsoft</b>", "Google, LLC.", "XP INC", "Nuclea"):
            with self.subTest(company=company):
                self.assertTrue(policy.is_target_company(company))

    def test_substrings_and_unregistered_partners_are_not_company_matches(self):
        for company in ("", " ", None, "ClearSale", "Experian", "Intercontinental", "Microsoft Partner", "Google Partners", "Google Cloud Partner", "Banco Intercontinental", "Nubank Parceiros"):
            with self.subTest(company=company):
                self.assertFalse(policy.is_target_company(company))
                evaluation = evaluate_candidate(company)
                self.assertFalse(evaluation["signals"]["priority_company"])
                self.assertEqual(evaluation["status"], "discovered")
                self.assertFalse(validator.valid(vacancy(company))[0])

    def test_consultancies_still_require_financial_context(self):
        for company in policy.CONTEXT_COMPANIES:
            with self.subTest(company=company):
                job = vacancy(company)
                self.assertTrue(policy.is_contextual_company(company))
                self.assertFalse(policy.is_target_company(company))
                self.assertFalse(validator.valid(job)[0])
                job["requirements"].append("Atuação em serviços financeiros")
                self.assertEqual(validator.valid(job), (True, "ok"))

    def test_new_companies_with_strong_financial_context_are_still_allowed(self):
        job = vacancy("Empresa não cadastrada", reason="Atuação no mercado financeiro e em serviços financeiros")
        self.assertFalse(policy.is_target_company(job["company"]))
        self.assertEqual(validator.valid(job), (True, "ok"))

    def test_company_approval_does_not_bypass_other_filters(self):
        for company in ("Microsoft", "Google"):
            for overrides in (
                {"role": "Software Engineer Sênior"},
                {"role": "Assistente Administrativo Júnior", "requirements": ["Excel", "Comunicação", "Organização"]},
                {"requirements": ["Python", "SQL"]},
                {"location": "Lisboa, Portugal", "modality": "Presencial"},
            ):
                with self.subTest(company=company, overrides=overrides):
                    self.assertFalse(validator.valid(vacancy(company, **overrides))[0])

    def test_aliases_belong_to_only_one_company(self):
        owners = {}
        for company in policy.COMPANIES:
            for name in (company.name, *company.aliases):
                key = policy.normalize_company(name)
                self.assertTrue(key)
                self.assertNotIn(key, owners)
                owners[key] = company.name
        self.assertFalse(policy.TARGET_KEYS & policy.CONTEXT_KEYS)

    def test_search_lists_only_contain_canonical_registered_targets(self):
        self.assertEqual(len(policy.CORE_PRIORITY_COMPANIES), 18)
        self.assertEqual(len(policy.PRIORITY_COMPANIES), 62)
        self.assertEqual(len(set(policy.PRIORITY_COMPANIES)), len(policy.PRIORITY_COMPANIES))
        self.assertLessEqual(set(policy.CORE_PRIORITY_COMPANIES), set(policy.PRIORITY_COMPANIES))
        self.assertLessEqual(set(policy.PRIORITY_COMPANIES), set(policy.TARGET_COMPANIES))
        for company in ("Microsoft", "Google"):
            self.assertIn(company, policy.CORE_PRIORITY_COMPANIES)
        self.assertNotIn("ANBIMA", policy.PRIORITY_COMPANIES)
        self.assertIn("ANBIMA", policy.TARGET_COMPANIES)

    def test_priority_search_queries_include_each_technology_company_once(self):
        with patch.object(collector, "LINKEDIN_KEYWORDS", []), patch.object(
            collector, "linkedin_query_urls", side_effect=lambda query, starts: [query],
        ):
            queries = enhanced.enhanced_linkedin_urls()
        for company in ("Microsoft", "Google"):
            self.assertEqual(sum(query.startswith(f'"{company}" AND') for query in queries), 1)

    def test_collection_validation_and_catalog_keep_non_financial_targets(self):
        # Synthetic public-page responses; no network, real catalog or database writes.
        # Separate validation/build processes reproduce the actual workflow and ensure
        # they do not depend on the collector's configure() monkey-patches.
        for company in ("Microsoft", "Microsoft Brasil", "Google", "Google Brasil"):
            with self.subTest(company=company), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                auto_file = root / "data-auto.js"
                job = vacancy(company)
                posting = {
                    "@type": "JobPosting", "title": job["role"],
                    "hiringOrganization": {"name": company},
                    "jobLocation": {"address": {"addressLocality": "São Paulo", "addressRegion": "SP", "addressCountry": "BR"}},
                    "description": "<h2>Requisitos</h2><ul>" + "".join(f"<li>{item}</li>" for item in job["requirements"]) + "</ul>",
                }
                with patch.multiple(collector, ROOT=root, AUTO_FILE=auto_file, BASE_FILES=[]), patch.object(
                    collector, "discover_urls", return_value=[job["source"]],
                ), patch.object(collector, "fetch_page", return_value=(None, posting)), patch.object(collector.time, "sleep"):
                    self.assertEqual(collector.main(), 0)
                self.assertEqual([item["company"] for item in validator.parse_jobs(auto_file)], [company])
                commands = (
                    "import validate_auto as stage; stage.ROOT = root; stage.AUTO_FILE = root / 'data-auto.js'; stage.BASE_FILES = []; stage.main()",
                    "import build_catalog as stage; stage.ROOT = root; stage.run(online=False)",
                )
                for command in commands:
                    result = subprocess.run([
                        sys.executable, "-c",
                        "import sys; from pathlib import Path; sys.path.insert(0, 'scripts'); root = Path(sys.argv[1]); " + command,
                        directory,
                    ], cwd=ROOT, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads((root / "collection-report.json").read_text())
                catalog = json.loads((root / "jobs.json").read_text())
                self.assertEqual((report["added"], report["validated"], report["rejected"]), (1, 1, 0))
                self.assertEqual(catalog["meta"]["included"], 1)
                self.assertEqual(catalog["jobs"][0]["company"], company)
                self.assertFalse(catalog["jobs"][0]["excluded"])


if __name__ == "__main__":
    unittest.main()
