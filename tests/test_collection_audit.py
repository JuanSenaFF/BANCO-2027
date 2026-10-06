import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_vagas as collector
from collection_audit import CandidateAudit, schedule
from source_resolution import OfficialSourceResolver, promote_source


class CollectionAuditTests(unittest.TestCase):
    def test_source_budgets_never_displace_core_or_official(self):
        rows = ([{"url": f"https://www.linkedin.com/jobs/view/{10000000+i}", "source": "linkedin", "bucket": "generic"} for i in range(500)] +
                [{"url": "https://www.linkedin.com/jobs/view/99999999", "source": "linkedin", "bucket": "core"},
                 {"url": "https://carreiras.itau.com.br/vaga/sp/dev/35299/123", "source": "company", "bucket": "official"}])
        with tempfile.TemporaryDirectory() as directory:
            audit = CandidateAudit(Path(directory) / "history.json", rows, "2026-10-06T12:00:00Z")
            selected = schedule(rows, audit, set(), lambda _: True)
            self.assertEqual(selected[:2], [rows[-1]["url"], rows[-2]["url"]])
            self.assertEqual(len(selected), 142)
            for url in selected:
                audit.mark(url, "fetch_failed", "fetch_403")
            funnel = audit.finish(scheduled=len(selected), scanned=len(selected))
            self.assertEqual(sum(funnel["outcomes"].values()), 502)
            self.assertEqual(funnel["not_scanned"], 360)

    def test_regression_entry_titles_all_enter_without_relaxing_quality(self):
        examples = [
            ("Analista de Engenharia TI Jr", "Itaú"),
            ("Software Engineer Early Career", "Google"),
            ("IT Analyst I", "Santander"),
            ("Software Engineer Junior", "Microsoft"),
            ("Data Analyst I", "Banco Inter"),
        ]
        for index, (title, company) in enumerate(examples):
            with self.subTest(title=title), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                url = f"https://www.linkedin.com/jobs/view/{90000000+index}"
                posting = {"@type": "JobPosting", "title": title, "hiringOrganization": {"name": company},
                           "jobLocation": {"address": {"addressLocality": "São Paulo", "addressRegion": "SP"}},
                           "description": "<h2>Requirements</h2><ul><li>Python development</li><li>SQL databases</li><li>Git and APIs REST</li></ul>"}
                with patch.multiple(collector, ROOT=root, AUTO_FILE=root / "data-auto.js", BASE_FILES=[]), \
                        patch.object(collector, "discover_urls", return_value=[url]), \
                        patch.object(collector, "fetch_page", return_value=(None, posting)):
                    self.assertEqual(collector.main(), 0)
                report = json.loads((root / "collection-report.json").read_text())
                self.assertEqual(report["outcomes"], {"accepted": 1})
                self.assertEqual(report["added"], 1)

    def test_fallback_requires_qualification_evidence(self):
        posting = {"title": "Software Engineer Junior", "description": "<ul><li>Conhecimento em Python</li><li>Experiência em SQL</li><li>Familiaridade com Git</li></ul>"}
        req, _, method = collector.requirements_for(None, posting)
        self.assertEqual((len(req), method), (3, "technical_bullets"))
        duties = {"title": "Software Engineer Junior", "description": "<ul><li>Desenvolver em Python</li><li>Criar SQL</li><li>Integrar Git</li></ul>"}
        self.assertLess(len(collector.requirements_for(None, duties)[0]), 3)

    def test_unknown_official_location_is_review_not_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            url = "https://carreiras.itau.com.br/vaga/sp/software-engineer-junior/35299/123"
            posting = {"title": "Software Engineer Junior", "hiringOrganization": {"name": "Banco Itau"},
                       "description": "<h2>Requirements</h2><li>Python</li><li>SQL</li><li>Git APIs</li>"}
            with patch.multiple(collector, ROOT=root, AUTO_FILE=root / "data-auto.js", BASE_FILES=[]), \
                    patch.object(collector, "discover_urls", return_value=[url]), \
                    patch.object(collector, "fetch_page", return_value=(None, posting)):
                collector.main()
            self.assertEqual(json.loads((root / "collection-report.json").read_text())["outcomes"], {"retry": 1})

    def test_google_public_page_extracts_title_requirements_and_sp(self):
        markup = ('<div class="DkhPwc"><h2 class="p1N2lc">Software Engineer, Early Career</h2>'
                  '<span class="pwO9Dc vo5qdf">São Paulo, State of São Paulo, Brazil</span>'
                  '<h3>Minimum qualifications:</h3><ul><li>Python</li><li>SQL</li><li>Git and APIs</li></ul></div>')
        url = 'https://www.google.com/about/careers/applications/jobs/results/12345678-software-engineer-early-career'
        with patch.object(collector, 'safe_get', return_value=SimpleNamespace(status_code=200, text=markup)):
            soup, posting = collector.fetch_page(url)
        self.assertEqual(posting['hiringOrganization']['name'], 'Google')
        self.assertEqual(len(collector.requirements_for(soup, posting)[0]), 3)
        self.assertIn('São Paulo', posting['jobLocation']['address']['addressLocality'])

    def test_official_two_requirement_job_is_reviewed_without_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            url = 'https://www.google.com/about/careers/applications/jobs/results/12345678-software-engineer-early-career'
            posting = {'title': 'Software Engineer Early Career', 'hiringOrganization': {'name': 'Google'},
                       'jobLocation': {'address': {'addressLocality': 'São Paulo, Brasil'}},
                       'description': '<h3>Minimum qualifications:</h3><li>Python and Java</li><li>SQL and Git</li>'}
            with patch.multiple(collector, ROOT=root, AUTO_FILE=root / 'data-auto.js', BASE_FILES=[]), \
                    patch.object(collector, 'discover_urls', return_value=[url]), \
                    patch.object(collector, 'fetch_page', return_value=(None, posting)):
                collector.main()
            report = json.loads((root / 'collection-report.json').read_text())
            self.assertEqual(report['outcomes'], {'retry': 1})
            self.assertEqual(report['reasons']['requirements_review'], 1)
            self.assertEqual(report['added'], 0)


