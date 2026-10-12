"""Recruiter HTTP surface.

Talent-pool search reads stored rows. It does not score anyone. Identity
fields are included only when that candidate has an active talent-pool
consent. An application does not count as that consent.
"""

from django.db.models import Exists, OuterRef
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.recruiting.identity import IDENTITY_FIELDS, contains_identity, identity_values
from apps.recruiting.models import (
    ApplicationEvaluation,
    Candidate,
    JobApplication,
    TalentPoolConsent,
)
from apps.recruiting.permissions import IsRecruiter, RecruiterEvaluationPermission
from apps.recruiting.services import evaluate_application


class TalentPoolView(APIView):
    permission_classes = [IsAuthenticated, IsRecruiter]

    def get(self, request):
        open_consent = TalentPoolConsent.objects.filter(
            candidate=OuterRef("pk"),
            revoked_at__isnull=True,
        )
        candidates = Candidate.objects.annotate(
            talent_pool_open=Exists(open_consent)
        ).order_by("pk")
        return Response(
            {"results": [_talent_pool_entry(candidate) for candidate in candidates]}
        )


class ApplicationEvaluationView(GenericAPIView):
    """POST runs one evaluation. The permission check is on the application."""

    queryset = JobApplication.objects.select_related("candidate", "posting")
    permission_classes = [IsAuthenticated, RecruiterEvaluationPermission]
    lookup_url_kwarg = "application_id"

    def post(self, request, application_id):
        application = self.get_object()
        result = evaluate_application(application)
        return Response(evaluation_payload(result), status=status.HTTP_201_CREATED)


def evaluation_payload(result: ApplicationEvaluation) -> dict:
    """Model fields, then Django's overlap. The note label is applied here."""
    percentage = result.overlap_percentage
    return {
        "observations": result.observations,
        "discriminatory_criteria_present": result.discriminatory_criteria_present,
        "regional_operational_experience": result.regional_operational_experience,
        "verification_topics": result.verification_topics,
        "salary_alignment_note": result.salary_alignment_note,
        "recruiter_note": result.recruiter_note,
        "recruiter_note_label": "model-written",
        "keyword_overlap_percentage": None if percentage is None else f"{percentage:.2f}",
        "rubric_version": result.rubric_version,
        "matched_keywords": result.matched_keywords,
        "missing_keywords": result.missing_keywords,
        "model_id": result.model_id,
    }


def _talent_pool_entry(candidate: Candidate) -> dict:
    visible = bool(candidate.talent_pool_open)
    entry = {
        "candidate_id": candidate.pk,
        "stated_skills": _stated_skills(candidate, identity_visible=visible),
    }
    if visible:
        for field in IDENTITY_FIELDS:
            value = getattr(candidate, field)
            if field == "date_of_birth" and value is not None:
                value = value.isoformat()
            entry[field] = value
    return entry


def _stated_skills(candidate: Candidate, *, identity_visible: bool):
    skills = candidate.stated_skills
    if identity_visible or not isinstance(skills, list):
        return skills
    values = identity_values(candidate)
    return [
        skill
        for skill in skills
        if isinstance(skill, str) and not contains_identity(skill, values)
    ]
