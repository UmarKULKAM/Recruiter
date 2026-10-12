"""Recruiter evaluation. Django merges keyword overlap after the model call.

RECRUITER_EVALUATION uses the Flash route at temperature 0. The call goes
through the shared Gemini wrapper: one mode prompt, tag stripping,
``response.parsed``, then the serializer. Identity values are removed before
the text is wrapped. They are not match features.
"""

from decimal import Decimal

from apps.ingestion.gemini import (
    generate_parsed,
    route_for,
    wrap_untrusted_cv,
    wrap_untrusted_job_text,
)
from apps.ingestion.schemas import RecruiterEvaluation
from apps.recruiting.identity import identity_values, redact_identity
from apps.recruiting.models import ApplicationEvaluation, JobApplication
from apps.recruiting.rubric import keyword_overlap
from apps.recruiting.serializers import serialize_recruiter_evaluation


def evaluate_application(
    application: JobApplication,
    *,
    client=None,
) -> ApplicationEvaluation:
    """Assess one application for its job. Does not require talent-pool consent."""
    candidate = application.candidate
    posting = application.posting
    values = identity_values(candidate)
    job_text = redact_identity(posting.raw_text, values)
    cv_text = redact_identity(candidate.cv_text, values)
    overlap = keyword_overlap(
        posting.stated_skills,
        candidate.stated_skills,
        identity_values=values,
    )
    model, temperature, thinking_budget = route_for("RECRUITER_EVALUATION")
    parsed = generate_parsed(
        mode="RECRUITER_EVALUATION",
        contents=_contents(
            job_text=job_text,
            cv_text=cv_text,
            shared_gross_monthly=application.shared_gross_monthly,
        ),
        schema=RecruiterEvaluation,
        model=model,
        temperature=temperature,
        thinking_budget=thinking_budget,
        client=client,
    )
    checked = serialize_recruiter_evaluation(
        parsed,
        job_text=job_text,
        cv_text=cv_text,
        posting_requires_regional_operational_experience=(
            posting.requires_regional_operational_experience
        ),
        candidate_shared_gross_monthly=application.shared_gross_monthly,
        posting_compensation=posting.compensation,
        identity_values=values,
    )
    return ApplicationEvaluation.objects.create(
        application=application,
        observations=[item.model_dump() for item in checked.observations],
        discriminatory_criteria_present=list(checked.discriminatory_criteria_present),
        regional_operational_experience=checked.regional_operational_experience,
        verification_topics=list(checked.verification_topics),
        salary_alignment_note=checked.salary_alignment_note,
        recruiter_note=checked.recruiter_note,
        overlap_percentage=overlap.percentage,
        rubric_version=overlap.rubric_version,
        matched_keywords=list(overlap.matched_keywords),
        missing_keywords=list(overlap.missing_keywords),
        model_id=model,
        parsed_payload=checked.model_dump(),
    )


def _contents(*, job_text: str, cv_text: str, shared_gross_monthly: Decimal | None) -> str:
    """Job text and CV text only. A shared salary figure stays outside the tags."""
    parts = []
    if shared_gross_monthly is not None:
        parts.append(f"candidate_shared_gross_monthly: {format(shared_gross_monthly, 'f')}")
    parts.append(wrap_untrusted_job_text(job_text))
    parts.append(wrap_untrusted_cv(cv_text))
    return "\n\n".join(parts)
