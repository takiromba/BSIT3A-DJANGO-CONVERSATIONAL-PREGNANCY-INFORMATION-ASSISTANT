from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import render

from .accounts import _display_name
from .models import ChatConversation, ChatMessage, PregnancyTopic


@login_required(login_url="login")
def home(request):
    topics_by_category = {
        topic.category: topic
        for topic in PregnancyTopic.objects.filter(is_published=True)
    }
    recent_conversations = ChatConversation.objects.filter(
        user=request.user
    ).prefetch_related(
        Prefetch(
            "messages",
            queryset=ChatMessage.objects.filter(
                role=ChatMessage.Role.USER,
            ).order_by("-created_at"),
            to_attr="recent_user_messages",
        )
    )[
        :5
    ]
    last_activity = (
        ChatConversation.objects.filter(user=request.user)
        .order_by("-updated_at")
        .first()
    )
    category_count = (
        PregnancyTopic.objects.filter(is_published=True)
        .values_list("category", flat=True)
        .distinct()
        .count()
    )
    return render(
        request,
        "pregnancy/dashboard.html",
        {
            "display_name": _display_name(request.user),
            "question_count": ChatMessage.objects.filter(
                conversation__user=request.user,
                role=ChatMessage.Role.USER,
            ).count(),
            "last_activity": last_activity,
            "recent_conversations": recent_conversations,
            "topic_count": PregnancyTopic.objects.filter(is_published=True).count(),
            "category_count": category_count,
            "categories": [
                {**category, "topic": topics_by_category.get(category["value"])}
                for category in PregnancyTopic.category_metadata()
            ],
        },
    )
