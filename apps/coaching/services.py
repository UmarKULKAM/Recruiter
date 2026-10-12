"""Candidate coach. Django issues ids; Gemini does not.

CV_OPTIMIZER and CANDIDATE_REPORT use the Flash route. MOCK_INTERVIEW uses
the Pro route and returns in this call. The interview message carries this
turn plus the questions already stored on the session.
"""

import json
import uuid
from collections.abc import Sequence

from apps.coaching.models import (
    CvReview,
    InterviewSession,
    InterviewTurn,
    ProgressReport,
    StoredGap,
)
from apps.coaching.serializers import (
    serialize_candidate_report,
    serialize_cv_optimizer,
    serialize_mock_interview,
)
from apps.ingestion.gemini import (
    generate_parsed,
    route_for,
    strip_closing_untrusted_tags,
    wrap_untrusted_answer,
    wrap_untrusted_cv,
    wrap_untrusted_job_text,
)
from apps.ingestion.schemas import CandidateReport, CvOptimizer, MockInterview


def record_stored_gap(*, kind: str, label: str, gap_id: str | None = None) -> StoredGap:
    """Store one gap. Django issues ``gap_id`` when the caller does not pass one."""
    allowed = {
        StoredGap.Kind.MISSING_KEYWORD,
        StoredGap.Kind.WEAK_INTERVIEW_ANSWER,
    }
    if kind not in allowed:
        raise ValueError("kind must be missing_keyword or weak_interview_answer.")
    cleaned = label.strip()
    if not cleaned:
        raise ValueError("A stored gap needs a label.")
    issued = (gap_id or "").strip() or f"gap-{uuid.uuid4().hex}"
    return StoredGap.objects.create(gap_id=issued, kind=kind, label=cleaned)


def optimize_cv(*, cv_text: str, job_text: str = "", client=None) -> CvReview:
    """Qualitative CV coaching. Flash, temperature 0."""
    parts = []
    if job_text.strip():
        parts.append(wrap_untrusted_job_text(job_text))
    parts.append(wrap_untrusted_cv(cv_text))
    model, temperature, thinking_budget = route_for("CV_OPTIMIZER")
    parsed = generate_parsed(
        mode="CV_OPTIMIZER",
        contents="\n\n".join(parts),
        schema=CvOptimizer,
        model=model,
        temperature=temperature,
        thinking_budget=thinking_budget,
        client=client,
    )
    checked = serialize_cv_optimizer(parsed, cv_text=cv_text)
    return CvReview.objects.create(
        cv_text=cv_text,
        job_text=job_text,
        coaching_points=[point.model_dump() for point in checked.coaching_points],
        bullet_edits=[edit.model_dump() for edit in checked.bullet_edits],
        discriminatory_criteria_in_posting=list(
            checked.discriminatory_criteria_in_posting
        ),
        model_id=model,
        parsed_payload=checked.model_dump(),
    )


def start_interview(
    *,
    job_text: str,
    cv_text: str = "",
    posting_kind: str = "",
    client=None,
) -> InterviewTurn:
    """Open a session and ask the first question. Coaching quality is null."""
    if not job_text.strip():
        raise ValueError("A mock interview needs the job text.")
    session = InterviewSession.objects.create(
        job_text=job_text,
        cv_text=cv_text,
        posting_kind=posting_kind,
    )
    return _interview_turn(session, answer_text="", client=client)


def answer_interview(*, session_id, answer_text: str, client=None) -> InterviewTurn:
    """Score this answer and ask the next question. Synchronous Pro call."""
    session = InterviewSession.objects.get(pk=session_id)
    if not session.turns.exists():
        raise ValueError("Turn 1 is start_interview. There is no answer to score yet.")
    return _interview_turn(session, answer_text=answer_text, client=client)


def write_progress_report(*, gaps: Sequence[StoredGap], client=None) -> ProgressReport:
    """Seven-day plan from stored gaps. Flash, temperature 0.

    The user message is the stored gap list, outside the untrusted tags.
    """
    gap_list = list(gaps)
    model, temperature, thinking_budget = route_for("CANDIDATE_REPORT")
    parsed = generate_parsed(
        mode="CANDIDATE_REPORT",
        contents=_stored_gaps_message(gap_list),
        schema=CandidateReport,
        model=model,
        temperature=temperature,
        thinking_budget=thinking_budget,
        client=client,
    )
    checked = serialize_candidate_report(parsed, gaps=gap_list)
    return ProgressReport.objects.create(
        progress_note=checked.progress_note,
        seven_day_plan=[item.model_dump() for item in checked.seven_day_plan],
        source_gap_ids=[gap.gap_id for gap in gap_list],
        model_id=model,
        parsed_payload=checked.model_dump(),
    )


def _interview_turn(session: InterviewSession, *, answer_text: str, client) -> InterviewTurn:
    prior = list(session.turns.order_by("turn_number"))
    turn_number = len(prior) + 1
    opening = turn_number == 1
    model, temperature, thinking_budget = route_for("MOCK_INTERVIEW")
    parsed = generate_parsed(
        mode="MOCK_INTERVIEW",
        contents=_interview_contents(session, prior, answer_text, opening=opening),
        schema=MockInterview,
        model=model,
        temperature=temperature,
        thinking_budget=thinking_budget,
        client=client,
    )
    checked = serialize_mock_interview(
        parsed,
        turn_number=turn_number,
        procurement_tender=session.posting_kind == "procurement_tender",
    )
    snippet = None if checked.star_snippet is None else checked.star_snippet.model_dump()
    return InterviewTurn.objects.create(
        session=session,
        turn_number=turn_number,
        answers_question_id=None if opening else prior[-1].question_id,
        interviewer_message=checked.interviewer_message,
        answer_text="" if opening else answer_text,
        answer_feedback=checked.answer_feedback,
        star_snippet=snippet,
        coaching_quality=checked.coaching_quality,
        model_id=model,
        parsed_payload=checked.model_dump(),
    )


def _interview_contents(session, prior, answer_text: str, *, opening: bool) -> str:
    """This turn, plus questions Django already stored. No session id."""
    prior_questions = [
        {
            "question_id": str(turn.question_id),
            "interviewer_message": strip_closing_untrusted_tags(turn.interviewer_message),
        }
        for turn in prior
    ]
    lines = [
        f"opening_turn: {'true' if opening else 'false'}",
        "",
        "prior_questions:",
        json.dumps(prior_questions, ensure_ascii=False),
    ]
    if prior:
        lines.extend(["", f"answers_question_id: {prior[-1].question_id}"])
    parts = ["\n".join(lines), wrap_untrusted_job_text(session.job_text)]
    if session.cv_text.strip():
        parts.append(wrap_untrusted_cv(session.cv_text))
    if not opening:
        parts.append(wrap_untrusted_answer(answer_text))
    return "\n\n".join(parts)


def _stored_gaps_message(gaps: Sequence[StoredGap]) -> str:
    payload = [
        {
            "gap_id": gap.gap_id,
            "kind": gap.kind,
            "label": strip_closing_untrusted_tags(gap.label),
        }
        for gap in gaps
    ]
    return "stored_gaps:\n" + json.dumps(payload, ensure_ascii=False)
