import hashlib
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (
    LoginForm,
    PregnancyProfileForm,
    PrenatalAppointmentForm,
    RegisterForm,
)
from .models import PregnancyProfile
from .onboarding import post_authentication_redirect, pregnancy_record_is_complete

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=1)
ATTEMPT_WINDOW = timedelta(minutes=15)
INVALID_LOGIN_MESSAGE = "Invalid username or password."
LOCKED_MESSAGE = "Too many failed attempts. Locked for 1 minute."


def _lock_cache_keys(request, username):
    remote_addr = request.META.get("REMOTE_ADDR", "")
    digest = hashlib.sha256(
        f"{username.casefold()}\0{remote_addr}".encode()
    ).hexdigest()
    return f"login-attempts:{digest}", f"login-lock:{digest}"


def _reset_lock_state(request, username):
    attempts_key, lock_key = _lock_cache_keys(request, username)
    cache.delete_many((attempts_key, lock_key))


def _get_lock_state(request, username):
    attempts_key, lock_key = _lock_cache_keys(request, username)
    lock_until = cache.get(lock_key)
    if lock_until is not None:
        remaining = max(0, int((lock_until - timezone.now()).total_seconds()))
        return MAX_FAILED_ATTEMPTS, remaining or 1
    return cache.get(attempts_key, 0), None


def _record_failed_attempt(request, username):
    attempts_key, lock_key = _lock_cache_keys(request, username)
    cache.add(attempts_key, 0, timeout=int(ATTEMPT_WINDOW.total_seconds()))
    failed_attempts = cache.incr(attempts_key)
    if failed_attempts >= MAX_FAILED_ATTEMPTS:
        cache.set(
            lock_key,
            timezone.now() + LOCK_DURATION,
            timeout=int(LOCK_DURATION.total_seconds()),
        )
        cache.delete(attempts_key)
        return MAX_FAILED_ATTEMPTS, int(LOCK_DURATION.total_seconds())
    return failed_attempts, None


def _display_name(user):
    return user.get_full_name().strip() or user.get_username()


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return post_authentication_redirect(request.user)

    form = LoginForm(request=request, data=request.POST or None)
    username = request.POST.get("username", "").strip()
    if request.method == "POST" and username:
        _failed_attempts, remaining = _get_lock_state(request, username)
        if remaining is not None:
            messages.error(
                request, f"Too many failed attempts. Try again in {remaining} seconds."
            )
            return render(
                request,
                "auth/login.html",
                {
                    "form": form,
                    "locked": True,
                    "remaining": remaining,
                },
            )

        if form.is_valid():
            user = form.get_user()
            _reset_lock_state(request, username)
            login(request, user)
            return post_authentication_redirect(user)

        failed_attempts, remaining = _record_failed_attempt(request, username)
        if remaining is not None:
            messages.error(request, LOCKED_MESSAGE)
            return render(
                request,
                "auth/login.html",
                {
                    "form": form,
                    "locked": True,
                    "remaining": remaining,
                },
            )
        messages.error(
            request,
            f"{INVALID_LOGIN_MESSAGE} {MAX_FAILED_ATTEMPTS - failed_attempts} attempts remaining.",
        )
    return render(request, "auth/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        return post_authentication_redirect(request.user)

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return post_authentication_redirect(user)
    return render(
        request,
        "auth/register.html",
        {
            "form": form,
            "errors": form.errors,
            "form_data": request.POST,
        },
    )


@require_http_methods(["GET", "POST"])
@login_required(login_url="login")
def profile(request):
    profile, _created = PregnancyProfile.objects.get_or_create(user=request.user)
    was_complete = pregnancy_record_is_complete(profile)
    form = PregnancyProfileForm(
        request.POST or None if request.POST.get("save_profile") else None,
        instance=profile,
        user=request.user,
        require_privacy_acknowledgement=not was_complete,
    )
    appointment_form = PrenatalAppointmentForm()

    if request.method == "POST" and "save_profile" in request.POST and form.is_valid():
        form.save()
        if not was_complete:
            messages.success(
                request,
                "Your pregnancy information has been saved. Welcome to PregnaBot.",
            )
            return redirect("dashboard")
        messages.success(request, "Your profile has been updated.")
        return redirect("profile")

    if request.method == "POST" and "add_appointment" in request.POST:
        appointment_form = PrenatalAppointmentForm(request.POST)
        if appointment_form.is_valid():
            appointment = appointment_form.save(commit=False)
            appointment.profile = profile
            appointment.save()
            messages.success(request, "Your appointment was saved.")
            return redirect("profile")

    return render(
        request,
        "pregnancy/prenatal_profile.html",
        {
            "profile": profile,
            "form": form,
            "appointment_form": appointment_form,
            "display_name": _display_name(request.user),
            "onboarding_complete": was_complete,
            "today": timezone.localdate(),
            "appointments": profile.appointments.filter(
                scheduled_at__gte=timezone.now(),
            )[:20],
        },
    )


# ``pregnancy-profile/`` stays as a backwards-compatible alias of the profile view.
pregnancy_profile = profile
