from django.conf import settings
from django.db import models


class Candidate(models.Model):
    """A person the recruiter may assess.

    ``stated_skills`` is the phrase list the CV states, stored by Django.
    RECRUITER_EVALUATION does not emit it. Identity columns stay off
    talent-pool search until a separate consent row exists.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="candidate_profile",
    )
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    national_id = models.CharField(max_length=64, blank=True)
    photo = models.CharField(
        max_length=500,
        blank=True,
        help_text="Storage reference. The file is not sent to the model.",
    )
    date_of_birth = models.DateField(null=True, blank=True)
    cv_text = models.TextField(blank=True)
    stated_skills = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"candidate {self.pk}"


class TalentPoolConsent(models.Model):
    """Consent to be found in talent-pool search.

    An application consents to assessment for that job only. It does not
    create this record. ``revoked_at`` set means the consent is not active.
    """

    candidate = models.OneToOneField(
        Candidate,
        on_delete=models.CASCADE,
        related_name="talent_pool_consent",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        state = "revoked" if self.revoked_at else "active"
        return f"talent pool {state} for candidate {self.candidate_id}"


class JobApplication(models.Model):
    """An application to one employment post.

    This row is the consent to assess the candidate for this job. Talent-pool
    search still needs ``TalentPoolConsent``. ``shared_gross_monthly`` is set
    only when the candidate chose to share that figure.
    """

    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    posting = models.ForeignKey(
        "ingestion.EmploymentPosting",
        on_delete=models.CASCADE,
        related_name="applications",
    )
    shared_gross_monthly = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["candidate", "posting"],
                name="unique_job_application",
            )
        ]

    def __str__(self) -> str:
        return f"application {self.pk}"


class ApplicationEvaluation(models.Model):
    """One stored RECRUITER_EVALUATION plus Django's keyword overlap.

    The parsed payload is the model object after the serializer. Overlap
    percentage and rubric version are columns Django writes. A later read
    uses this row and does not call the model again.
    """

    application = models.ForeignKey(
        JobApplication,
        on_delete=models.CASCADE,
        related_name="evaluations",
    )
    observations = models.JSONField()
    discriminatory_criteria_present = models.JSONField(default=list)
    regional_operational_experience = models.TextField(null=True, blank=True)
    verification_topics = models.JSONField()
    salary_alignment_note = models.TextField(null=True, blank=True)
    recruiter_note = models.TextField()
    overlap_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Django keyword-overlap percentage. Null when it cannot be computed.",
    )
    rubric_version = models.CharField(max_length=64)
    matched_keywords = models.JSONField(default=list)
    missing_keywords = models.JSONField(default=list)
    model_id = models.CharField(max_length=64)
    parsed_payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(overlap_percentage__isnull=True)
                | models.Q(overlap_percentage__gte=0, overlap_percentage__lte=100),
                name="overlap_percentage_bounds",
            )
        ]

    def __str__(self) -> str:
        return f"evaluation {self.pk}"
