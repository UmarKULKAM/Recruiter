from django.urls import path

from apps.ingestion.views import JobSearchRunView

urlpatterns = [
    path("search-runs/", JobSearchRunView.as_view(), name="job-search-runs"),
]
