"""Identity fields stay off talent-pool search and out of the model call.

The closed list is name, phone, email, national ID, photo, and date of birth.
"""

import re
from collections.abc import Sequence

IDENTITY_FIELDS = (
    "full_name",
    "phone",
    "email",
    "national_id",
    "photo",
    "date_of_birth",
)


def identity_values(candidate) -> list[str]:
    """Stored identity strings for one candidate. Photo is a reference, not bytes."""
    values = [
        candidate.full_name,
        candidate.phone,
        candidate.email,
        candidate.national_id,
        candidate.photo,
    ]
    if candidate.date_of_birth is not None:
        values.append(candidate.date_of_birth.isoformat())
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


def contains_identity(text: str, values: Sequence[str]) -> bool:
    haystack = text.casefold()
    return any(value.casefold() in haystack for value in values if value)


def redact_identity(text: str, values: Sequence[str]) -> str:
    """Remove stored identity strings before source text is wrapped."""
    redacted = text
    for value in sorted((item for item in values if item), key=len, reverse=True):
        redacted = re.compile(re.escape(value), re.IGNORECASE).sub("", redacted)
    return redacted
