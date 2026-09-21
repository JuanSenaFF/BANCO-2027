import copy
import html
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from source_resolution import (GupyResolver, board_page, job_url, match_evidence,
                               promote_source, resolve_catalog, restore_source)
from build_catalog import apply_source_preference
import build_catalog

BASE = 'https://pagseguro.gupy.io/'
URL = BASE + 'jobs/11175121'
SECOND = BASE + 'jobs/22222222'
LINKEDIN = 'https://br.linkedin.com/jobs/view/cientista-de-dados-jr-at-pagbank-4418200168/'


def job():
    return {'key': 'linkedin:4418200168', 'id': 45, 'company': 'PagBank',
            'role': 'Cientista de Dados Jr', 'source': LINKEDIN,
            'status': 'Possivelmente encerrada', 'validationState': 'pending',
            'requirements': ['Python', 'SQL', 'Estatística', 'Machine Learning',
                             'Crédito', 'Fraude', 'PLD', 'Cobrança', 'Modelos preditivos'],
            'firstSeenAt': '2026-01-01', 'location': None}


def posting(**changes):
    return {'@type': 'JobPosting', 'title': 'Cientista de Dados Jr.',
            'hiringOrganization': {'name': 'PagBank'}, 'validThrough': '2099-12-31',
            'description': '<h2>Descrição da vaga</h2><p>Sobre o PagBank</p>'
            '<h2>Responsabilidades e atribuições</h2><ul>'
            '<li>Analytics e Machine Learning para crédito, fraude, PLD e cobrança.</li>'
            '<li>Modelos preditivos e análise de dados.</li></ul>'
            '<h2>Requisitos e qualificações</h2><ul><li>Python e SQL</li>'
            '<li>Estatística e Machine Learning</li><li>Modelos preditivos</li></ul>',
            'jobLocation': {'address': {'addressLocality': 'São Paulo', 'addressRegion': 'SP'}},
            **changes}


def markup(p):
    return '<script type="application/ld+json">' + html.escape(json.dumps(p)) + '</script>'


