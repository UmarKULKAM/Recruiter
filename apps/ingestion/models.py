from django.db import models


class Listing(models.Model):
    """Shared columns for an employment post and a procurement tender."""

    class Legitimacy(models.TextChoices):
        HIGH = "high", "high"
        REVIEW = "review", "review"
        CLEAR = "clear", "clear"

    external_id = models.CharField(max_length=128, unique=True)
    source = models.CharField(max_length=32, default="fixture")
    content_hash = models.CharField(max_length=64)
    raw_text = models.TextField()
    title = models.CharField(max_length=500, null=True, blank=True)
    employer_name = models.CharField(max_length=500, null=True, blank=True)
    employer_hidden = models.BooleanField()
    seniority = models.CharField(max_length=200, null=True, blank=True)
    location_text = models.TextField(null=True, blank=True)
    location_class = models.CharField(max_length=32, null=True, blank=True)
    work_authorization_text = models.TextField(null=True, blank=True)
    compensation = models.JSONField(null=True, blank=True)
    deadline = models.DateField(null=True, blank=True)
    deadline_text = models.TextField(null=True, blank=True)
    stated_skills = models.JSONField(null=True, blank=True)
    requires_regional_operational_experience = models.BooleanField()
    contact_channel = models.CharField(max_length=32, null=True, blank=True)
    charges_applicant = models.BooleanField(null=True, blank=True)
    legitimacy = models.CharField(max_length=16, choices=Legitimacy.choices)
    discriminatory_criteria = models.JSONField(default=list)
    parsed_payload = models.JSONField()
    model_id = models.CharField(max_length=64)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField()
    expired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=["content_hash"]),
            models.Index(fields=["legitimacy"]),
        ]

    def __str__(self) -> str:
        return self.title or self.external_id


class EmploymentPosting(Listing):
    """A parsed offer of paid work."""


class ProcurementTender(Listing):
    """A parsed public procurement or supply tender. Not an employment post."""