class GenericResolverTests(unittest.TestCase):
    def test_greenhouse_feed_promotes_linkedin_only_with_matching_requirements(self):
        job = {"key": "linkedin:1", "source": "https://www.linkedin.com/jobs/view/12345678",
               "role": "Software Engineer Junior", "company": "Stone", "requirements": ["Python", "SQL", "Git"],
               "status": "Possivelmente encerrada"}
        url = "https://boards.greenhouse.io/stone/jobs/1234"
        feed = {"jobs": [{"title": job["role"], "absolute_url": url, "content":
                          "<h2>Requirements</h2><li>Python</li><li>SQL</li><li>Git</li>",
                          "location": {"name": "São Paulo, SP"}}]}
        response = SimpleNamespace(status_code=200, json=lambda: feed)
        with patch("source_resolution.safe_fetch", return_value=response):
            result = OfficialSourceResolver(object()).resolve(job)
        self.assertEqual(result["state"], "resolved")
        promote_source(job, result)
        self.assertEqual(job["source"], url)
        self.assertEqual(job["sourceProvider"], "greenhouse")
        self.assertEqual(job["validationState"], "confirmed")

    def test_itau_careers_resolves_legal_name_and_abbreviated_title(self):
        url = "https://carreiras.itau.com.br/vaga/sao-paulo/anl-engenharia-ti-jr-dados/35299/101004728032"
        job = {"source": "https://www.linkedin.com/jobs/view/12345678", "company": "Itaú",
               "role": "Analista de Engenharia TI Jr", "requirements": ["Python", "SQL", "Git"],
               "status": "Possivelmente encerrada"}
        posting = {"@type": "JobPosting", "title": "ANL ENGENHARIA TI JR - DADOS",
                   "hiringOrganization": {"name": "Banco Itau"}, "validThrough": "2099-12-31",
                   "jobLocation": {"address": {"addressLocality": "São Paulo", "addressRegion": "SP"}},
                   "description": "<h2>Responsabilidades</h2><p>Construir soluções resilientes e colaborar com o time de engenharia.</p>"
                                  "<h2>No que você precisa mandar bem?</h2><ul><li>Conhecimento em Python</li>"
                                  "<li>Conhecimento em SQL</li><li>Experiência com Git</li></ul>"}
        import html
        detail = '<script type="application/ld+json">' + html.escape(json.dumps(posting)) + '</script>'
        response = SimpleNamespace(status_code=200, text=detail, url=url)
        with patch("update_vagas.official_company_urls", return_value=[url]), \
                patch("source_resolution.safe_fetch", return_value=response):
            result = OfficialSourceResolver(object()).resolve(job)
        self.assertEqual(result["state"], "resolved")
        self.assertEqual(result["verification"]["validationState"], "confirmed")

    def test_santander_workday_search_and_detail_confirm_it_analyst_i(self):
        url = "https://santander.wd3.myworkdayjobs.com/pt-BR/SantanderCareers/job/SAO-PAULO/IT-Analyst-I--Suporte-_Req1612818"
        job = {"source": "https://www.linkedin.com/jobs/view/12345678", "company": "Santander",
               "role": "IT Analyst I (Suporte)", "requirements": ["Linux", "infraestrutura", "suporte a sistemas"],
               "status": "Possivelmente encerrada"}
        detail = {"jobPostingInfo": {"title": job["role"], "location": "SAO PAULO",
                 "jobDescription": "<p>Buscamos tecnologia para nossos sistemas críticos.</p>"
                                   "<b>Requisitos Imprescindíveis</b><ul><li>Conhecimento em Linux</li>"
                                   "<li>Conhecimento em infraestrutura</li><li>Experiência com suporte a sistemas</li></ul>",
                 "startDate": "2026-10-01"}}
        response = SimpleNamespace(status_code=200, json=lambda: detail)
        with patch("update_vagas.workday_urls", return_value=[url]), \
                patch("source_resolution.safe_fetch", return_value=response):
            outcome = OfficialSourceResolver(object()).resolve(job)
        self.assertEqual(outcome["state"], "resolved")
        self.assertEqual(outcome["verification"]["validationState"], "confirmed")


if __name__ == "__main__":
    unittest.main()