class SourceResolutionTests(unittest.TestCase):
    def resolve(self, p=None, board=None, second=None):
        pages = {BASE: board or '<a href="/jobs/11175121">Cientista de Dados Jr.</a>',
                 URL: markup(p or posting())}
        if second:
            pages[BASE] += '<a href="/jobs/22222222">Cientista de Dados Jr.</a>'
            pages[SECOND] = markup(second)

        def fetch(_session, url):
            return SimpleNamespace(status_code=200, text=pages[url], url=url)

        with patch('source_resolution.safe_fetch', side_effect=fetch), patch('quality.safe_fetch', side_effect=fetch):
            return GupyResolver(object()).resolve(job())

    def test_pagbank_resolves_by_title_requirements_and_duties(self):
        outcome = self.resolve()
        self.assertEqual(outcome['state'], 'resolved')
        self.assertEqual(outcome['url'], URL)
        self.assertEqual(outcome['verification']['validationState'], 'confirmed')

    def test_jr_and_junior_are_equivalent(self):
        outcome = self.resolve(posting(title='Cientista de Dados Júnior'))
        self.assertEqual(outcome['state'], 'resolved')

    def test_same_title_two_jobs_go_to_review(self):
        self.assertEqual(self.resolve(second=posting())['state'], 'review_required')

    def test_other_company_cannot_resolve(self):
        self.assertEqual(self.resolve(posting(hiringOrganization={'name': 'Banco BMG'}))['state'], 'pending')

    def test_title_alone_is_not_enough(self):
        outcome = self.resolve(posting(description='<h2>Requisitos</h2><li>Java</li><li>Git</li><li>Spring Boot</li>'))
        self.assertNotEqual(outcome['state'], 'resolved')

    def test_generic_company_text_does_not_count(self):
        p = posting(description='<p>Python SQL Estatística Machine Learning Crédito Fraude PLD Cobrança Modelos preditivos</p>'
                    '<h2>Requisitos</h2><li>Java</li><li>Git</li><li>Spring Boot</li>')
        self.assertNotEqual(self.resolve(p)['state'], 'resolved')

    def test_expired_official_job_does_not_close_linkedin_record(self):
        outcome = self.resolve(posting(validThrough='2000-01-01'))
        target = job()
        promote_source(target, outcome)
        self.assertEqual(outcome['state'], 'pending')
        self.assertEqual(target['source'], LINKEDIN)
        self.assertNotEqual(target['status'], 'Encerrada')

    def test_senior_and_pcd_mismatch_not_associated(self):
        for title in ('Cientista de Dados Sênior', 'Cientista de Dados Jr. PCD'):
            with self.subTest(title=title):
                self.assertIsNone(match_evidence(job(), posting(title=title), 'pagseguro'))

    def test_city_conflict_rejected(self):
        target = {**job(), 'location': 'Campinas, SP'}
        self.assertIsNone(match_evidence(target, posting(), 'pagseguro'))

    def test_missing_city_is_not_invented_as_matching_evidence(self):
        evidence = match_evidence(job(), posting(), 'pagseguro')
        self.assertTrue(evidence['requirementsConfirmed'])
        self.assertGreaterEqual(evidence['score'], 85)

    def test_no_known_board_remains_pending(self):
        with patch('source_resolution.safe_fetch') as fetch:
            result = GupyResolver(object()).resolve({**job(), 'company': 'Unknown'})
        fetch.assert_not_called()
        self.assertEqual(result['state'], 'pending')

    def test_failed_board_cached_once_for_multiple_jobs(self):
        with patch('source_resolution.safe_fetch', side_effect=TimeoutError) as fetch:
            resolver = GupyResolver(object())
            for _ in range(2):
                self.assertEqual(resolver.resolve(job())['state'], 'fetch_failed')
        self.assertEqual(fetch.call_count, 1)

    def test_exhausted_budget_preserves_pending_record(self):
        resolver = GupyResolver(object())
        resolver.requests = 80
        with patch('source_resolution.safe_fetch') as fetch:
            result = resolver.resolve(job())
        fetch.assert_not_called()
        self.assertEqual(result['state'], 'fetch_failed')
        self.assertIn('Orçamento', result['reason'])

    def test_one_failed_candidate_prevents_false_unique_match(self):
        board = '<a href="/jobs/11175121">Cientista de Dados Jr</a><a href="/jobs/22222222">Cientista de Dados Jr</a>'
        self.assertEqual(self.resolve(board=board)['state'], 'fetch_failed')

    def test_next_data_jobs_and_anchors_are_deduplicated(self):
        payload = {'props': {'pageProps': {'jobs': [{'id': 11175121, 'name': 'Cientista de Dados Jr'}]}}}
        page = '<a href="/jobs/11175121?tracking=x">Cientista</a><script id="__NEXT_DATA__">' + json.dumps(payload) + '</script>'
        rows, _, _, _ = board_page(page, 'pagseguro')
        self.assertEqual(rows, {URL: 'Cientista de Dados Jr'})

    def test_hostile_or_wrong_employer_urls_are_rejected(self):
        for url in ('https://evil.test/jobs/123', 'https://pagseguro.gupy.io.evil.test/jobs/123',
                    'http://pagseguro.gupy.io/jobs/123', 'https://user@pagseguro.gupy.io/jobs/123',
                    'https://pagseguro.gupy.io:444/jobs/123', 'https://anbima.gupy.io/jobs/123'):
            self.assertIsNone(job_url(url, 'pagseguro'))

    def test_board_redirect_to_other_employer_is_not_trusted(self):
        response = SimpleNamespace(status_code=200, text='<a href="/jobs/11175121">Cientista</a>', url='https://evil.test/')
        with patch('source_resolution.safe_fetch', return_value=response):
            self.assertEqual(GupyResolver(object()).resolve(job())['state'], 'fetch_failed')

    def test_detail_redirect_to_other_job_is_not_trusted(self):
        response = SimpleNamespace(status_code=200, text=markup(posting()), url=SECOND)
        with patch('source_resolution.safe_fetch', return_value=response):
            with self.assertRaises(ValueError):
                GupyResolver(object()).load_detail(URL)

    def test_rate_limited_board_is_not_treated_as_empty(self):
        with patch('source_resolution.safe_fetch', return_value=SimpleNamespace(status_code=429)):
            outcome = GupyResolver(object()).resolve(job())
        self.assertEqual(outcome['state'], 'fetch_failed')
        self.assertIn('429', outcome['reason'])

    def test_dynamic_pagination_never_claims_complete_search(self):
        board = '<script id="__NEXT_DATA__">' + json.dumps({'jobs': [{'id':11175121, 'name':'Cientista de Dados Jr'}], 'hasNextPage': True}) + '</script>'
        self.assertEqual(self.resolve(board=board)['state'], 'fetch_failed')

    def test_declared_total_exceeds_visible_jobs(self):
        board = '<script id="__NEXT_DATA__">' + json.dumps({'jobs': [{'id':11175121, 'name':'Cientista de Dados Jr'}], 'totalJobs': 50}) + '</script>'
        self.assertEqual(self.resolve(board=board)['state'], 'fetch_failed')

    def test_static_next_page_is_followed_and_cached(self):
        page2 = BASE + '?page=2'
        pages = {BASE: '<a href="?page=2" rel="next">Next</a>', page2: '<a href="/jobs/11175121">Cientista</a>'}
        with patch('source_resolution.safe_fetch', side_effect=lambda _, url: SimpleNamespace(status_code=200, text=pages[url], url=url)) as fetch:
            resolver = GupyResolver(object())
            self.assertEqual(resolver.load_board('pagseguro')[0], {URL: 'Cientista'})
            resolver.load_board('pagseguro')
        self.assertEqual(fetch.call_count, 2)

    def test_promotion_keeps_key_first_seen_and_both_urls(self):
        target = job()
        promote_source(target, self.resolve())
        self.assertEqual(target['key'], 'linkedin:4418200168')
        self.assertEqual(target['firstSeenAt'], '2026-01-01')
        self.assertEqual(target['source'], URL)
        self.assertEqual({r['url'] for r in target['sources']}, {URL, LINKEDIN})
        self.assertTrue(target['sourceOfficial'])

    def test_catalog_merge_does_not_restore_old_linkedin_source(self):
        previous = job()
        promote_source(previous, self.resolve())
        merged = restore_source(previous, {**previous, **job()})
        self.assertEqual(merged['source'], URL)
        self.assertEqual(merged['requirements'], previous['requirements'])

    def test_resolution_review_does_not_override_existing_review(self):
        target = {**job(), 'reviewRequired': True, 'reviewReason': 'Outra revisão'}
        promote_source(target, {'state': 'review_required', 'reason': 'Ambígua'})
        self.assertEqual(target['reviewReason'], 'Outra revisão')
        self.assertEqual(target['source'], LINKEDIN)

    def test_ambiguous_match_enters_review_queue_and_can_be_resolved(self):
        target = job()
        promote_source(target, self.resolve(second=posting()))
        self.assertTrue(target['reviewRequired'])
        self.assertIn('Fonte oficial:', target['reviewReason'])
        promote_source(target, self.resolve())
        self.assertFalse(target['reviewRequired'])

    def test_real_catalog_rebuild_preserves_resolved_key_and_source(self):
        previous = job()
        promote_source(previous, self.resolve())
        official = {**previous, 'id': 100, 'key': 'pagseguro.gupy.io/jobs/11175121'}
        official.pop('sourceResolution')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'jobs.json').write_text(json.dumps({'jobs': [previous], 'meta': {}}))
            with patch.object(build_catalog, 'ROOT', root), patch.object(build_catalog, 'parse_jobs', side_effect=lambda p: [job(), official] if p.name == 'data-auto.js' else []):
                build_catalog.run(online=False)
                build_catalog.run(online=False)
            result = json.loads((root / 'jobs.json').read_text())['jobs']
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['key'], previous['key'])
        self.assertEqual(result[0]['id'], previous['id'])
        self.assertEqual(result[0]['source'], URL)
        self.assertEqual(result[0]['firstSeenAt'], previous['firstSeenAt'])

    def test_resolved_stable_key_wins_over_newly_collected_duplicate(self):
        target = job()
        promote_source(target, self.resolve())
        duplicate = {**copy.deepcopy(target), 'key': 'pagseguro.gupy.io/jobs/11175121', 'firstSeenAt': '2099-01-01'}
        duplicate.pop('sourceResolution')
        apply_source_preference([duplicate, target])
        self.assertEqual(duplicate['duplicateOf'], target['key'])
        self.assertIsNone(target['duplicateOf'])

    def test_closed_excluded_or_non_linkedin_are_not_resolved(self):
        jobs = [{**job(), 'status':'Encerrada'}, {**job(), 'excluded':True}, {**job(), 'source':URL}]
        with patch('source_resolution.safe_fetch') as fetch:
            self.assertEqual(resolve_catalog(jobs, object()), {})
        fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
