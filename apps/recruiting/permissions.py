"""DRF object permissions. A candidate cannot call recruiter evaluation.

The group names are ``candidate`` and ``recruiter``. The model is not the
permission layer, and it does not confirm consent.
"""

from rest_framework.permissions import BasePermission

CANDIDATE_GROUP = "candidate"
RECRUITER_GROUP = "recruiter"


def _in_group(user, name: str) -> bool:
    return bool(user and user.is_authenticated and user.groups.filter(name=name).exists())


class RecruiterEvaluationPermission(BasePermission):
    """Object permission for assessing one application.

    ``has_permission`` allows any authenticated user through to the object
    check. ``has_object_permission`` refuses a candidate, including the
    candidate who owns the application.
    """

    message = "A candidate cannot call recruiter evaluation."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if _in_group(user, CANDIDATE_GROUP):
            return False
        candidate_user_id = getattr(getattr(obj, "candidate", None), "user_id", None)
        if candidate_user_id is not None and candidate_user_id == user.id:
            return False
        return _in_group(user, RECRUITER_GROUP)


class IsRecruiter(BasePermission):
    """Talent-pool search is a recruiter surface."""

    message = "Recruiter access is required."

    def has_permission(self, request, view):
        user = request.user
        return _in_group(user, RECRUITER_GROUP) and not _in_group(user, CANDIDATE_GROUP)
