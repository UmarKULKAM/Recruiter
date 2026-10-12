import uuid

from django.db import models


class StoredGap(models.Model):
    """A missing keyword or a weak interview answer Django stored.

    The model does not mint gap ids. ``write_progress_report`` cites these.
    """

    class Kind(models.TextChoices):
        MISSING_KEYWORD = "missing_keyword", "missing_keyword"
        WEAK_INTERVIEW_ANSWER = "weak_interview_answer", "weak_interview_answer"

    gap_id = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=32, choices=Kind.choices)
    label = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.gap_id


class CvReview(models.Model):
    """CV_OPTIMIZER result after excerpt checks. Flash model id is stored."""

    cv_text = models.TextField()
    job_text = models.TextField(blank=True)
    coaching_points = models.JSONField()
    bullet_edits = models.JSONField()
    discriminatory_criteria_in_posting = models.JSONField(default=list)
    model_id = models.CharField(max_length=64)
    parsed_payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class InterviewSession(models.Model):
    """Django issues the session id. It is not a model output field."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_text = models.TextField()
    cv_text = models.TextField(blank=True)
    posting_kind = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return str(self.id)


class InterviewTurn(models.Model):
    """One mock-interview turn.

    ``turn_number`` and ``question_id`` are issued here. ``coaching_quality``
    is coaching quality from 1 to 10 after turn 1, and null on turn 1. It is
    not a hiring score.
    """

    session = models.ForeignKey(
        InterviewSession,
        on_delete=models.CASCADE,
        related_name="turns",
    )
    turn_number = models.PositiveIntegerField()
    question_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    answers_question_id = models.UUIDField(null=True, blank=True)
    interviewer_message = models.TextField()
    answer_text = models.TextField(blank=True)
    answer_feedback = models.TextField(null=True, blank=True)
    star_snippet = models.JSONField(null=True, blank=True)
    coaching_quality = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Coaching quality from 1 to 10 on turns after turn 1. "
            "Null on turn 1. Not a hiring score."
        ),
    )
    model_id = models.CharField(max_length=64)
    parsed_payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["turn_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "turn_number"],
                name="unique_interview_turn",
            ),
            models.CheckConstraint(
                condition=models.Q(coaching_quality__isnull=True)
                | (
                    models.Q(coaching_quality__gte=1, coaching_quality__lte=10)
                    & ~models.Q(turn_number=1)
                ),
                name="coaching_quality_after_turn_1",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.session_id} turn {self.turn_number}"


class ProgressReport(models.Model):
    """CANDIDATE_REPORT result. Each plan action cites a stored gap id."""

    progress_note = models.TextField()
    seven_day_plan = models.JSONField()
    source_gap_ids = models.JSONField()
    model_id = models.CharField(max_length=64)
    parsed_payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
