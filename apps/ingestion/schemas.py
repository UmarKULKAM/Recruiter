"""Pydantic models for the five hiring modes.

Passed to Gemini as ``response_schema``. The Schema object has no
``uniqueItems``, ``additionalProperties``, ``const``, ``pattern``, or
``$schema``, so those keywords are not declared. ``minLength``, ``minItems``,
``maxItems``, ``minimum``, and ``maximum`` stay. Cross-field rules the schema
cannot express are applied by the ingestion serializer for JOB_PARSER.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

NonEmptyStr = Annotated[str, Field(min_length=1)]

DiscriminatoryCriterion = Literal[
    "age",
    "sex",
    "tribe",
    "religion",
    "marital_status",
    "health",
    "photo",
    "race",
    "colour",
    "political_opinion",
    "national_extraction",
    "social_origin",
    "hiv",
    "appearance",
]

_DISCRIMINATORY_DESCRIPTION = (
    "Posting demands to flag. Empty when none. Not match features."
)

PostingKind = Literal["employment", "procurement_tender"]
LocationClass = Literal["uganda_onsite", "remote_from_uganda", "international"]
PayPeriod = Literal["hourly", "daily", "weekly", "monthly", "annual"]
PayBasis = Literal["gross", "net"]
ContactChannel = Literal["personal_inbox", "employer_channel"]
LegitimacyTier = Literal["high", "review", "clear"]


class Compensation(BaseModel):
    """Stated pay. Amount strings copy the printed numerals."""

    verbatim: NonEmptyStr | None
    currency: NonEmptyStr | None
    period: PayPeriod | None
    basis: PayBasis | None
    amount_low: NonEmptyStr | None
    amount_high: NonEmptyStr | None


class JobParser(BaseModel):
    model_config = ConfigDict(title="JOB_PARSER")

    posting_kind: PostingKind | None
    title: NonEmptyStr | None
    employer_name: NonEmptyStr | None
    employer_hidden: bool
    seniority: NonEmptyStr | None
    location_text: NonEmptyStr | None
    location_class: Annotated[
        LocationClass | None,
        Field(
            description=(
                "remote_from_uganda only when the work can be done from Uganda."
            )
        ),
    ]
    work_authorization_text: NonEmptyStr | None
    compensation: Annotated[
        Compensation | None,
        Field(
            description=(
                "Null when the posting states no pay. "
                "Amount strings copy the printed numerals."
            )
        ),
    ]
    deadline: date | None
    deadline_text: NonEmptyStr | None
    stated_skills: Annotated[
        list[NonEmptyStr] | None,
        Field(
            min_length=1,
            description=(
                "Phrases the posting states. Null when it states none. "
                "Not a matched or missing keyword list."
            ),
        ),
    ]
    requires_regional_operational_experience: Annotated[
        bool,
        Field(
            description=(
                "True only when the posting states the requirement. "
                "This is not regional_operational_experience."
            )
        ),
    ]
    contact_channel: ContactChannel | None
    charges_applicant: bool | None
    legitimacy: Annotated[
        LegitimacyTier,
        Field(
            description=(
                "high, then review, then clear. A personal inbox alone is review."
            )
        ),
    ]
    discriminatory_criteria: Annotated[
        list[DiscriminatoryCriterion],
        Field(description=_DISCRIMINATORY_DESCRIPTION),
    ]


class CoachingPoint(BaseModel):
    focus: Literal[
        "structure",
        "wording",
        "evidence",
        "alignment",
        "do_not_comply",
        "not_an_employment_post",
    ]
    advice: NonEmptyStr


class BulletEdit(BaseModel):
    cv_excerpt: NonEmptyStr
    suggestion: NonEmptyStr
    uses_result_placeholder: bool


class CvOptimizer(BaseModel):
    model_config = ConfigDict(title="CV_OPTIMIZER")

    coaching_points: Annotated[
        list[CoachingPoint],
        Field(min_length=1, max_length=6),
    ]
    bullet_edits: Annotated[list[BulletEdit], Field(max_length=8)]
    discriminatory_criteria_in_posting: Annotated[
        list[DiscriminatoryCriterion],
        Field(description=_DISCRIMINATORY_DESCRIPTION),
    ]


class StarSnippet(BaseModel):
    situation: NonEmptyStr | None
    task: NonEmptyStr | None
    action: NonEmptyStr | None
    result: NonEmptyStr


class MockInterview(BaseModel):
    model_config = ConfigDict(title="MOCK_INTERVIEW")

    interviewer_message: NonEmptyStr
    answer_feedback: Annotated[
        NonEmptyStr | None,
        Field(
            description=(
                "Null on turn 1. Feedback on the answer, not a score "
                "and not CV coaching."
            )
        ),
    ]
    star_snippet: Annotated[
        StarSnippet | None,
        Field(
            description=(
                "Null on turn 1 and when the answer has no behavioral content. "
                "result is the placeholder when the candidate stated no result."
            )
        ),
    ]
    coaching_quality: Annotated[
        int | None,
        Field(
            ge=1,
            le=10,
            description=(
                "Coaching quality from 1 to 10. Null on turn 1 and when the "
                "text is a procurement tender. Not a hiring metric."
            ),
        ),
    ]


class PlanAction(BaseModel):
    action: NonEmptyStr
    cites_gap_id: NonEmptyStr


class CandidateReport(BaseModel):
    model_config = ConfigDict(title="CANDIDATE_REPORT")

    progress_note: NonEmptyStr
    seven_day_plan: Annotated[
        list[PlanAction],
        Field(
            max_length=7,
            description=(
                "Ordered plan. Every item cites a stored gap id. At most seven. "
                "Empty when there is no usable stored gap."
            ),
        ),
    ]


class Observation(BaseModel):
    kind: Literal["strength", "risk"]
    observation: NonEmptyStr
    source: Literal["cv", "job_text"]
    excerpt: NonEmptyStr


class RecruiterEvaluation(BaseModel):
    model_config = ConfigDict(title="RECRUITER_EVALUATION")

    observations: Annotated[list[Observation], Field(max_length=8)]
    discriminatory_criteria_present: Annotated[
        list[DiscriminatoryCriterion],
        Field(description=_DISCRIMINATORY_DESCRIPTION),
    ]
    regional_operational_experience: Annotated[
        NonEmptyStr | None,
        Field(
            description=(
                "A CV quote when the posting requires it and the CV shows it. "
                "Otherwise null."
            )
        ),
    ]
    verification_topics: Annotated[
        list[NonEmptyStr],
        Field(
            max_length=5,
            description="Facts to check in an interview. Not a rank.",
        ),
    ]
    salary_alignment_note: Annotated[
        NonEmptyStr | None,
        Field(
            description=(
                "Null unless the candidate shared a gross monthly figure and "
                "the posting states a gross monthly band."
            )
        ),
    ]
    recruiter_note: NonEmptyStr


MODE_SCHEMAS = {
    "JOB_PARSER": JobParser,
    "CV_OPTIMIZER": CvOptimizer,
    "MOCK_INTERVIEW": MockInterview,
    "CANDIDATE_REPORT": CandidateReport,
    "RECRUITER_EVALUATION": RecruiterEvaluation,
}
