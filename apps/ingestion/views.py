"""Staff job search.

POST /api/ingestion/search-runs/ runs one sweep and stores the text.
GET returns stored rows and does not run the sweep or score a candidate.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ingestion.models import JobSearchRun
from apps.ingestion.search import execute_job_search


class JobSearchRunView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        runs = JobSearchRun.objects.order_by("-pk")[:20]
        return Response({"results": [_payload(run) for run in runs]})

    def post(self, request):
        run = execute_job_search()
        return Response(_payload(run), status=201)


@require_GET
@login_required
@staff_member_required
def staff_job_search(request):
    """The button lives here. Opening the page does not run a search."""
    latest = JobSearchRun.objects.order_by("-pk").first()
    return render(
        request,
        "ingestion/job_search.html",
        {"latest": latest},
    )


def _payload(run: JobSearchRun) -> dict:
    return {
        "id": run.pk,
        "body": run.body,
        "model_id": run.model_id,
        "reference_date": run.reference_date.isoformat(),
        "user_message": run.user_message,
        "created_at": run.created_at.isoformat(),
    }
