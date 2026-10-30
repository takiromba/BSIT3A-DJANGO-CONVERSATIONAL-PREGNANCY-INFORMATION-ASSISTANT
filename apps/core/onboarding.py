from django.shortcuts import redirect

from .models import PregnancyProfile

ONBOARDING_ALLOWED_URL_NAMES = {
    "login",
    "register",
    "logout",
    "profile",
    "pregnancy_profile",
    "appointment_delete",
    "bookmark_toggle",
    "public_home",
    "chatbot",
    "chat_new",
    "chat_conversation",
    "conversation_history",
    "chat_rename",
    "chat_delete",
    "chat_export",
    "chat_feedback",
    "pregnancy_information",
    "topic_detail",
    "faq_list",
    "health_check",
    "set_language",
}

ONBOARDING_ALLOWED_NAMESPACES = {"admin"}
ONBOARDING_ALLOWED_PATH_PREFIXES = (
    "/static/",
    "/media/",
    "/admin/",
    "/i18n/",
    "/healthz/",
)


def get_pregnancy_profile(user):
    try:
        return user.pregnancy_profile
    except (AttributeError, PregnancyProfile.DoesNotExist):
        return None


def pregnancy_record_is_complete(profile):
    return bool(
        profile and (profile.pregnancy_status or profile.estimated_conception_date)
    )


def user_has_completed_pregnancy_record(user):
    if not getattr(user, "is_authenticated", False):
        return False
    return pregnancy_record_is_complete(get_pregnancy_profile(user))


def post_authentication_redirect(user):
    if user_has_completed_pregnancy_record(user):
        return redirect("dashboard")
    return redirect("pregnancy_profile")


def request_allows_incomplete_onboarding(request):
    path = request.path
    if any(path.startswith(prefix) for prefix in ONBOARDING_ALLOWED_PATH_PREFIXES):
        return True
    match = getattr(request, "resolver_match", None)
    if match is None:
        return True
    if match.namespace in ONBOARDING_ALLOWED_NAMESPACES:
        return True
    return match.url_name in ONBOARDING_ALLOWED_URL_NAMES
