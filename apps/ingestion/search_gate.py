"""Date gate for one job-search sweep.

A listing stays only when the source states both a posted date and a deadline,
the posted date falls in the 14 days ending on the reference date, and the
deadline has not passed. A missing year is not a date.
"""

import re
from datetime import date, datetime, time, timedelta

WINDOW_DAYS = 14

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_DAY_MONTH = re.compile(
    r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]+)\s*,?\s*(20\d{2})\b",
    re.IGNORECASE,
)
_MONTH_DAY = re.compile(
    r"\b([A-Za-z]+)\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s*,?\s*(20\d{2})\b",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)")
_CLOCK = re.compile(r"\b(\d{1,2})\s*:\s*(\d{2})\s*(am|pm)\b", re.IGNORECASE)

CLOSED_MARKERS = (
    "no longer accepting applications",
    "this position has been filled",
    "this job has been closed",
    "this job is closed",
    "applications are closed",
    "vacancy has closed",
    "listing has been archived",
    "this listing is archived",
)


def parse_explicit_date(text: str) -> date | None:
    """Return a calendar date only when the text states a day, month, and year."""
    if not text:
        return None
    day_first = _DAY_MONTH.search(text)
    if day_first:
        parsed = _assemble(
            int(day_first.group(1)),
            day_first.group(2),
            int(day_first.group(3)),
        )
        if parsed:
            return parsed
    month_first = _MONTH_DAY.search(text)
    if month_first:
        parsed = _assemble(
            int(month_first.group(2)),
            month_first.group(1),
            int(month_first.group(3)),
        )
        if parsed:
            return parsed
    iso = _ISO_DATE.search(text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    return None


def parse_clock(text: str) -> time | None:
    match = _CLOCK.search(text or "")
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour < 1 or hour > 12 or minute > 59:
        return None
    meridiem = match.group(3).lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return time(hour, minute)


def posted_in_window(posted: date | None, reference: date) -> bool:
    if posted is None:
        return False
    start = reference - timedelta(days=WINDOW_DAYS)
    return start <= posted <= reference


def deadline_still_open(
    deadline: date | None,
    reference: date,
    *,
    deadline_time: time | None = None,
    now: datetime | None = None,
) -> bool:
    """A date-only deadline stays open through that local calendar day.

    When the page states a clock time and the deadline is the reference day,
    the listing closes once that local time has passed.
    """
    if deadline is None:
        return False
    if deadline > reference:
        return True
    if deadline < reference:
        return False
    if deadline_time is None or now is None:
        return True
    current = now.time().replace(second=0, microsecond=0)
    return current <= deadline_time


def text_says_closed(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in CLOSED_MARKERS)


def listing_qualifies(
    posted: date | None,
    deadline: date | None,
    reference: date,
    *,
    closed: bool = False,
    deadline_time: time | None = None,
    now: datetime | None = None,
) -> bool:
    if closed:
        return False
    return posted_in_window(posted, reference) and deadline_still_open(
        deadline,
        reference,
        deadline_time=deadline_time,
        now=now,
    )


def format_date(value: date) -> str:
    return f"{value.day} {value.strftime('%b')} {value.year}"


def _assemble(day: int, month_name: str, year: int) -> date | None:
    month = MONTHS.get(month_name.lower())
    if month is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None
