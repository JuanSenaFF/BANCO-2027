"""Conservative extraction and verification. No successful check is inferred from HTTP 200 alone."""
from __future__ import annotations
import html, ipaddress, socket, re, unicodedata, json
from datetime import datetime, timezone
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from rules import VALIDATION_CLOSED, VALIDATION_CONFIRMED, VALIDATION_PENDING
from company_policy import same_company_name


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s or '')) if unicodedata.category(c) != 'Mn').lower()


def parse_json_ld(raw):
    """Parse regular or HTML-entity-encoded JSON-LD without altering valid JSON."""
    payload = str(raw or '').strip()
    for _ in range(3):
        if not payload:
            return None
        try:
            return json.loads(payload)
        except (ValueError, TypeError):
            decoded = html.unescape(payload)
            if decoded == payload:
                return None
            payload = decoded
    return None


def find_jobposting(obj):
    if isinstance(obj, dict):
        if obj.get('@type') == 'JobPosting':
            return obj
        for value in obj.values():
            posting = find_jobposting(value)
            if posting:
                return posting
    elif isinstance(obj, list):
        for value in obj:
            posting = find_jobposting(value)
            if posting:
                return posting
    return None


def extract_jobposting(soup):
    """Return the first JobPosting from any supported JSON-LD representation."""
    if soup is None:
        return None
    for script in soup.select('script[type="application/ld+json"]'):
        posting = find_jobposting(parse_json_ld(script.string or script.get_text()))
        if posting:
            return posting
    return None


def senior_conflict(title, description):
    t=norm(title)
    return bool(
        re.search(r'\b(pl|pleno|sr|senior|staff|lead|especialista|specialist|principal)\b', t)
        # Some job boards render Roman II/III with lowercase ``l`` characters
        # (for example, "Analyst lll"). Treat those lookalikes as non-entry
        # levels too, without rejecting the legitimate suffix "I".
        or re.search(
            r'\b(?:spec|analyst|analista|developer|desenvolvedor|engenheir[oa]|software engineer|data engineer|engineer|engenheiro de software|engenheiro de dados)\s+'
            r'(?:ii|iii|iv|v|ll|lll|[2-9])\b',
            t,
        )
        or re.search(
            r'(?:experiencia\s+(?:como|de|em nivel)\s+|nivel de experiencia\s*[:\-]?\s*)'
            r'(?:profissional\s+)?(?:pleno|senior)',
            norm(description),
        )
    )


SECTION_STOP_RE = re.compile(
    r'beneficios|responsabilidades|atribuicoes|oferecemos|o que oferecemos|sobre (?:nos|a empresa|o time)|'
    r'processo seletivo|etapas do processo|etapas|como funciona|por que trabalhar|porque trabalhar|'
    r'nossa cultura|cultura e valores|ambiente de trabalho|informacoes adicionais|informacoes da vaga|'
    r'responsibilities|what (?:you will do|we offer)|about (?:us|the company|the team|the job)|'
    r'employment type|type of employment|job type|tipo de emprego'
)

REQUIREMENTS_HEADING_RE = re.compile(
    r'^(?:requisitos(?: e qualificacoes)?|qualificacoes|qualifications|requirements|minimum qualifications|'
    r'basic qualifications|required qualifications|what you need|who you are|o que (?:buscamos(?: em voce)?|voce precisa)|'
    r'precisamos que)\s*:?$'
)
DIFFERENTIALS_HEADING_RE = re.compile(
    r'^(?:diferenciais?|nice[ -]to[ -]have|preferred qualifications|sera um plus|desejaveis?)\s*:?$'
)
STOP_HEADING_RE = re.compile(
    r'^(?:beneficios|benefits|what we offer|offerings|responsabilidades|atribuicoes|responsibilities|'
    r'o que (?:voce vai fazer|fara)|oferecemos|sobre (?:nos|a empresa|o time)|about (?:us|the company|the team|the job)|'
    r'processo seletivo|etapas(?: do processo(?: seletivo)?)?|nossa cultura|informacoes adicionais|'
    r'employment type|type of employment|job type|tipo de emprego)\s*:?$'
)

