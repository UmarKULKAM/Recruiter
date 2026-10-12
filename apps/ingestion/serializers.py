"""Checks Gemini's response schema cannot express for JOB_PARSER."""

import re

from apps.ingestion.schemas import (
    Compensation,
    DiscriminatoryCriterion,
    JobParser,
    LegitimacyTier,
)

# A fee, deposit, or "must pay to apply" line is not stated pay.
_PAY_STATED = re.compile(
    r"("
    r"\b(salary|salaries|wage|wages|remuneration|stipend|honorarium)\b"
    r"|"
    r"\b(gross|net)\b.{0,40}\b(month|monthly|annum|annual|hour|hourly|week|weekly|day|daily)\b"
    r"|"
    r"\b(ugx|usd|eur|gbp|kes|rwf|tzs)\b.{0,40}\b"
    r"(month|monthly|annum|annual|hour|hourly|week|weekly|per)\b"
    r"|"
    r"\b(per month|per annum|a month|monthly salary|hourly rate)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_CRITERION_ALIASES: dict[str, DiscriminatoryCriterion] = {
    "age": "age",
    "sex": "sex",
    "gender": "sex",
    "tribe": "tribe",
    "religion": "religion",
    "marital status": "marital_status",
    "marital_status": "marital_status",
    "health": "health",
    "photo": "photo",
    "photograph": "photo",
    "race": "race",
    "colour": "colour",
    "color": "colour",
    "political opinion": "political_opinion",
    "political_opinion": "political_opinion",
    "national extraction": "national_extraction",
    "national_extraction": "national_extraction",
    "social origin": "social_origin",
    "social_origin": "social_origin",
    "hiv": "hiv",
    "hiv status": "hiv",
    "appearance": "appearance",
}


def legitimacy_for(
    *,
    charges_applicant: bool | None,
    employer_hidden: bool,
    contact_channel: str | None,
) -> LegitimacyTier:
    """high, then review, then clear. A personal inbox alone is review."""
    if charges_applicant is True or employer_hidden:
        return "high"
    if contact_channel == "personal_inbox":
        return "review"
    return "clear"


def serialize_job_parser(parsed: JobParser, *, source_text: str) -> JobParser:
    employer_name = _blank_to_none(parsed.employer_name)
    employer_hidden = parsed.employer_hidden or employer_name is None
    if employer_hidden:
        employer_name = None

    skills, flags = _skills_without_discriminatory_flags(
        parsed.stated_skills,
        list(parsed.discriminatory_criteria),
    )
    return parsed.model_copy(
        update={
            "employer_name": employer_name,
            "employer_hidden": employer_hidden,
            "compensation": _null_unstated_pay(parsed.compensation, source_text),
            "stated_skills": skills,
            "discriminatory_criteria": flags,
            "legitimacy": legitimacy_for(
                charges_applicant=parsed.charges_applicant,
                employer_hidden=employer_hidden,
                contact_channel=parsed.contact_channel,
            ),
        }
    )


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _null_unstated_pay(
    compensation: Compensation | None,
    source_text: str,
) -> Compensation | None:
    if compensation is None:
        return None
    if not _PAY_STATED.search(source_text):
        return None
    stated = (
        compensation.verbatim
        or compensation.amount_low
        or compensation.amount_high
        or compensation.currency
    )
    if not stated:
        return None
    return compensation


def _criterion_for_skill(skill: str) -> DiscriminatoryCriterion | None:
    key = re.sub(r"[\s_-]+", " ", skill.strip().lower()).strip()
    aliased = _CRITERION_ALIASES.get(key)
    if aliased is None:
        aliased = _CRITERION_ALIASES.get(key.replace(" ", "_"))
    return aliased


def _skills_without_discriminatory_flags(
    skills: list[str] | None,
    flags: list[DiscriminatoryCriterion],
) -> tuple[list[str] | None, list[DiscriminatoryCriterion]]:
    kept: list[str] = []
    seen_skills: set[str] = set()
    seen_flags = set(flags)
    ordered_flags = list(flags)
    for skill in skills or []:
        criterion = _criterion_for_skill(skill)
        if criterion is not None:
            if criterion not in seen_flags:
                seen_flags.add(criterion)
                ordered_flags.append(criterion)
            continue
        if skill in seen_skills:
            continue
        seen_skills.add(skill)
        kept.append(skill)

    deduped_flags: list[DiscriminatoryCriterion] = []
    seen_flags = set()
    for flag in ordered_flags:
        if flag in seen_flags:
            continue
        seen_flags.add(flag)
        deduped_flags.append(flag)
    return (kept or None), deduped_flags
