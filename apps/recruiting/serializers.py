"""Checks the response schema cannot express for RECRUITER_EVALUATION."""

from collections.abc import Sequence
from decimal import Decimal

from apps.ingestion.schemas import RecruiterEvaluation
from apps.recruiting.identity import contains_identity, redact_identity
from apps.recruiting.rubric import is_discriminatory_phrase


def serialize_recruiter_evaluation(
    parsed: RecruiterEvaluation,
    *,
    job_text: str,
    cv_text: str,
    posting_requires_regional_operational_experience: bool,
    candidate_shared_gross_monthly: Decimal | None,
    posting_compensation: dict | None,
    identity_values: Sequence[str] = (),
) -> RecruiterEvaluation:
    """Drop excerpts the source does not contain, and null fields the rules close.

    ``regional_operational_experience`` stays null unless the posting requires
    it and the quote is a contiguous copy from the CV. The salary note stays
    null unless the candidate shared a gross monthly figure and the posting
    states a gross monthly band.
    """
    observations = _observations(
        parsed,
        job_text=job_text,
        cv_text=cv_text,
        identity_values=identity_values,
    )
    topics = [
        topic
        for topic in parsed.verification_topics
        if not is_discriminatory_phrase(topic)
        and not contains_identity(topic, identity_values)
    ]
    return parsed.model_copy(
        update={
            "observations": observations,
            "verification_topics": topics,
            "regional_operational_experience": _regional_quote(
                parsed.regional_operational_experience,
                required=posting_requires_regional_operational_experience,
                cv_text=cv_text,
                identity_values=identity_values,
            ),
            "salary_alignment_note": _salary_note(
                parsed.salary_alignment_note,
                shared=candidate_shared_gross_monthly,
                compensation=posting_compensation,
                identity_values=identity_values,
            ),
            "recruiter_note": _recruiter_note(parsed.recruiter_note, identity_values),
        }
    )


def _observations(
    parsed: RecruiterEvaluation,
    *,
    job_text: str,
    cv_text: str,
    identity_values: Sequence[str],
) -> list:
    if not cv_text.strip():
        return []
    kept = []
    for item in parsed.observations:
        source_text = cv_text if item.source == "cv" else job_text
        if item.excerpt not in source_text:
            continue
        if is_discriminatory_phrase(item.observation) or is_discriminatory_phrase(
            item.excerpt
        ):
            continue
        if contains_identity(item.excerpt, identity_values) or contains_identity(
            item.observation, identity_values
        ):
            continue
        kept.append(item)
    return kept


def _regional_quote(
    quote: str | None,
    *,
    required: bool,
    cv_text: str,
    identity_values: Sequence[str],
) -> str | None:
    if not required or not quote:
        return None
    if quote not in cv_text:
        return None
    if contains_identity(quote, identity_values):
        return None
    return quote


def _salary_note(
    note: str | None,
    *,
    shared: Decimal | None,
    compensation: dict | None,
    identity_values: Sequence[str],
) -> str | None:
    if shared is None or not _gross_monthly_band(compensation):
        return None
    if not note or contains_identity(note, identity_values):
        return None
    return note


def _gross_monthly_band(compensation: dict | None) -> bool:
    if not isinstance(compensation, dict):
        return False
    if compensation.get("basis") != "gross" or compensation.get("period") != "monthly":
        return False
    return bool(compensation.get("amount_low")) and bool(compensation.get("amount_high"))


def _recruiter_note(note: str, identity_values: Sequence[str]) -> str:
    cleaned = redact_identity(note, identity_values).strip()
    if cleaned:
        return cleaned
    return "The note was removed because it repeated an identity field."