NON_REQUIREMENT_RE = re.compile(
    r'\bvale[- ]?(?:transporte|refeicao|alimentacao)\b|\bplano (?:medico|de saude|odontologico)\b|'
    r'\bseguro de vida\b|\bprevidencia privada\b|\bplr\b|\blicenca (?:maternidade|paternidade)\b|'
    r'\bdescontos? exclusivos?\b|\bgympass\b|\bwellhub\b|\btotalpass\b|'
    r'\bteste cognitivo\b|\bvideo entrevista\b|\bentrevista com\b|\bentrevista focada\b|'
    r'\bviva bem\b|\buniversidade corporativa\b|\bparcerias? educacionais\b|\bparticipacao nos lucros\b|'
    r'\bcondicoes especiais em produtos\b|\bisencao de tarifas\b|\b\d+\s*[ªa]?\s*cesta alimentacao\b|\bauxilio creche\b|'
    r'\bprocesso seletivo\b|\brecrutamento\b|\bavaliacao tecnica\b|\betapas? do processo\b|'
    r'\bambiente dinamico\b|\bliberdade para trilhar\b|\bespaco para desenvolvimento\b|\bnivel de experiencia\b'
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


def deduplicate_requirement_containers(items):
    """Remove long parent text that merely concatenates multiple child items."""
    unique = []
    for item in items or []:
        text = re.sub(r'\s+', ' ', str(item or '')).strip()
        if text and text not in unique:
            unique.append(text)
    normalized = [norm(item) for item in unique]
    out = []
    for index, item in enumerate(unique):
        children = [
            other for other_index, other in enumerate(normalized)
            if other_index != index and len(other) >= 3 and other in normalized[index]
        ]
        if len(item) > 180 and len(children) >= 2:
            continue
        out.append(item)
    return out


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
        # Process a paragraph as a whole so inline emphasis does not discard
        # content ("Conhecimento em <strong>Python</strong>"). Ignore block
        # containers so their list items are not emitted twice.
        if node.find_parent('li') or (node.name in {'strong', 'b'} and node.find_parent('p')):
            continue
        if node.name == 'p' and node.find(['ul', 'ol', 'li']):
            continue
        t = re.sub(r'\s+', ' ', node.get_text(' ', strip=True)).strip()
        n = norm(t)
        if len(t) < 130:
            if DIFFERENTIALS_HEADING_RE.fullmatch(n):
                mode = 'diff'
                continue
            if STOP_HEADING_RE.fullmatch(n):
                mode = None
                continue
            if REQUIREMENTS_HEADING_RE.fullmatch(n):
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
    return deduplicate_requirement_containers(req)[:30], deduplicate_requirement_containers(diff)[:20]


def posting_company(posting):
    """Extract the employer name from schema.org hiringOrganization variants."""
    organization = (posting or {}).get('hiringOrganization')
    if isinstance(organization, list):
        organization = next((item for item in organization if item), None)
    if isinstance(organization, dict):
        return str(organization.get('name') or '').strip()
    return str(organization or '').strip()


def posting_company_matches(actual, expected):
    """Match registered aliases or a longer legal name with the same core words."""
    if same_company_name(actual, expected):
        return True
    ignored = {'a', 'as', 'da', 'das', 'de', 'do', 'dos', 'e', 'for', 'para', 'the', 'sa', 'ltda', 'inc'}
    actual_tokens = {token for token in re.findall(r'[a-z0-9]+', norm(actual)) if token not in ignored}
    expected_tokens = {token for token in re.findall(r'[a-z0-9]+', norm(expected)) if token not in ignored}
    return len(expected_tokens) >= 2 and expected_tokens <= actual_tokens


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


def verify(job, session, *, response=None):
    at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    result = {
        'lastCheckedAt': at,
        'status': 'Possivelmente encerrada',
        'validationState': VALIDATION_PENDING,
        'verificationReason': 'Não foi possível confirmar',
    }
    try:
        response = response if response is not None else safe_fetch(session, job.get('source', ''))
        if response.status_code in (404, 410):
            return {**result, 'status': 'Encerrada', 'validationState': VALIDATION_CLOSED, 'lastVerifiedAt': at, 'verificationReason': 'Anúncio removido (404/410)'}
        if response.status_code != 200:
            return {**result, 'verificationReason': f'HTTP {response.status_code}; não confirma encerramento'}
        soup = BeautifulSoup(response.text, 'html.parser')
        text = norm(soup.get_text(' ', strip=True))
        if re.search(r'nao aceita mais candidaturas|no longer accepting applications|vaga (?:foi )?encerrada|job (?:is )?no longer available', text):
            return {**result, 'status': 'Encerrada', 'validationState': VALIDATION_CLOSED, 'lastVerifiedAt': at, 'verificationReason': 'Encerramento explícito'}
        posting = extract_jobposting(soup)
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
            company = posting_company(posting)
            expected_company = str(job.get('company') or '').strip()
            from difflib import SequenceMatcher
            title_matches = bool(title and expected and SequenceMatcher(None, title, expected).ratio() >= .65)
            company_matches = bool(company and expected_company and posting_company_matches(company, expected_company))
            seniority_matches = not senior_conflict(posting.get('title', ''), posting.get('description', ''))
            if title_matches and company_matches and seniority_matches and len(str(posting.get('description', ''))) > 150:
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
            if company and expected_company and not company_matches:
                return {**result, 'verificationReason': 'JobPosting pertence a outra empresa'}
            if title_matches and not seniority_matches:
                return {**result, 'verificationReason': 'JobPosting tem senioridade fora do recorte'}
        return {**result, 'verificationReason': 'Página acessível, sem evidência suficiente de vaga aberta'}
    except Exception as exc:
        return {**result, 'verificationReason': f'Falha de validação: {type(exc).__name__}'}
