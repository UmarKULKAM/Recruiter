"""Keyword overlap. Django owns this rubric. The model does not.

Version ``keyword-overlap-1`` normalizes stated skills from the job and from
the CV, then stores the percentage. It does not ask the model for a matched
list, a missing list, or a percentage.

1. Unicode NFKC, then casefold, then trim.
2. Treat ``_``, ``-``, ``.``, ``/``, ``,``, and ``&`` as spaces.
3. Keep letters, numbers, ``+``, and ``#``. Drop every other character.
4. Collapse whitespace. Drop a phrase that becomes empty.
5. Drop a phrase that is only a discriminatory criterion. Those criteria are
   not match features. There is no synonym table.
6. Drop a phrase that contains a stored identity value (name, phone, email,
   national ID, photo reference, or date of birth).
7. Deduplicate each side, keeping the first occurrence and the job's order.
8. A job phrase matches when its normalized form equals a CV phrase.
   Equality is exact. A longer phrase is not a match.
9. When the job list is missing, or nothing remains after those drops, or the
   CV list was never recorded, the percentage is null. An empty CV list is a
   recorded list, and the percentage is then 0. Otherwise the percentage is
   ``matched / job phrases * 100``, rounded half up to two decimal places.
"""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

RUBRIC_VERSION = "keyword-overlap-1"

# Normalized closed list, plus the aliases the parser already refuses to treat
# as skills. Exact phrase only: "age verification" is not this list.
EXCLUDED_PHRASES = frozenset(
    {
        "age",
        "sex",
        "gender",
        "tribe",
        "religion",
        "marital status",
        "health",
        "photo",
        "photograph",
        "race",
        "colour",
        "color",
        "political opinion",
        "national extraction",
        "social origin",
        "hiv",
        "hiv status",
        "appearance",
    }
)


@dataclass(frozen=True)
class KeywordOverlap:
    percentage: Decimal | None
    rubric_version: str
    matched_keywords: list[str]
    missing_keywords: list[str]


def normalize_skill(phrase: str) -> str:
    """One stated skill under rubric ``keyword-overlap-1``."""
    text = unicodedata.normalize("NFKC", phrase).casefold().strip()
    kept: list[str] = []
    for char in text:
        if char.isalnum() or char in "+#":
            kept.append(char)
        elif char.isspace() or char in "_-./,&":
            kept.append(" ")
    return " ".join("".join(kept).split())


def is_discriminatory_phrase(phrase: str) -> bool:
    normalized = normalize_skill(phrase)
    return bool(normalized) and normalized in EXCLUDED_PHRASES


def keyword_overlap(
    job_stated_skills,
    cv_stated_skills,
    *,
    identity_values: Sequence[str] = (),
) -> KeywordOverlap:
    """Percentage from the two stored phrase lists. Null when it cannot be computed."""
    job_recorded = isinstance(job_stated_skills, list)
    cv_recorded = isinstance(cv_stated_skills, list)
    job_keys = (
        _normalize_list(job_stated_skills, identity_values) if job_recorded else []
    )
    cv_keys = (
        set(_normalize_list(cv_stated_skills, identity_values)) if cv_recorded else set()
    )
    if not job_recorded or not job_keys or not cv_recorded:
        return KeywordOverlap(
            percentage=None,
            rubric_version=RUBRIC_VERSION,
            matched_keywords=[],
            missing_keywords=[],
        )
    matched = [key for key in job_keys if key in cv_keys]
    missing = [key for key in job_keys if key not in cv_keys]
    percentage = (
        Decimal(len(matched)) * Decimal(100) / Decimal(len(job_keys))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return KeywordOverlap(
        percentage=percentage,
        rubric_version=RUBRIC_VERSION,
        matched_keywords=matched,
        missing_keywords=missing,
    )


def _normalize_list(skills: Sequence, identity_values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in skills:
        if not isinstance(item, str):
            continue
        normalized = normalize_skill(item)
        if not normalized or normalized in seen:
            continue
        if normalized in EXCLUDED_PHRASES or _contains_identity(
            item, normalized, identity_values
        ):
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _contains_identity(raw: str, normalized: str, identity_values: Sequence[str]) -> bool:
    raw_fold = raw.casefold()
    for value in identity_values:
        if not value or not value.strip():
            continue
        folded = value.casefold()
        if folded in raw_fold or folded in normalized:
            return True
        normalized_value = normalize_skill(value)
        if normalized_value and (
            normalized_value == normalized or normalized_value in normalized
        ):
            return True
    return False
