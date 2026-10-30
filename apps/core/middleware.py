from django.shortcuts import redirect

from .onboarding import (
    request_allows_incomplete_onboarding,
    user_has_completed_pregnancy_record,
)


class PregnancyOnboardingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, _view_func, _view_args, _view_kwargs):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not user.is_staff
            and not user_has_completed_pregnancy_record(user)
            and not request_allows_incomplete_onboarding(request)
        ):
            return redirect("pregnancy_profile")
        return None
