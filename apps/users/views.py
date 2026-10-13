from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .forms import UserForm

User = get_user_model()


def _is_superuser(user):
    return user.is_superuser


# PAGE
@login_required(login_url="login")
@user_passes_test(_is_superuser, login_url="dashboard")
def user_list_page(request):
    query = request.GET.get("q", "").strip()
    users = _paginated_users(query, request.GET.get("page", 1))

    return render(
        request,
        "users/list.html",
        {
            "users": users,
            "query": query,
        },
    )


def _paginated_users(query, page_number):
    users_list = User.objects.all().order_by("-date_joined")
    if query:
        users_list = users_list.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )
    return Paginator(users_list, 10).get_page(page_number)


# LIST USERS (AJAX)
@login_required(login_url="login")
@user_passes_test(_is_superuser, login_url="dashboard")
def user_list_ajax(request):
    users = _paginated_users(
        request.GET.get("q", "").strip(),
        request.GET.get("page", 1),
    )
    data = list(
        users.object_list.values(
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "is_staff",
            "is_active",
            "date_joined",
        )
    )
    return JsonResponse(
        {
            "data": data,
            "has_next": users.has_next(),
            "has_prev": users.has_previous(),
            "page": users.number,
            "pages": users.paginator.num_pages,
            "total": users.paginator.count,
        }
    )


# GET SINGLE USER (AJAX)
@login_required(login_url="login")
@user_passes_test(_is_superuser, login_url="dashboard")
def user_get_ajax(request, pk):
    user = get_object_or_404(User, pk=pk)
    return JsonResponse(
        {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "is_staff": user.is_staff,
            "is_active": user.is_active,
        }
    )


# CREATE / UPDATE USER (AJAX)
@login_required(login_url="login")
@user_passes_test(_is_superuser, login_url="dashboard")
@require_POST
def user_save_ajax(request):
    user_id = request.POST.get("id")

    if user_id:
        if not user_id.isdecimal():
            return JsonResponse({"error": "Invalid user id."}, status=400)
        user = get_object_or_404(User, pk=user_id)
    else:
        user = User()

    form_data = request.POST.copy()
    for field in ("is_staff", "is_active"):
        form_data[field] = "true" if request.POST.get(field) == "true" else ""
    form = UserForm(form_data, instance=user)
    if not form.is_valid():
        errors = {
            field: error_list[0]
            for field, error_list in form.errors.items()
            if error_list
        }
        first_error = next(iter(errors.values()), "Please correct the form.")
        return JsonResponse({"error": first_error, "errors": errors}, status=400)

    try:
        user = form.save()
    except IntegrityError:
        return JsonResponse(
            {
                "error": "Could not save user due to a conflict (duplicate username/email)."
            },
            status=400,
        )

    return JsonResponse(
        {
            "status": "success",
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "is_staff": user.is_staff,
            "is_active": user.is_active,
        }
    )


# DELETE USER (AJAX)
@login_required(login_url="login")
@user_passes_test(_is_superuser, login_url="dashboard")
@require_POST
def user_delete_ajax(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.user == user:
        return JsonResponse({"error": "You cannot delete yourself"}, status=400)
    user.delete()
    return JsonResponse({"status": "deleted"})
