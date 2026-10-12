"""Checks the response schema cannot express for the candidate coach."""

import re
from collections.abc import Sequence

from apps.ingestion.schemas import CandidateReport, CvOptimizer, MockInterview

# A stored gap label that is itself a closed-list criterion, not a sentence
# that merely mentions one.
_DISCRIMINATORY_LABELS = {
    "age",
    "sex",
    "gender",
    "tribe",
    "religion",
    "marital status",
    "marital_status",
    "health",
    "photo",
    "photograph",
    "race",
    "colour",
    "color",
    "political opinion",
    "political_opinion",
    "national extraction",
    "national_extraction",
    "social origin",
    "social_origin",
    "hiv",
    "hiv status",
    "appearance",
}


def gap_label_is_discriminatory(label: str) -> bool:
    key = re.sub(r"[\s_-]+", " ", label.strip().lower()).strip()
    return key in _DISCRIMINATORY_LABELS or key.replace(" ", "_") in _DISCRIMINATORY_LABELS


def serialize_cv_optimizer(parsed: CvOptimizer, *, cv_text: str) -> CvOptimizer:
    """Drop a bullet edit whose excerpt is not a substring of the source CV."""
    kept = [edit for edit in parsed.bullet_edits if edit.cv_excerpt in cv_text]
    return parsed.model_copy(update={"bullet_edits": kept})


def serialize_mock_interview(
    parsed: MockInterview,
    *,
    turn_number: int,
    procurement_tender: bool = False,
) -> MockInterview:
    """Coaching quality is null on turn 1. It is not a hiring score.

    A procurement tender is not interviewed, so the score stays null there too.
    """
    if turn_number < 1:
        raise ValueError("turn_number starts at 1.")
    if turn_number == 1 or procurement_tender:
        return parsed.model_copy(
            update={
                "answer_feedback": None,
                "star_snippet": None,
                "coaching_quality": None,
            }
        )
    return parsed


def serialize_candidate_report(
    parsed: CandidateReport,
    *,
    gaps: Sequence,
) -> CandidateReport:
    """Keep an action only when it cites a provided, usable gap id.

    Discriminatory labels are not usable. Ids the model mints are dropped.
    At most one action per gap, at most seven, in the order the model returned.
    """
    allowed: list[str] = []
    seen_ids: set[str] = set()
    for gap in gaps:
        gap_id = gap.gap_id
        if gap_id in seen_ids:
            continue
        seen_ids.add(gap_id)
        if gap_label_is_discriminatory(gap.label):
            continue
        allowed.append(gap_id)
    allowed_ids = set(allowed)

    kept = []
    cited: set[str] = set()
    for item in parsed.seven_day_plan:
        gap_id = item.cites_gap_id.strip()
        if gap_id not in allowed_ids or gap_id in cited:
            continue
        cited.add(gap_id)
        if gap_id != item.cites_gap_id:
            item = item.model_copy(update={"cites_gap_id": gap_id})
        kept.append(item)
        if len(kept) == 7:
            break
    return parsed.model_copy(update={"seven_day_plan": kept})
