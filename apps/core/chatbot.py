from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import BadRequest
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .models import FAQ, ChatConversation, ChatMessage
from .services.pregnabot import reply, search_answers


def _pregnabot_reply(question):
    return reply(question)


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def chatbot(request, conversation_id=None):
    conversation = None
    if conversation_id is not None:
        conversation = get_object_or_404(
            ChatConversation,
            pk=conversation_id,
            user=request.user,
        )

    if request.method == "POST":
        question = request.POST.get("question", "").strip()
        if not question:
            messages.error(request, "Please enter a question before sending.")
            return redirect(
                "chat_conversation" if conversation else "chatbot",
                **({"conversation_id": conversation.pk} if conversation else {}),
            )
        if len(question) > 4000:
            messages.error(request, "Please keep your question under 4,000 characters.")
            return redirect(
                "chat_conversation" if conversation else "chatbot",
                **({"conversation_id": conversation.pk} if conversation else {}),
            )

        if conversation is None:
            conversation = ChatConversation.objects.create(
                user=request.user,
                title=question[:117] + ("…" if len(question) > 117 else ""),
            )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.USER,
            content=question,
        )
        for answer in search_answers(question):
            ChatMessage.objects.create(
                conversation=conversation,
                role=ChatMessage.Role.ASSISTANT,
                answer_title=answer.title,
                content=answer.content,
                source_name=answer.source_name,
                source_url=answer.source_url,
            )
        conversation.save(update_fields=["updated_at"])
        return redirect("chat_conversation", conversation_id=conversation.pk)

    page_obj = None
    if conversation is not None:
        message_list = conversation.messages.all()
        paginator = Paginator(message_list, 30)
        page_obj = paginator.get_page(request.GET.get("page", paginator.num_pages or 1))
    return render(
        request,
        "pregnancy/chatbot.html",
        {
            "conversation": conversation,
            "chat_messages": page_obj.object_list if page_obj else [],
            "message_page": page_obj,
            "recent_conversations": ChatConversation.objects.filter(
                user=request.user,
            ).order_by("-updated_at")[:8],
            "suggested_questions": FAQ.objects.filter(
                is_published=True,
            ).order_by(
                "position", "pk"
            )[:5],
        },
    )


@login_required(login_url="login")
@require_POST
def rename_conversation(request, conversation_id):
    conversation = get_object_or_404(
        ChatConversation,
        pk=conversation_id,
        user=request.user,
    )
    title = request.POST.get("title", "").strip()
    if not title or len(title) > 120:
        messages.error(
            request, "Conversation title must be between 1 and 120 characters."
        )
    else:
        conversation.title = title
        conversation.save(update_fields=["title", "updated_at"])
        messages.success(request, "Conversation renamed.")
    return redirect("chat_conversation", conversation_id=conversation.pk)


@login_required(login_url="login")
@require_POST
def delete_conversation(request, conversation_id):
    conversation = get_object_or_404(
        ChatConversation,
        pk=conversation_id,
        user=request.user,
    )
    conversation.delete()
    messages.success(request, "Conversation deleted.")
    return redirect("chatbot")


@login_required(login_url="login")
def export_conversation(request, conversation_id):
    conversation = get_object_or_404(
        ChatConversation.objects.prefetch_related("messages"),
        pk=conversation_id,
        user=request.user,
    )
    lines = [conversation.title, ""]
    for message in conversation.messages.all():
        label = "You" if message.role == ChatMessage.Role.USER else "PregnaBot"
        title = f" — {message.answer_title}" if message.answer_title else ""
        lines.extend(
            (
                f"{label}{title} ({message.created_at:%Y-%m-%d %H:%M})",
                message.content,
                "",
            )
        )
    response = HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="pregnabot-chat-{conversation.pk}.txt"'
    )
    return response


@login_required(login_url="login")
@require_POST
def message_feedback(request, message_id):
    helpful = request.POST.get("helpful")
    if helpful not in {"true", "false"}:
        raise BadRequest("Feedback value must be true or false.")
    message = get_object_or_404(
        ChatMessage.objects.filter(
            conversation__user=request.user,
            role=ChatMessage.Role.ASSISTANT,
        ),
        pk=message_id,
    )
    message.helpful = helpful == "true"
    message.save(update_fields=["helpful"])
    messages.success(request, "Thanks for sharing your feedback.")
    return redirect("chat_conversation", conversation_id=message.conversation_id)


def _is_superuser(user):
    return user.is_superuser


@login_required(login_url="login")
@user_passes_test(_is_superuser, login_url="dashboard")
def feedback_analytics(request):
    feedback = ChatMessage.objects.filter(
        role=ChatMessage.Role.ASSISTANT,
        helpful__isnull=False,
    )
    totals = feedback.aggregate(
        positive=Count("pk", filter=Q(helpful=True)),
        negative=Count("pk", filter=Q(helpful=False)),
    )
    unanswered_count = ChatMessage.objects.filter(
        role=ChatMessage.Role.ASSISTANT,
        content__icontains="could not find a matching answer",
    ).count()
    top_questions = (
        ChatMessage.objects.filter(
            role=ChatMessage.Role.USER,
            conversation__messages__helpful__isnull=False,
        )
        .values("content")
        .annotate(
            feedback_count=Count(
                "conversation__messages",
                filter=Q(
                    conversation__messages__role=ChatMessage.Role.ASSISTANT,
                    conversation__messages__helpful__isnull=False,
                ),
            )
        )
        .order_by("-feedback_count", "content")[:10]
    )
    return render(
        request,
        "pregnancy/feedback_analytics.html",
        {
            "totals": totals,
            "unanswered_count": unanswered_count,
            "top_questions": top_questions,
        },
    )
