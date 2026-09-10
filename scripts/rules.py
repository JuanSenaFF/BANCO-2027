"""Shared catalog rules used by collection, validation and presentation."""

from __future__ import annotations

from datetime import datetime, timezone


# Requirements are intentionally conservative: a high score is an automatic
# duplicate, while the intermediate band remains visible for human review.
DUPLICATE_SIMILARITY = 0.90
REVIEW_SIMILARITY = 0.75
ACTIVE_VERIFICATION_DAYS = 7
RECHECK_AFTER_DAYS = 2

VALIDATION_PENDING = "pending"
VALIDATION_CONFIRMED = "confirmed"
VALIDATION_CLOSED = "closed"
VALIDATION_REVIEW = "review"


def age_days(value: str | None, now: datetime | None = None) -> float | None:
    """Return the age of an ISO timestamp in days, or None when invalid."""
    if not value:
        return None
    try:
        current = now or datetime.now(timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (current - parsed).total_seconds() / 86400)
    except (TypeError, ValueError):
        return None


def validation_state(job: dict) -> str:
    """Return the public validation state for a catalog record."""
    if job.get("reviewRequired"):
        return VALIDATION_REVIEW
    if job.get("status") == "Encerrada":
        return VALIDATION_CLOSED
    verified_age = age_days(job.get("lastVerifiedAt"))
    if job.get("status") == "Ativa" and verified_age is not None and verified_age <= ACTIVE_VERIFICATION_DAYS:
        return VALIDATION_CONFIRMED
    return VALIDATION_PENDING
