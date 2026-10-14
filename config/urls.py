from django.contrib import admin
from django.urls import include, path

from apps.ingestion.views import staff_job_search

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/ingestion/", include("apps.ingestion.urls")),
    path("api/recruiting/", include("apps.recruiting.urls")),
    path("staff/job-search/", staff_job_search, name="staff-job-search"),
]
