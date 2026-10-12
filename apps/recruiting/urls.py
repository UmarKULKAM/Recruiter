from django.urls import path

from apps.recruiting.views import ApplicationEvaluationView, TalentPoolView

urlpatterns = [
    path("talent-pool/", TalentPoolView.as_view(), name="talent-pool"),
    path(
        "applications/<int:application_id>/evaluate/",
        ApplicationEvaluationView.as_view(),
        name="application-evaluate",
    ),
]
