"""Conservative extraction and verification. No successful check is inferred from HTTP 200 alone."""
from __future__ import annotations
import ipaddress, socket, re, unicodedata, json
from datetime import datetime, timezone
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from rules import VALIDATION_CLOSED, VALIDATION_CONFIRMED, VALIDATION_PENDING


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s or '')) if unicodedata.category(c) != 'Mn').lower()


def senior_conflict(title, description):
    t=norm(title)
    return bool(
        re.search(r'\b(pleno|senior|staff|lead|especialista|principal)\b', t)
        or re.search(r'\b(?:spec|analyst|analista|developer|desenvolvedor|engenheir[oa])\s+(?:ii|iii|iv|v|[2-9])\b', t)
        or re.search(
            r'(?:experiencia\s+(?:como|de|em nivel)\s+|nivel de experiencia\s*[:\-]?\s*)'
            r'(?:profissional\s+)?(?:pleno|senior)',
            norm(description),
        )
    )


SECTION_STOP_RE = re.compile(
    r'beneficios|responsabilidades|atribuicoes|oferecemos|o que oferecemos|sobre (?:nos|a empresa|o time)|'
    r'processo seletivo|etapas do processo|etapas|como funciona|por que trabalhar|porque trabalhar|'
    r'nossa cultura|cultura e valores|ambiente de trabalho|informacoes adicionais|informacoes da vaga'
)

NON_REQUIREMENT_RE = re.compile(
    r'\bvale[- ]?(?:transporte|refeicao|alimentacao)\b|\bplano (?:medico|de saude|odontologico)\b|'
    r'\bseguro de vida\b|\bprevidencia privada\b|\bplr\b|\blicenca (?:maternidade|paternidade)\b|'
    r'\bdescontos? exclusivos?\b|\bgympass\b|\bwellhub\b|\btotalpass\b|'
    r'\bteste cognitivo\b|\bvideo entrevista\b|\bentrevista com\b|\bentrevista focada\b|'
    r'\bprocesso seletivo\b|\brecrutamento\b|\bavaliacao tecnica\b|\betapas? do processo\b|'
    r'\bambiente dinamico\b|\bliberdade para trilhar\b|\bespaco para desenvolvimento\b'
)

TECHNICAL_TITLE_RE = re.compile(
    r'software|backend|back-end|developer|desenvolvedor|engenharia|dados|data|cloud|sre|devops|'
    r'automacao|python|java|\.net|c#|sistemas|infraestrutura|security|seguranca|qa|qualidade|quant'
)

HARD_SKILL_RE = re.compile(
    r'\bpython\b|\bsql\b|\bjava\b|\.net|\bc#\b|javascript|typescript|node|react|angular|'
    r'\bapi\b|\bapis\b|\brest\b|\bgit\b|github|gitlab|aws|azure|gcp|cloud|docker|kubernetes|'
    r'kafka|rabbitmq|spring|banco de dados|database|tableau|power bi|metabase|spark|databricks|'
    r'machine learning|ia generativa|inteligencia artificial|linux|terraform|ci/cd|devops|'
    r'microsservic|microservice|observabilidade|security|seguranca|oracle|postgres|mysql|trino|starburst'
)


def is_non_requirement_item(text):
    return bool(NON_REQUIREMENT_RE.search(norm(text)))


def requirements_quality_conflict(title, requirements):
    """Reject obviously polluted or non-informative requirement sets for technical roles."""
    reqs = [str(x).strip() for x in (requirements or []) if str(x).strip()]
    if not reqs:
        return True
    bad = sum(is_non_requirement_item(x) for x in reqs)
    if bad >= 2 and bad / len(reqs) >= 0.25:
        return True
    if TECHNICAL_TITLE_RE.search(norm(title)) and not any(HARD_SKILL_RE.search(norm(x)) for x in reqs):
        return True
    return False


def split_requirements(soup, posting=None):
    if posting and posting.get('description'):
        root = BeautifulSoup(str(posting['description']), 'html.parser')
    else:
        root = soup.select_one('.show-more-less-html__markup, .description__text, [class*="description"]') if soup else None
    if root is None:
        return [], []
    req, diff = [], []
    mode = None
    for node in root.find_all(['h2', 'h3', 'h4', 'strong', 'b', 'p', 'li']):
        if node.find_parent('li') or (node.name == 'p' and node.find(['strong', 'b'])):
            continue
        t = re.sub(r'\s+', ' ', node.get_text(' ', strip=True)).strip()
        n = norm(t)
        if len(t) < 130:
            if re.search(r'diferencia|nice.to.have|sera um plus|desejave', n):
                mode = 'diff'
                continue
            if re.search(r'requisitos|qualificaco|requirements|o que (?:buscamos|precisa)|precisamos que', n):
                mode = 'req'
                continue
            if SECTION_STOP_RE.search(n):
                mode = None
                continue
        if node.name not in ['li', 'p'] or not (3 <= len(t) <= 700):
            continue
        if is_non_requirement_item(t):
            continue
        target = diff if mode == 'diff' else req if mode == 'req' else None
        if target is not None and t not in target:
            target.append(t)
    return req[:30], diff[:20]


