"""Fixture feed. Live board scraping is not implemented."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from django.db import models
from django.utils import timezone

from apps.ingestion.gemini import FLASH_MODEL
from apps.ingestion.models import EmploymentPosting, ProcurementTender
from apps.ingestion.schemas import JobParser

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "feed.json"
FIXTURE_SOURCE = "fixture"


@dataclass(frozen=True)
class FixtureItem:
    external_id: str
    text: str
    source: str = FIXTURE_SOURCE


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_fixtures(path: Path = FIXTURE_PATH) -> list[FixtureItem]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = payload.get("source", FIXTURE_SOURCE)
    return [
        FixtureItem(
            external_id=item["external_id"],
            text=item["text"],
            source=source,
        )
        for item in payload["items"]
    ]


def ingest_fixture_feed(parse=None) -> dict[str, int]:
    """Parse each fixture and save employment posts and tenders separately.

    Listings from this source that do not reappear are marked expired.
    """
    if parse is None:
        from apps.ingestion.gemini import parse_posting

        parse = parse_posting

    now = timezone.now()
    seen_employment: set[str] = set()
    seen_tenders: set[str] = set()
    skipped = 0

    for item in load_fixtures():
        checked = parse(item.text)
        if checked.posting_kind == "employment":
            row = _upsert(EmploymentPosting, item, checked, now)
            _retire(ProcurementTender, item, now)
            seen_employment.add(row.external_id)
        elif checked.posting_kind == "procurement_tender":
            row = _upsert(ProcurementTender, item, checked, now)
            _retire(EmploymentPosting, item, now)
            seen_tenders.add(row.external_id)
        else:
            _retire(EmploymentPosting, item, now)
            _retire(ProcurementTender, item, now)
            skipped += 1

    return {
        "employment": len(seen_employment),
        "tenders": len(seen_tenders),
        "skipped": skipped,
        "expired_employment": _expire_absent(EmploymentPosting, seen_employment, now),
        "expired_tenders": _expire_absent(ProcurementTender, seen_tenders, now),
    }


def _upsert(model, item: FixtureItem, checked: JobParser, now):
    digest = content_hash(item.text)
    duplicate = (
        model.objects.filter(content_hash=digest)
        .exclude(external_id=item.external_id)
        .order_by("first_seen_at")
        .first()
    )
    if duplicate is not None:
        model.objects.filter(external_id=item.external_id).exclude(
            pk=duplicate.pk
        ).update(expired_at=now)
        for field, value in _field_values(item, checked, now, digest).items():
            setattr(duplicate, field, value)
        duplicate.save()
        return duplicate

    row, _created = model.objects.update_or_create(
        external_id=item.external_id,
        defaults=_field_values(item, checked, now, digest),
    )
    return row


def _field_values(item: FixtureItem, checked: JobParser, now, digest: str) -> dict:
    payload = checked.model_dump(mode="json")
    return {
        "source": item.source,
        "content_hash": digest,
        "raw_text": item.text,
        "title": checked.title,
        "employer_name": checked.employer_name,
        "employer_hidden": checked.employer_hidden,
        "seniority": checked.seniority,
        "location_text": checked.location_text,
        "location_class": checked.location_class,
        "work_authorization_text": checked.work_authorization_text,
        "compensation": payload["compensation"],
        "deadline": checked.deadline,
        "deadline_text": checked.deadline_text,
        "stated_skills": payload["stated_skills"],
        "requires_regional_operational_experience": (
            checked.requires_regional_operational_experience
        ),
        "contact_channel": checked.contact_channel,
        "charges_applicant": checked.charges_applicant,
        "legitimacy": checked.legitimacy,
        "discriminatory_criteria": payload["discriminatory_criteria"],
        "parsed_payload": payload,
        "model_id": FLASH_MODEL,
        "last_seen_at": now,
        "expired_at": None,
    }


def _retire(model, item: FixtureItem, now) -> None:
    digest = content_hash(item.text)
    model.objects.filter(expired_at__isnull=True).filter(
        models.Q(external_id=item.external_id) | models.Q(content_hash=digest)
    ).update(expired_at=now)


def _expire_absent(model, seen_ids: set[str], now) -> int:
    return model.objects.filter(
        source=FIXTURE_SOURCE,
        expired_at__isnull=True,
    ).exclude(external_id__in=seen_ids).update(expired_at=now)
