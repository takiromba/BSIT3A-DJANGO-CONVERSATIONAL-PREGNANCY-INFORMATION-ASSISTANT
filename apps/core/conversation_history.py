from datetime import datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import OuterRef, Q, Subquery
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import ChatConversation, ChatMessage

FILTERS = {
    "today": "Today",
    "7": "Last 7 Days",
    "30": "Last 30 Days",
}


def _local_day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


@require_GET
@login_required(login_url="login")
def conversation_history(request):
    conversations = ChatConversation.objects.filter(user=request.user)

    query = request.GET.get("q", "").strip()
    if query:
        conversations = conversations.filter(
            Q(title__icontains=query) | Q(messages__content__icontains=query)
        ).distinct()

    selected_filter = request.GET.get("range", "")
    today = timezone.localdate()
    if selected_filter == "today":
        conversations = conversations.filter(updated_at__gte=_local_day_start(today))
    elif selected_filter == "7":
        conversations = conversations.filter(
            updated_at__gte=_local_day_start(today - timedelta(days=6))
        )
    elif selected_filter == "30":
        conversations = conversations.filter(
            updated_at__gte=_local_day_start(today - timedelta(days=29))
        )
    else:
        selected_filter = ""

    latest_message = ChatMessage.objects.filter(
        conversation_id=OuterRef("pk")
    ).order_by("-created_at", "-pk")
    conversations = conversations.annotate(
        latest_user_message=Subquery(
            latest_message.filter(role=ChatMessage.Role.USER).values("content")[:1]
        ),
        latest_message=Subquery(latest_message.values("content")[:1]),
    ).order_by("-updated_at", "-pk")

    paginator = Paginator(conversations, 8)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_suffix = query_params.urlencode()
    filter_params = request.GET.copy()
    filter_params.pop("page", None)
    filter_params.pop("range", None)

    return render(
        request,
        "pregnancy/conversation_history.html",
        {
            "page_obj": page_obj,
            "query": query,
            "selected_filter": selected_filter,
            "filter_query": filter_params.urlencode(),
            "query_suffix": query_suffix,
            "date_filters": FILTERS,
        },
    )