def location_fields(posting, text):
    p = posting or {}
    locations = p.get('jobLocation', [])
    if isinstance(locations, dict):
        locations = [locations]
    places = []
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        a = loc.get('address', {})
        if isinstance(a, dict):
            places.append(', '.join(str(a[k]) for k in ['addressLocality', 'addressRegion', 'addressCountry'] if a.get(k)))
    n = norm(text)
    mode = (
        'Remoto' if p.get('jobLocationType') == 'TELECOMMUTE'
        else 'Híbrido' if re.search(r'\bhibrid[oa]\b', n)
        else 'Presencial' if re.search(r'\bpresencial\b', n)
        else 'Remoto' if re.search(r'(?:trabalho|modelo|work)\s+(?:100%\s+)?(?:remoto|remote)', n)
        else None
    )
    return {
        'location': ' / '.join(filter(None, places)) or None,
        'modality': mode,
        'publishedAt': p.get('datePosted'),
        'validThrough': p.get('validThrough'),
    }


def public_url(url):
    p = urlparse(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        return False
    try:
        return all(ipaddress.ip_address(x[4][0]).is_global for x in socket.getaddrinfo(p.hostname, 443))
    except (OSError, ValueError):
        return False


def safe_fetch(session, url):
    for _ in range(5):
        if not public_url(url):
            raise ValueError('URL não pública')
        response = session.get(url, timeout=15, allow_redirects=False)
        if response.status_code not in (301, 302, 303, 307, 308):
            return response
        from urllib.parse import urljoin
        url = urljoin(url, response.headers.get('Location', ''))
    raise ValueError('Redirecionamentos excessivos')


def verify(job, session):
    at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    result = {
        'lastCheckedAt': at,
        'status': 'Possivelmente encerrada',
        'validationState': VALIDATION_PENDING,
        'verificationReason': 'Não foi possível confirmar',
    }
    try:
        response = safe_fetch(session, job.get('source', ''))
        if response.status_code in (404, 410):
            return {**result, 'status': 'Encerrada', 'validationState': VALIDATION_CLOSED, 'lastVerifiedAt': at, 'verificationReason': 'Anúncio removido (404/410)'}
        if response.status_code != 200:
            return {**result, 'verificationReason': f'HTTP {response.status_code}; não confirma encerramento'}
        soup = BeautifulSoup(response.text, 'html.parser')
        text = norm(soup.get_text(' ', strip=True))
        if re.search(r'nao aceita mais candidaturas|no longer accepting applications|vaga (?:foi )?encerrada|job (?:is )?no longer available', text):
            return {**result, 'status': 'Encerrada', 'validationState': VALIDATION_CLOSED, 'lastVerifiedAt': at, 'verificationReason': 'Encerramento explícito'}
        posting = None

        def find(o):
            if isinstance(o, dict):
                if o.get('@type') == 'JobPosting':
                    return o
                for v in o.values():
                    r = find(v)
                    if r:
                        return r
            if isinstance(o, list):
                for v in o:
                    r = find(v)
                    if r:
                        return r

        for script in soup.select('script[type="application/ld+json"]'):
            try:
                posting = find(json.loads(script.get_text()))
            except (ValueError, TypeError):
                continue
            if posting:
                break
        if posting:
            valid = posting.get('validThrough')
            if valid:
                try:
                    expiry = datetime.fromisoformat(valid.replace('Z', '+00:00'))
                    if not expiry.tzinfo:
                        expiry = expiry.replace(tzinfo=timezone.utc)
                    if expiry < datetime.now(timezone.utc):
                        return {**result, 'status': 'Encerrada', 'validationState': VALIDATION_CLOSED, 'lastVerifiedAt': at, 'verificationReason': 'Prazo expirado'}
                except ValueError:
                    pass
            # A generic page or another job must not validate this record.
            title = norm(posting.get('title', ''))
            expected = norm(job.get('role', ''))
            from difflib import SequenceMatcher
            if title and SequenceMatcher(None, title, expected).ratio() >= .65 and len(str(posting.get('description', ''))) > 150:
                req, diff = split_requirements(soup, posting)
                extracted = {}
                if len(req) >= 3 and not requirements_quality_conflict(posting.get('title') or job.get('role', ''), req):
                    extracted = {'requirements': req, 'differentials': diff}
                return {
                    **result,
                    'status': 'Ativa',
                    'validationState': VALIDATION_CONFIRMED,
                    'lastVerifiedAt': at,
                    'verificationReason': 'JobPosting correspondente e válido',
                    **location_fields(posting, text),
                    **extracted,
                }
        return {**result, 'verificationReason': 'Página acessível, sem evidência suficiente de vaga aberta'}
    except Exception as exc:
        return {**result, 'verificationReason': f'Falha de validação: {type(exc).__name__}'}
