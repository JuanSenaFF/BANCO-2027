"""Deterministic normalization for job requirements.

The original sentence is always preserved. Structured fields are evidence about
what was explicitly present in the posting; missing information stays ``None``
instead of being guessed.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


SCHEMA_VERSION = 2
REQUIREMENT_TYPES = {"mandatory", "differential", "eliminatory"}
CATEGORIES = {"technical", "experience", "education", "language", "location", "modality", "eligibility", "behavioral", "domain", "other"}
RELATIONS = {"single", "any", "all"}


def norm(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", value.lower()).strip()


@dataclass(frozen=True)
class Technology:
    pattern: str
    skill: str
    subskill: str | None = None
    profile_skill_id: str | None = None


# Specific technologies precede their ecosystems. A Spring requirement maps to
# the Spring profile skill, not to generic Java, which prevents false matches.
TECHNOLOGIES = [
    Technology(r"\bspring\s*boot\b", "Java", "Spring Boot", "spring"),
    Technology(r"\bspring\s*(?:data|mvc|security|test)\b", "Java", "Spring", "spring"),
    Technology(r"\bhibernate\b|\bjpa\b", "Java", "Hibernate/JPA", "spring"),
    Technology(r"\bjakarta\s*ee\b|\bjava\s*ee\b|\bj2ee\b", "Java", "Jakarta EE"),
    Technology(r"java server faces|\bjsf\b", "Java", "JavaServer Faces"),
    Technology(r"\bjboss\b|\bapache\b", "Java", "Servidor de aplicação"),
    Technology(r"\bjunit\b|\bmockito\b", "Testes", "JUnit/Mockito", "tests"),
    Technology(r"\bpytest\b", "Testes", "pytest", "tests"),
    Technology(r"\bjmeter\b", "Testes", "JMeter", "tests"),
    Technology(r"phpunit|\bpest\b", "Testes", "PHPUnit/Pest", "tests"),
    Technology(r"\bselenium\b", "Automação", "Selenium", "auto"),
    Technology(r"\bpl\s*/?\s*sql\b", "SQL", "PL/SQL", "sql"),
    Technology(r"\bpostgres(?:ql)?\b", "SQL", "PostgreSQL", "sql"),
    Technology(r"\bmysql\b", "SQL", "MySQL", "sql"),
    Technology(r"\boracle\b", "SQL", "Oracle", "sql"),
    Technology(r"\bmongodb\b", "Banco de dados", "MongoDB"),
    Technology(r"\bredis\b", "Banco de dados", "Redis"),
    Technology(r"\bamazon s3\b|\baws s3\b|\bs3\b", "AWS", "Amazon S3", "aws"),
    Technology(r"\baws lambda\b|\blambda\b", "AWS", "AWS Lambda", "aws"),
    Technology(r"\baws sqs\b|\bsqs\b", "AWS", "Amazon SQS", "aws"),
    Technology(r"\baws sns\b|\bsns\b", "AWS", "Amazon SNS", "aws"),
    Technology(r"\bcloudwatch\b", "AWS", "CloudWatch", "aws"),
    Technology(r"\baws\b|amazon web services", "AWS", None, "aws"),
    Technology(r"\bazure\b", "Azure", None, "azure"),
    Technology(r"\bgcp\b|google cloud", "GCP", None, "gcp"),
    Technology(r"\bdocker\b|\bpodman\b", "Contêineres", "Docker/Podman", "docker"),
    Technology(r"\bkubernetes\b|\beks\b", "Contêineres", "Kubernetes", "k8s"),
    Technology(r"\bterraform\b|cloudformation|infrastructure as code|\biac\b", "Infraestrutura como código", "Terraform/IaC", "iac"),
    Technology(r"\bkafka\b|rabbitmq|mensageria|\bsqs\b|\bsns\b", "Mensageria", None, "msg"),
    Technology(r"observabilidade|\bgrafana\b|\bsplunk\b|dynatrace|new relic|datadog|\bkibana\b", "Observabilidade", None, "obs"),
    Technology(r"\bci\s*/\s*cd\b|\bci\b|github actions|gitlab ci|\bjenkins\b|devsecops", "CI/CD", None, "cicd"),
    Technology(r"microsservic|microservice", "Microsserviços", None, "micro"),
    Technology(r"\brest(?:ful)?\b|\bapis?\b|\bsoap\b|\bopenapi\b|\bswagger\b", "APIs", "REST/Integração", "api"),
    Technology(r"\bgit\b|\bgithub\b|\bgitlab\b", "Controle de versão", "Git", "git"),
    Technology(r"testes?|testing|\btdd\b|test automation|homologacao", "Testes", None, "tests"),
    Technology(r"orientacao a objetos|design patterns?|\bsolid\b|clean code|code review|qualidade de codigo|\bdry\b|logica de programacao|estruturas de dados", "Design de software", "POO/Design", "design"),
    Technology(r"\blinux\b|shell script|\bbash\b", "Linux", None, "linux"),
    Technology(r"seguranca|security|\bowasp\b|\biam\b|\boauth\b|\bjwt\b|ping identity|\blgpd\b|\bgdpr\b", "Segurança", None, "sec"),
    Technology(r"\bexcel\b", "Dados/BI", "Excel", "data"),
    Technology(r"\bpower\s*bi\b", "Dados/BI", "Power BI", "data"),
    Technology(r"\btableau\b", "Dados/BI", "Tableau", "data"),
    Technology(r"\bdatabricks\b", "Dados/BI", "Databricks", "data"),
    Technology(r"\bspark\b|\bpyspark\b", "Dados/BI", "Spark", "data"),
    Technology(r"machine learning|inteligencia artificial|ia generativa|generative ai|\bia\b|\bllms?\b|prompt engineering|vertex ai|chatbots?|assistentes virtuais", "IA/ML", None, "ai"),
    Technology(r"automacao|automation|\brpa\b|\buipath\b|\bn8n\b|\bbotcity\b", "Automação", None, "auto"),
    Technology(r"troubleshooting|debugging|incidente|sustentacao|producao|\bdeploy\b|\brollback\b|\bgmud\b|suporte (?:a sistemas|tecnico)|\bitil\b", "Produção", "Troubleshooting", "prod"),
    Technology(r"monitoramento|metricas e dashboards", "Observabilidade", None, "obs"),
    Technology(r"modelagem de dados|manipulacao de dados|analise de dados|visualizacao de dados|estatistica|data warehouse|data lake|lakehouse|governanca de dados|qualidade de dados|analise (?:descritiva|preditiva|quantitativa)|indicadores|\bkpis?\b", "Dados/BI", None, "data"),
    Technology(r"bancos? relacionais|banco de dados|\bnosql\b|administracao de banco de dados|backup/restore|replicacao", "Banco de dados", None, "sql"),
    Technology(r"integracoes? entre sistemas|fluxos e jornadas digitais", "APIs", "Integração", "api"),
    Technology(r"\bhtml5?\b|\bcss3?\b|webpack|\bvite\b", "Web", "Frontend"),
    Technology(r"metodologias ageis|\bscrum\b|\bkanban\b", "Métodos ágeis"),
    Technology(r"\bpython\b", "Python", None, "python"),
    Technology(r"\bjava\b", "Java", None, "java"),
    Technology(r"\.net\b|\bc#\b|asp\.net", ".NET", "C#/.NET", "dotnet"),
    Technology(r"\bnode(?:\.js|js)?\b", "JavaScript", "Node.js", "js"),
    Technology(r"\btypescript\b", "JavaScript", "TypeScript", "js"),
    Technology(r"\bjavascript\b", "JavaScript", None, "js"),
    Technology(r"\breact(?:\.js)?\b", "JavaScript", "React"),
    Technology(r"\bangular\b", "JavaScript", "Angular"),
    Technology(r"\bvue(?:\.js)?\b", "JavaScript", "Vue.js"),
    Technology(r"\bgo(?:lang)?\b", "Go"),
    Technology(r"\bcobol\b", "COBOL"),
    Technology(r"\bphp\b", "PHP"),
    Technology(r"\blaravel\b", "PHP", "Laravel"),
    Technology(r"\bsalesforce\b", "Salesforce"),
    Technology(r"\bsql\b", "SQL", None, "sql"),
    Technology(r"\bcloud\b|\bnuvem\b", "Cloud", None, "cloud"),
]

LEVEL_PATTERNS = [
    (4, r"especialista|expert|expertise profunda|arquitetura avancada"),
    (3, r"avancad|advanced|dominio|dominar|solido|proficien"),
    (2, r"intermedi"),
    (1, r"basic|basico|fundament|nocao|nocoes|introdutor|familiaridade"),
]
LEVEL_LABELS = {1: "básico", 2: "intermediário", 3: "avançado", 4: "especialista"}

EDUCATION_RE = re.compile(r"formacao|graduacao|ensino superior|bacharel|cursando|curso superior|degree")
LANGUAGE_RE = re.compile(r"\bingles\b|\benglish\b|\bespanhol\b|\bspanish\b|\bportugues\b|\bportuguese\b")
LOCATION_RE = re.compile(r"residir|residencia|localizacao|disponibilidade para (?:atuar|trabalhar|mudanca)|\bpresencial\b")
ELIGIBILITY_RE = re.compile(r"\bpcd\b|pessoa(?:s)? com deficiencia|vaga afirmativa|elegibilidade")
BEHAVIORAL_RE = re.compile(r"comunicacao|colabora|proativ|organizacao|autonomia|curiosidade|relacionamento|trabalho em equipe|senso de")
DOMAIN_RE = re.compile(r"mercado financeiro|meios de pagamento|fintech|bancari|credito|risco|fraude|investimento|renda fixa|compliance|\bfidc\b|ambiente sicoob")
TECHNICAL_GENERIC_RE = re.compile(r"backend|desenvolvimento de software|infraestrutura|redes|servidores|documentacao tecnica|regras de negocio|finops")
TRANSFERABLE_PROFILE_IDS = {"sql", "api", "git", "tests", "design", "docker", "cicd", "micro", "msg", "obs", "linux", "iac", "sec", "data", "auto", "prod", "cloud"}


def _technologies(text: str) -> list[dict]:
    normalized = norm(text)
    found = []
    seen = set()
    for tech in TECHNOLOGIES:
        if not re.search(tech.pattern, normalized, re.I):
            continue
        key = (tech.skill, tech.subskill, tech.profile_skill_id)
        if key in seen:
            continue
        seen.add(key)
        found.append({
            "skill": tech.skill,
            "subskill": tech.subskill,
            "profileSkillId": tech.profile_skill_id,
        })
    return found


def _required_level(text: str) -> int | None:
    normalized = norm(text)
    for level, pattern in LEVEL_PATTERNS:
        if re.search(pattern, normalized):
            return level
    return None


def _minimum_years(text: str) -> float | None:
    normalized = norm(text).replace(",", ".")
    match = re.search(r"(?:minim[oa]\s+(?:de\s+)?)?(\d+(?:\.\d+)?)\s*\+?\s*(?:anos?|years?|anos de experiencia)", normalized)
    return float(match.group(1)) if match else None


def normalize_requirement(text: str, mandatory: bool, position: int = 0, source: str = "description") -> dict:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    normalized = norm(clean)
    technologies = _technologies(clean)
    level = _required_level(clean)
    years = _minimum_years(clean)

    if ELIGIBILITY_RE.search(normalized):
        category = "eligibility"
    elif EDUCATION_RE.search(normalized):
        category = "education"
    elif LOCATION_RE.search(normalized):
        category = "location"
    elif LANGUAGE_RE.search(normalized) and not technologies:
        category = "language"
    elif technologies:
        category = "technical"
    elif TECHNICAL_GENERIC_RE.search(normalized):
        category = "technical"
    elif years is not None or "experiencia" in normalized or "vivencia" in normalized:
        category = "experience"
    elif BEHAVIORAL_RE.search(normalized):
        category = "behavioral"
    elif DOMAIN_RE.search(normalized):
        category = "domain"
    else:
        category = "other"

    eliminatory = mandatory and category in {"education", "location", "eligibility"}
    requirement_type = "eliminatory" if eliminatory else "mandatory" if mandatory else "differential"
    profile_ids = list(dict.fromkeys(t["profileSkillId"] for t in technologies if t["profileSkillId"]))
    unmapped_skill_count = sum(not t["profileSkillId"] for t in technologies)
    relation = "single"
    if len(technologies) > 1:
        relation = "any" if re.search(r"\bou\b|\bor\b", normalized) or "/" in clean else "all"
    primary = technologies[0] if technologies else {}
    transferable = category == "behavioral" or any(skill_id in TRANSFERABLE_PROFILE_IDS for skill_id in profile_ids)

    return {
        "text": clean,
        "position": position,
        "source": source,
        "mandatory": mandatory,
        "requirementType": requirement_type,
        "category": category,
        "skill": primary.get("skill"),
        "subskill": primary.get("subskill"),
        "skills": technologies,
        "profileSkillIds": profile_ids,
        "unmappedSkillCount": unmapped_skill_count,
        "relation": relation,
        "level": level,
        "levelLabel": LEVEL_LABELS.get(level),
        "minYears": years,
        "transferable": transferable,
    }


def normalize_job_requirements(job: dict) -> list[dict]:
    records = [
        normalize_requirement(text, True, position)
        for position, text in enumerate(job.get("requirements", []))
    ]
    records.extend(
        normalize_requirement(text, False, position)
        for position, text in enumerate(job.get("differentials", []))
    )
    title = norm(job.get("role", ""))
    if ELIGIBILITY_RE.search(title) and not any(record["category"] == "eligibility" for record in records):
        records.append(normalize_requirement(
            "Elegibilidade para vaga afirmativa: confirmar no anúncio",
            True,
            sum(record["mandatory"] for record in records),
            "title",
        ))
    validate_requirements(records)
    return records


def validate_requirements(records: list[dict]) -> None:
    """Fail a build instead of publishing a partially malformed contract."""
    for record in records:
        if not record.get("text"):
            raise ValueError("normalized requirement without text")
        if record.get("requirementType") not in REQUIREMENT_TYPES:
            raise ValueError(f"invalid requirement type: {record.get('requirementType')}")
        if record.get("category") not in CATEGORIES:
            raise ValueError(f"invalid requirement category: {record.get('category')}")
        if record.get("relation") not in RELATIONS:
            raise ValueError(f"invalid skill relation: {record.get('relation')}")
        if record.get("level") is not None and record["level"] not in {1, 2, 3, 4}:
            raise ValueError(f"invalid required level: {record.get('level')}")
        if record.get("minYears") is not None and record["minYears"] < 0:
            raise ValueError(f"invalid minimum experience: {record.get('minYears')}")
        if record.get("mandatory") != (record.get("requirementType") != "differential"):
            raise ValueError("mandatory flag conflicts with requirement type")
        if not isinstance(record.get("profileSkillIds"), list):
            raise ValueError("profileSkillIds must be a list")
        if not isinstance(record.get("unmappedSkillCount"), int) or record["unmappedSkillCount"] < 0:
            raise ValueError("unmappedSkillCount must be a non-negative integer")


def normalization_summary(jobs: list[dict]) -> dict:
    records = [record for job in jobs for record in job.get("requirementsStructured", [])]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "total": len(records),
        "mandatory": sum(record.get("requirementType") == "mandatory" for record in records),
        "differential": sum(record.get("requirementType") == "differential" for record in records),
        "eliminatory": sum(record.get("requirementType") == "eliminatory" for record in records),
        "technicalMapped": sum(record.get("category") == "technical" and bool(record.get("skill")) for record in records),
        "unmapped": sum(record.get("category") == "other" for record in records),
    }
