"""Run the staff job search and store the reply on JobSearchRun.

The sweep reads the sources named in prompts/job_search.txt. It does not call
Gemini or Groq, and it does not save EmploymentPosting or ProcurementTender rows.
The reference date is the server's local date, written into the user message
and then read back from that message.
"""

import re
from datetime import date, datetime

from django.utils import timezone

from apps.ingestion.models import JobSearchRun
from apps.ingestion.search_gate import format_date
from apps.ingestion.search_http import live_fetch
from apps.ingestion.search_sources import (
    EMPTY_SENTENCE,
    TARGET_GROUPS,
    UNREAD_SENTENCE,
    SweepOutcome,
    VerifiedListing,
)

MODEL_ID = "direct-source-sweep"
_REFERENCE = re.compile(
    r"System reference date:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})"
)


def build_user_message(reference: date) -> str:
    return (
        f"System reference date: {reference.day} "
        f"{reference.strftime('%B')} {reference.year}"
    )


def reference_date_from_user_message(message: str) -> date:
    match = _REFERENCE.search(message or "")
    if not match:
        raise ValueError("The user message has no system reference date.")
    return datetime.strptime(
        f"{int(match.group(1))} {match.group(2)} {match.group(3)}",
        "%d %B %Y",
    ).date()


def execute_job_search(*, fetch=None) -> JobSearchRun:
    fetcher = live_fetch if fetch is None else fetch
    message = build_user_message(timezone.localdate())
    reference = reference_date_from_user_message(message)
    body = build_search_body(reference, now=timezone.localtime(), fetch=fetcher)
    return JobSearchRun.objects.create(
        body=body,
        model_id=MODEL_ID,
        reference_date=reference,
        user_message=message,
    )


def build_search_body(reference: date, *, now: datetime | None, fetch=None) -> str:
    fetcher = live_fetch if fetch is None else fetch
    groups = []
    for group_name, targets in TARGET_GROUPS:
        blocks = []
        for label, sweeper in targets:
            try:
                outcome = sweeper(reference, fetcher, now)
            except Exception:
                outcome = SweepOutcome(unread=True)
            blocks.append(_render_target(label, outcome))
        groups.append(group_name + "\n\n" + "\n\n".join(blocks))
    return "\n\n".join(groups) + "\n"


def render_listing(item: VerifiedListing) -> str:
    return "\n".join(
        (
            f"Job Title: {item.title}",
            f"Hiring Organization & Location: {item.organization_location}",
            (
                "Date Posted | Application Deadline: "
                f"{format_date(item.posted)} | {format_date(item.deadline)}"
            ),
            f"URL: {item.url}",
        )
    )


def _render_target(label: str, outcome: SweepOutcome) -> str:
    if outcome.unread:
        body = UNREAD_SENTENCE
    elif not outcome.listings:
        body = EMPTY_SENTENCE
    else:
        body = "\n\n".join(render_listing(item) for item in outcome.listings)
    return f"{label}\n{body}"
