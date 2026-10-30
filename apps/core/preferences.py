"""Account settings: profile credentials, security, and privacy information."""

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import AccountDetailsForm


def _display_name(user):
    return user.get_full_name().strip() or user.get_username()


@require_http_methods(["GET", "POST"])
@login_required(login_url="login")
def settings_view(request):
    account_form = AccountDetailsForm(user=request.user)
    password_form = PasswordChangeForm(request.user)

    if request.method == "POST" and "update_account" in request.POST:
        account_form = AccountDetailsForm(request.POST, user=request.user)
        if account_form.is_valid():
            account_form.save()
            messages.success(request, "Your account details have been updated.")
            return redirect("settings")

    if request.method == "POST" and "change_password" in request.POST:
        password_form = PasswordChangeForm(request.user, data=request.POST)
        if password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Your password has been changed.")
            return redirect("settings")

    return render(
        request,
        "pregnancy/settings.html",
        {
            "account_form": account_form,
            "password_form": password_form,
            "account_username": request.user.get_username(),
            "account_date_joined": request.user.date_joined,
            "display_name": _display_name(request.user),
        },
    )
