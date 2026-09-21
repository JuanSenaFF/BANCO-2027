"""Resolve LinkedIn discoveries against known public employer Gupy boards.

No login, guessed private API, or title-only promotion. Network failures and
ambiguous matches retain the original record and carry an auditable reason.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from official_sources import merge_source_records
from quality import (extract_jobposting, location_fields, norm, parse_json_ld,
                     safe_fetch, senior_conflict, split_requirements, verify)

# Explicit employer aliases, never arbitrary company-name substring matches.
GUPY_BOARDS = {
    'pagbank': 'pagseguro', 'pagseguro': 'pagseguro',
    'anbima': 'anbima', 'grupo bancorbras': 'bancorbras', 'bancorbras': 'bancorbras',
    'via certa promotora': 'acertapromotora', 'banco bmg': 'bancobmg',
    'nuclea': 'nuclea', 'sicredi': 'sicredi', 'sicoob': 'sicoob',
    'banco bv': 'bancobv', 'picpay': 'picpay',
}
MAX_PAGES = 10
MAX_DETAILS = 20
MAX_REQUESTS = 80
MAX_SECONDS = 180


def normalized(value):
    return re.sub(r'[^a-z0-9]+', ' ', norm(value)).strip()


def board_for(company):
    return GUPY_BOARDS.get(normalized(company))


def title_words(value):
    text = normalized(value)
    text = re.sub(r'\b(jr|junior)\b', 'junior', text)
    text = re.sub(r'\bdev\b', 'desenvolvedor', text)
    # Keep seniority, PCD, technologies and locations: none is harmless noise.
    return text


def title_score(a, b):
    return SequenceMatcher(None, title_words(a), title_words(b)).ratio()


def job_url(value, board):
    url = urljoin(f'https://{board}.gupy.io/', str(value))
    p = urlparse(url)
    if (p.scheme == 'https' and p.netloc == f'{board}.gupy.io'
            and re.fullmatch(r'/jobs/\d+/?', p.path)):
        return f'https://{p.netloc}{p.path.rstrip("/")}'
    return None


def board_page(markup, board):
    """Read public anchors and embedded Next.js data; never invent endpoints."""
    soup = BeautifulSoup(markup, 'html.parser')
    rows = {}
    next_pages = set()
    has_next = False
    advertised_total = 0
    for a in soup.select('a[href]'):
        url = job_url(a['href'], board)
        if url:
            rows[url] = a.get_text(' ', strip=True)
        elif 'next' in (a.get('rel') or []) or normalized(a.get_text()) in {'proxima', 'proximo', 'next'}:
            p = urlparse(urljoin(f'https://{board}.gupy.io/', a['href']))
            if p.scheme == 'https' and p.netloc == f'{board}.gupy.io' and p.path == '/':
                next_pages.add(p.geturl())

    def walk(obj):
        nonlocal has_next, advertised_total
        if isinstance(obj, dict):
            if obj.get('hasNextPage') is True:
                has_next = True
            for field in ('totalJobs', 'totalCount'):
                if isinstance(obj.get(field), int):
                    advertised_total = max(advertised_total, obj[field])
            if obj.get('id') and (obj.get('name') or obj.get('title')):
                # A numeric ID alone might be a company/location, not a job.
                value = obj.get('jobUrl') or obj.get('url')
                if value:
                    url = job_url(value, board)
                    if url:
                        rows[url] = str(obj.get('name') or obj['title'])
            for key, value in obj.items():
                if key in {'jobs', 'jobList'} and isinstance(value, list):
                    for j in value:
                        if isinstance(j, dict) and j.get('id') and (j.get('name') or j.get('title')):
                            url = job_url(f'/jobs/{j["id"]}', board)
                            if url:
                                rows[url] = str(j.get('name') or j['title'])
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    for script in soup.select('script#__NEXT_DATA__'):
        walk(parse_json_ld(script.string or script.get_text()))
    return rows, next_pages, has_next, advertised_total


class GupyResolver:
    def __init__(self, session):
        self.session = session
        self.boards = {}
        self.details = {}
        self.requests = 0
        self.started = time.monotonic()

    def fetch(self, url):
        if self.requests >= MAX_REQUESTS or time.monotonic() - self.started >= MAX_SECONDS:
            raise TimeoutError('Orçamento de resolução atingido; tentar na próxima atualização')
        self.requests += 1
        return safe_fetch(self.session, url)

    def load_board(self, board):
        if board in self.boards:
            return self.boards[board]
        queue = [f'https://{board}.gupy.io/']
        seen, rows = set(), {}
        total = 0
        try:
            while queue:
                if len(seen) >= MAX_PAGES:
                    raise ValueError('Limite de paginação atingido')
                url = queue.pop(0)
                if url in seen:
                    continue
                seen.add(url)
                response = self.fetch(url)
                if response.status_code != 200:
                    raise ValueError(f'HTTP {response.status_code} no board')
                # A redirect to another employer/login must not become evidence.
                final = urlparse(getattr(response, 'url', None) or url)
                if final.netloc != f'{board}.gupy.io' or final.path not in {'', '/'}:
                    raise ValueError('Board redirecionou para outro destino')
                page, more, has_next, page_total = board_page(response.text, board)
                rows.update(page)
                total = max(total, page_total)
                unseen = more - seen
                if has_next and not unseen:
                    raise ValueError('Paginação dinâmica não disponível no HTML público')
                queue.extend(sorted(unseen - set(queue)))
            if not rows or total > len(rows):
                raise ValueError('Lista pública vazia ou incompleta; requer outro adaptador')
            result = (rows, None)
        except Exception as exc:
            result = ({}, f'{type(exc).__name__}: {exc}')
        self.boards[board] = result
        return result

    def load_detail(self, url):
        if url not in self.details:
            response = self.fetch(url)
            if response.status_code != 200:
                raise ValueError(f'HTTP {response.status_code} na vaga candidata')
            requested = urlparse(url)
            board = requested.hostname.split('.')[0]
            if job_url(getattr(response, 'url', None) or url, board) != url:
                raise ValueError('Vaga redirecionou para outro destino')
            posting = extract_jobposting(BeautifulSoup(response.text, 'html.parser'))
            if not posting:
                raise ValueError('Candidata sem JobPosting legível')
            self.details[url] = posting
        return self.details[url]

    def resolve(self, job):
        board = board_for(job.get('company'))
        outcome = {'state': 'pending', 'checkedAt': datetime.now(timezone.utc).isoformat(),
                   'discoveryUrl': job.get('source'), 'candidates': []}
        if not board:
            return {**outcome, 'reason': 'Empresa sem board Gupy cadastrado'}
        rows, error = self.load_board(board)
        if error:
            return {**outcome, 'state': 'fetch_failed', 'reason': error}
        urls = [url for url, title in rows.items()
                if not title or title_score(job.get('role'), title) >= .65]
        if len(urls) > MAX_DETAILS:
            return {**outcome, 'state': 'review_required', 'reason': 'Muitas candidatas; busca inconclusiva'}
        ranked = []
        failures = 0
        for url in urls:
            try:
                posting = self.load_detail(url)
                evidence = match_evidence(job, posting, board)
                if evidence:
                    ranked.append({'url': url, **evidence})
            except Exception:
                failures += 1
        ranked.sort(key=lambda row: row['score'], reverse=True)
        outcome['candidates'] = ranked[:5]
        if failures:
            return {**outcome, 'state': 'fetch_failed', 'reason': 'Candidatas inacessíveis; unicidade não confirmada'}
        if not ranked:
            return {**outcome, 'reason': 'Nenhuma correspondência suficiente no board'}
        best = ranked[0]
        ambiguous = len(ranked) > 1 and ranked[1]['score'] >= 70
        if best['score'] < 85 or ambiguous or not best['requirementsConfirmed']:
            return {**outcome, 'state': 'review_required', 'reason': 'Correspondência insuficiente ou ambígua'}
        checked = verify({**job, 'source': best['url']}, self.session)
        if checked.get('validationState') != 'confirmed':
            return {**outcome, 'reason': 'Fonte candidata não confirmou vaga aberta',
                    'verificationReason': checked.get('verificationReason')}
        return {**outcome, 'state': 'resolved', 'reason': 'Empresa, título e requisitos correspondentes; fonte confirmada',
                'url': best['url'], 'verification': checked}


def match_evidence(job, posting, board):
    organization = posting.get('hiringOrganization') or {}
    if not isinstance(organization, dict) or board_for(organization.get('name')) != board:
        return None
    title = posting.get('title', '')
    if senior_conflict(title, ''):
        return None
    if ('pcd' in normalized(title)) != ('pcd' in normalized(job.get('role'))):
        return None
    similarity = title_score(job.get('role'), title)
    if similarity < .8:
        return None
    req, _ = split_requirements(None, posting)
    original = job.get('requirements') or []
    # Short legacy lists (Python, SQL...) are compared against the official
    # requirement section, never against benefits or the employer presentation.
    tokens = set(normalized(' '.join(req)).split())
    items = [set(normalized(x).split()) for x in original if normalized(x)]
    coverage = sum(len(item & tokens) / len(item) >= .75 for item in items) / max(1, len(items))
    # Legacy summaries may include duties (credit/fraud/PLD), not only skills.
    # Use only the responsibilities section as additional evidence, not the
    # generic employer biography or benefits that appear on every posting.
    description = BeautifulSoup(str(posting.get('description') or ''), 'html.parser')
    duties = []
    for heading in description.find_all(['h2', 'h3', 'h4']):
        if re.search(r'responsabilidades|atribuicoes|responsibilities', normalized(heading.get_text())):
            for sibling in heading.find_next_siblings():
                if sibling.name in {'h2', 'h3', 'h4'}:
                    break
                duties.append(sibling.get_text(' ', strip=True))
    full_tokens = tokens | set(normalized(' '.join(duties)).split())
    description_coverage = sum(len(item & full_tokens) / len(item) >= .75 for item in items) / max(1, len(items))
    location = location_fields(posting, '')['location']
    known_location = normalized(job.get('location'))
    location_score = 0
    if known_location and known_location not in {'nao informada', 'nao informado'}:
        expected_city = normalized(re.split(r'[,/|]', job['location'])[0])
        actual_city = normalized((location or '').split(',')[0])
        if actual_city and expected_city != actual_city:
            return None
        location_score = 15 if actual_city else 0
    else:
        location_score = None
    # Dates are supporting metadata, not proof of identity: repostings differ.
    denominator = 85 if location_score is None else 100
    score = round(100 * (55 * similarity + 20 * coverage + 10 * description_coverage + (location_score or 0)) / denominator, 1)
    return {'score': score, 'title': title, 'titleSimilarity': round(similarity, 3),
            'requirementCoverage': round(coverage, 3),
            'descriptionCoverage': round(description_coverage, 3),
            'requirementsConfirmed': len(req) >= 3 and len(items) >= 3 and coverage >= .5 and description_coverage >= .75,
            'location': location}


def promote_source(job, outcome):
    """Change the primary URL, not the stable key used by applications/history."""
    job['sourceResolution'] = {k: v for k, v in outcome.items() if k != 'verification'}
    if outcome['state'] == 'review_required' and not job.get('reviewRequired'):
        job['reviewRequired'] = True
        job['reviewReason'] = 'Fonte oficial: ' + outcome['reason']
        job['sourceResolutionReviewReason'] = job['reviewReason']
    if outcome['state'] != 'resolved':
        return
    owned_reason = job.pop('sourceResolutionReviewReason', None)
    if owned_reason and job.get('reviewReason') == owned_reason:
        job['reviewRequired'] = False
        job.pop('reviewReason', None)
    original = dict(job)
    job.update(outcome['verification'])
    job.update(source=outcome['url'], sourceStructured=True, sourceName='Gupy',
               sourceProvider='gupy', sourceOfficial=True, sourcePriority=4)
    job['sources'] = merge_source_records(job, original)


def restore_source(previous, merged):
    """Curated input still carries LinkedIn: don't undo a confirmed promotion."""
    resolution = previous.get('sourceResolution') or {}
    if (resolution.get('state') == 'resolved'
            and resolution.get('discoveryUrl') == merged.get('source')
            and resolution.get('url') == previous.get('source')):
        for field in ('source', 'sourceStructured', 'sourceName', 'sourceProvider',
                      'sourceOfficial', 'sourcePriority', 'sources', 'requirements',
                      'differentials', 'location', 'modality', 'publishedAt', 'validThrough'):
            if field in previous:
                merged[field] = previous[field]
    return merged


def resolve_catalog(jobs, session):
    resolver = GupyResolver(session)
    counts = {}
    for job in jobs:
        host = urlparse(job.get('source', '')).hostname or ''
        if (not (host == 'linkedin.com' or host.endswith('.linkedin.com'))
                or job.get('excluded') or job.get('status') == 'Encerrada'):
            continue
        outcome = resolver.resolve(job)
        promote_source(job, outcome)
        state = outcome['state']
        counts[state] = counts.get(state, 0) + 1
    return counts
