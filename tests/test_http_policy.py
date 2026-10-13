import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from http_policy import PublicHTTP
from collection_audit import CandidateAudit, schedule


def response(url, status=200, body='public job', headers=None):
    r = requests.Response()
    r.url, r.status_code, r._content, r.encoding = url, status, body.encode(), 'utf-8'
    r.headers.update(headers or {})
    return r


class HTTPPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000
        self.sleeps = []
        self.http = PublicHTTP(self.tmp.name, clock=lambda: self.now, sleep=self.sleep)

    def sleep(self, duration):
        self.sleeps.append(duration)
        self.now += duration

    def test_success_cache_survives_runs_and_does_not_repeat_network(self):
        url = 'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/12345678'
        session = Mock(); session.get.return_value = response(url)
        self.http.get(session, url); self.http.save()
        other = PublicHTTP(self.tmp.name, clock=lambda: self.now, sleep=self.sleep)
        result = other.get(session, url)
        self.assertEqual(result.text, 'public job')
        self.assertEqual(result.headers['X-Radar-Cache'], 'hit')
        session.get.assert_called_once()

    def test_cache_params_are_part_of_identity_and_expired_cache_is_refetched(self):
        url = 'https://example.com/search'
        session = Mock(); session.get.return_value = response(url)
        self.http.get(session, url, params={'q': 'Python'})
        self.http.get(session, url, params={'q': 'Java'})
        self.now += 901
        self.http.get(session, url, params={'q': 'Python'})
        self.assertEqual(session.get.call_count, 3)

    def test_retry_after_suspends_only_blocked_host_and_persists(self):
        url = 'https://www.linkedin.com/jobs/view/12345678'
        session = Mock();session.get.return_value = response(url, 429, headers={'Retry-After': '120'})
        self.http.get(session, url);self.http.save()
        other = PublicHTTP(self.tmp.name, clock=lambda: self.now, sleep=self.sleep)
        skipped = other.get(session, url + '9')
        self.assertEqual(skipped.headers['X-Radar-Cooldown'], 'true')
        session.get.assert_called_once()
        session.get.return_value = response('https://example.com/jobs')
        other.get(session, 'https://example.com/jobs')
        self.assertEqual(session.get.call_count, 2)
        self.assertFalse(self.sleeps)

    def test_progressive_cooldown_and_pacing(self):
        url = 'https://www.linkedin.com/jobs/search'
        session = Mock();session.get.return_value = response(url, 429)
        self.http.get(session, url)
        self.assertEqual(self.http.state['www.linkedin.com']['blocked_until'], 1030)
        self.now = 1031
        self.http.get(session, url)
        self.assertEqual(self.http.state['www.linkedin.com']['blocked_until'], 1091)
        self.now = 1092
        session.get.return_value = response(url)
        self.http.get(session, url, params={'q':'Python'})
        self.http.get(session, url, params={'q':'Java'})
        self.assertEqual(self.sleeps, [1.5])

    def test_login_wall_and_failures_are_not_cached(self):
        url = 'https://www.linkedin.com/jobs/view/12345678'
        session = Mock();session.get.return_value = response('https://www.linkedin.com/authwall')
        self.http.get(session, url);self.http.get(session, url)
        self.assertEqual(session.get.call_count, 2)
        self.assertFalse(list(Path(self.tmp.name).glob('*.json')))

    def test_retry_queue_keeps_deadline_and_attempt_count_when_deferred(self):
        url = 'https://www.linkedin.com/jobs/view/12345678'
        rows = [{'url':url,'source':'linkedin','bucket':'core'}]
        path = Path(self.tmp.name)/'history.json'
        audit = CandidateAudit(path,rows,'2026-10-13T12:00:00Z')
        audit.mark(url,'retry','fetch_429');audit.finish(scheduled=1,scanned=1)
        later = CandidateAudit(path,rows,'2026-10-13T12:01:00Z')
        self.assertEqual(schedule(rows,later,set(),lambda _:True), [])
        self.assertEqual(later.history['linkedin:12345678']['retry_after'], '2026-10-13T12:30:00+00:00')
        self.assertEqual(later.history['linkedin:12345678']['attempt_count'], 1)
        self.assertEqual(later.history['linkedin:12345678']['url'], url)
