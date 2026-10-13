"""Public discovery cache and per-host pacing; never cache live verification."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import Counter
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests


class PublicHTTP:
    def __init__(self, directory, *, clock=time.time, sleep=time.sleep):
        self.directory = Path(directory)
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()
        self.host_locks, self.next_request = {}, {}
        self.stats = Counter()
        try:
            self.state = json.loads((self.directory / 'state.json').read_text())
        except (OSError, ValueError):
            self.state = {}

    def _response(self, data, *, cached=False):
        r = requests.Response()
        r.status_code, r.url = data['status'], data['url']
        r._content = data.get('body', '').encode('utf-8')
        r.encoding = 'utf-8'
        r.headers.update(data.get('headers', {}))
        if cached:
            r.headers['X-Radar-Cache'] = 'hit'
        return r

    def _delay(self, header, failures):
        try:
            delay = float(header)
        except (TypeError, ValueError):
            try:
                delay = parsedate_to_datetime(header).replace(tzinfo=timezone.utc).timestamp() - self.clock()
            except (TypeError, ValueError, OverflowError):
                delay = 30 * 2 ** min(failures - 1, 6)
        return max(1, min(delay, 86400))

    def get(self, session, url, *, timeout=10, **kwargs):
        host = (urlparse(url).hostname or '').lower()
        linkedin = host == 'linkedin.com' or host.endswith('.linkedin.com')
        key = hashlib.sha256(json.dumps([url, kwargs.get('params'), kwargs.get('headers')], sort_keys=True).encode()).hexdigest()
        path = self.directory / (key + '.json')
        ttl = 21600 if linkedin and ('/jobPosting/' in url or '/jobs/view/' in url) else 900
        try:
            data = json.loads(path.read_text())
            if data['expires'] > self.clock():
                with self.lock:
                    self.stats['cache_hits'] += 1
                return self._response(data, cached=True)
        except (OSError, ValueError, KeyError):
            pass
        with self.lock:
            host_lock = self.host_locks.setdefault(host, threading.Lock())
        with host_lock:
            # Another worker may have filled the same cache while we waited.
            try:
                data = json.loads(path.read_text())
                if data['expires'] > self.clock():
                    self.stats['cache_hits'] += 1
                    return self._response(data, cached=True)
            except (OSError, ValueError, KeyError):
                pass
            state = self.state.setdefault(host, {})
            until = state.get('blocked_until', 0)
            if until > self.clock():
                self.stats['cooldown_skips'] += 1
                return self._response({'status': state.get('status', 429), 'url': url,
                                       'headers': {'Retry-After': str(int(until - self.clock()) + 1),
                                                   'X-Radar-Cooldown': 'true'}})
            interval = 1.5 if linkedin else .1
            delay = max(0, self.next_request.get(host, 0) - self.clock())
            if delay:
                self.sleep(delay)
            self.next_request[host] = self.clock() + interval
            self.stats['network_requests'] += 1
            response = session.get(url, timeout=timeout, allow_redirects=True, **kwargs)
            if response.status_code in {429, 500, 502, 503, 504}:
                failures = state.get('failures', 0) + 1
                state.update(failures=failures, status=response.status_code,
                             blocked_until=self.clock() + self._delay(response.headers.get('Retry-After'), failures))
                self.stats['rate_limited' if response.status_code == 429 else 'server_errors'] += 1
            elif response.status_code == 200:
                state.update(failures=0, blocked_until=0)
                # Only public, successful discovery responses. Redirected login
                # walls are neither cached nor treated as evidence of a vacancy.
                final = urlparse(response.url or url)
                if final.hostname == host and not any(x in final.path for x in ('/login', '/authwall', '/signin')):
                    self.directory.mkdir(parents=True, exist_ok=True)
                    body = response.text
                    if len(body.encode()) <= 5_000_000:
                        data = {'status': 200, 'url': response.url or url, 'body': body,
                                'expires': self.clock() + ttl,
                                'headers': {'Content-Type': response.headers.get('Content-Type', '')}}
                        path.write_text(json.dumps(data, ensure_ascii=False))
            return response

    def save(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / 'state.json').write_text(json.dumps(self.state))
        for path in self.directory.glob('*.json'):
            if path.name == 'state.json':
                continue
            try:
                if json.loads(path.read_text()).get('expires', 0) < self.clock():
                    path.unlink()
            except (OSError, ValueError):
                pass
        return dict(self.stats)
