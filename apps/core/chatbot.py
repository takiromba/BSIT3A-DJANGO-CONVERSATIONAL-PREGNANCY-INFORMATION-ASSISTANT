import logging
import re
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import BadRequest
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.views.decorators.http import require_http_methods, require_POST

from .models import FAQ, ChatConversation, ChatMessage
from .onboarding import post_authentication_redirect
from .services import ai_provider
from .services.pregnabot import (
    Answer,
    is_urgent,
    reply,
    retrieve_answers,
    search_answers,
)

logger = logging.getLogger(__name__)
BR_LINE_BREAK_RE = re.compile(r"\\?(?:<br\s*/?>|&lt;br\s*/?&gt;)", re.IGNORECASE)
ESCAPED_NEWLINE_RE = re.compile(r"(?:\\+r\\+n|\\+n|\\+r)")
LIST_MARKER_RE = re.compile(
    r"^\s*\\?(?:(?P<bullet>[-*+])|(?P<number>\d+[.)]))\s+(?P<content>.*)$"
)

MAX_CONTEXT_MESSAGES = 6
MAX_CONTEXT_MESSAGE_LENGTH = 1200
MAX_QUESTIONS_PER_SUBMISSION = 5
PUBLIC_CHAT_SESSION_KEY = "public_chat_messages"

INTRODUCTION_RESPONSE = (
    "Hello! I’m PregnaBot, a pregnancy information assistant. I can help you "
    "explore general pregnancy information from the published information "
    "library. I can’t diagnose or replace advice from a healthcare professional."
)

FOLLOW_UP_PREFIXES = (
    "and ",
    "also ",
    "what about it",
    "what about that",
    "what about the symptoms",
    "why is that ",
    "why is it ",
    "why does that ",
    "why does it ",
    "why are they ",
    "why are these ",
    "why are those ",
    "why is this ",
    "can you explain more",
    "can you explain further",
    "can you explain that",
    "can you explain it",
    "can you explain why",
    "can you give me an example",
    "can you give me examples",
    "can you give me example",
    "could you give me an example",
    "could you give me examples",
    "give me an example",
    "give me examples",
    "give me example",
    "what should i do about it",
    "what should i do about this",
    "what should i do with it",
    "what should i do now",
    "what do i do about it",
    "what do i do about this",
    "what do i do with it",
    "how much is that",
    "how much should i take",
    "how many should i take",
    "how often should i take",
    "how many are there",
    "how often should i do that",
    "how long does it",
    "how do i do that",
    "is that ",
    "is it normal",
    "are they ",
    "are those ",
    "are these ",
    "are there any risks",
    "are there any other symptoms",
    "does it ",
    "does that ",
    "will it ",
    "will that ",
)

CONTEXT_CLARIFICATION = (
    "I couldn’t find published pregnancy information that answers this specific "
    "follow-up. Could you clarify what aspect of the previous topic you mean, "
    "or ask your healthcare professional for advice about your situation?"
)

PARAPHRASE_SYSTEM_PROMPT = (
    "You are PregnaBot, a pregnancy information assistant. Answer the current "
    "question using only facts supported by the supplied published answer. Use "
    "the previous exchange only to understand references such as 'that' or 'it'; "
    "do not answer an earlier question instead of the current one. Do not add "
    "medical claims, diagnoses, doses, or sources. For a follow-up that the "
    "published answer does not support, return exactly "
    "'UNSUPPORTED_FOLLOW_UP'. Never repeat the published answer verbatim as a "
    "substitute for answering a follow-up. Keep urgent symptoms guidance direct "
    "and do not tell the user to wait."
)

UNSUPPORTED_FOLLOW_UP = "UNSUPPORTED_FOLLOW_UP"


def _recent_context(conversation):
    if conversation is None:
        return []
    recent = list(
        conversation.messages.order_by("-created_at", "-pk")[:MAX_CONTEXT_MESSAGES]
    )
    return [
        {
            "role": message.role,
            "content": message.content[:MAX_CONTEXT_MESSAGE_LENGTH],
            "title": message.answer_title,
        }
        for message in reversed(recent)
        if message.role in {ChatMessage.Role.USER, ChatMessage.Role.ASSISTANT}
    ]


def _is_greeting_or_introduction(question):
    normalized = re.sub(r"[^\w\s]", " ", question.casefold())
    normalized = " ".join(normalized.split())
    if normalized in {
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "hi pregnabot",
        "hello pregnabot",
        "hey pregnabot",
    }:
        return True
    return any(
        phrase in normalized
        for phrase in (
            "introduce yourself",
            "tell me about yourself",
            "who are you",
            "what can you do",
        )
    )


def _is_contextual_follow_up(question):
    normalized = " ".join(re.sub(r"[^\w\s]", " ", question.casefold()).split())
    if normalized.startswith(
        (
            "what should i do if ",
            "what should i do when ",
            "what should i do for ",
            "are there any risks of ",
            "are there any risks associated with ",
        )
    ):
        return False
    return normalized.startswith(FOLLOW_UP_PREFIXES)


def _latest_exchange(history):
    last_user_index = next(
        (
            index
            for index in range(len(history) - 1, -1, -1)
            if history[index]["role"] == ChatMessage.Role.USER
        ),
        None,
    )
    if last_user_index is None:
        return []
    return history[last_user_index:]


def _submitted_questions(question):
    lines = [line.strip() for line in question.splitlines() if line.strip()]
    if len(lines) > 1 and all(line.endswith((".", "?", "!")) for line in lines):
        return lines
    return [question]


def _retrieval_query(question, relevant_history):
    previous_user = next(
        (
            item
            for item in reversed(relevant_history)
            if item["role"] == ChatMessage.Role.USER
        ),
        None,
    )
    if previous_user is None:
        return question

    if _is_contextual_follow_up(previous_user["content"]):
        previous_answer = next(
            (
                item
                for item in reversed(relevant_history)
                if item["role"] == ChatMessage.Role.ASSISTANT
            ),
            None,
        )
        if previous_answer and previous_answer["title"]:
            return previous_answer["title"]
    return previous_user["content"]


def _assistant_answers(question, history, request):
    if is_urgent(question):
        return search_answers(question)

    if _is_greeting_or_introduction(question):
        return [Answer(title=question, content=INTRODUCTION_RESPONSE)]

    relevant_history = []
    is_follow_up = _is_contextual_follow_up(question)
    if is_follow_up:
        relevant_history = _latest_exchange(history)
        if not relevant_history:
            return [Answer(title=question, content=CONTEXT_CLARIFICATION)]
        matches = retrieve_answers(
            _retrieval_query(question, relevant_history), limit=1
        )
        if not matches:
            return [Answer(title=question, content=CONTEXT_CLARIFICATION)]
    else:
        matches = retrieve_answers(question, limit=1)
    if not matches:
        return search_answers(question)
    return [
        _paraphrase_answer(
            question,
            matches[0],
            relevant_history,
            request,
        )
    ]


def _paraphrase_answer(question, answer, relevant_history, request):
    previous_user_question = next(
        (
            item["content"]
            for item in reversed(relevant_history)
            if item["role"] == ChatMessage.Role.USER
        ),
        "",
    )
    previous_assistant_answer = next(
        (
            item["content"]
            for item in reversed(relevant_history)
            if item["role"] == ChatMessage.Role.ASSISTANT
        ),
        "",
    )
    prompt = f"Current question:\n{question}\n"
    if previous_user_question:
        prompt += f"\nRelevant earlier question:\n{previous_user_question}\n"
    if previous_assistant_answer:
        prompt += f"\nRelevant earlier answer:\n{previous_assistant_answer}\n"
    prompt += f"\nPublished answer:\n{answer.content}"

    try:
        content = ai_provider.generate_response(
            [
                {"role": "system", "content": PARAPHRASE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
    except ai_provider.ProviderError as exc:
        logger.warning(
            "Configured AI provider response generation failed (%s).",
            type(exc).__name__,
        )
        if relevant_history:
            messages.warning(
                request,
                "PregnaBot could not answer this follow-up from the published information. "
                "Please clarify your question or ask a healthcare professional.",
            )
            return Answer(title=answer.title, content=CONTEXT_CLARIFICATION)
        messages.warning(
            request,
            "PregnaBot could not generate a response. The published answer is shown instead.",
        )
        return answer

    if relevant_history and (
        content.strip() == UNSUPPORTED_FOLLOW_UP
        or content.strip().casefold() == answer.content.strip().casefold()
    ):
        return Answer(title=answer.title, content=CONTEXT_CLARIFICATION)

    return Answer(
        title=answer.title,
        content=content,
        source_name=answer.source_name,
        source_url=answer.source_url,
    )


def _pregnabot_reply(question):
    return reply(question)


def _format_chat_content(content):
    content = BR_LINE_BREAK_RE.sub("\n", content)
    content = ESCAPED_NEWLINE_RE.sub("\n", content)
    blocks = []
    plain_lines = []
    list_items = []
    list_tag = None

    def flush_plain_lines():
        if plain_lines:
            blocks.append(
                format_html_join(
                    format_html("<br>"),
                    "{}",
                    ((line,) for line in plain_lines),
                )
            )
            plain_lines.clear()

    def flush_list_items():
        nonlocal list_tag
        if list_items:
            items_html = format_html_join(
                "",
                "<li>{}</li>",
                ((item,) for item in list_items),
            )
            blocks.append(format_html("<{0}>{1}</{0}>", list_tag, items_html))
            list_items.clear()
            list_tag = None

    for line in content.splitlines():
        if not line.strip():
            continue
        marker = LIST_MARKER_RE.match(line)
        if marker:
            flush_plain_lines()
            next_list_tag = "ol" if marker.group("number") else "ul"
            if list_tag and list_tag != next_list_tag:
                flush_list_items()
            list_tag = next_list_tag
            list_items.append(marker.group("content"))
        else:
            flush_list_items()
            plain_lines.append(line)

    flush_list_items()
    flush_plain_lines()
    return format_html_join(
        format_html("<br>"),
        "{}",
        ((block,) for block in blocks),
    )


@require_http_methods(["GET", "POST"])
def chatbot(request, conversation_id=None):
    is_authenticated = request.user.is_authenticated
    if not is_authenticated and conversation_id is not None:
        return redirect("login")

    if is_authenticated:
        request.session.pop(PUBLIC_CHAT_SESSION_KEY, None)
        public_messages = []
    else:
        public_messages = request.session.get(PUBLIC_CHAT_SESSION_KEY, [])

    conversation = None
    if conversation_id is not None:
        conversation = get_object_or_404(
            ChatConversation,
            pk=conversation_id,
            user=request.user,
        )

    if request.method == "POST":
        submitted_text = request.POST.get("question", "").strip()
        questions = _submitted_questions(submitted_text)
        question = questions[0]
        if not question:
            messages.error(request, "Please enter a question before sending.")
            return redirect(
                "chat_conversation" if conversation else "chatbot",
                **({"conversation_id": conversation.pk} if conversation else {}),
            )
        if len(submitted_text) > 4000:
            messages.error(request, "Please keep your question under 4,000 characters.")
            return redirect(
                "chat_conversation" if conversation else "chatbot",
                **({"conversation_id": conversation.pk} if conversation else {}),
            )
        if len(questions) > MAX_QUESTIONS_PER_SUBMISSION:
            messages.error(
                request,
                f"Please send no more than {MAX_QUESTIONS_PER_SUBMISSION} questions at a time.",
            )
            return redirect(
                "chat_conversation" if conversation else "chatbot",
                **({"conversation_id": conversation.pk} if conversation else {}),
            )

        if conversation is None and is_authenticated:
            conversation = ChatConversation.objects.create(
                user=request.user,
                title=question[:117] + ("…" if len(question) > 117 else ""),
            )
        for current_question in questions:
            if conversation is not None:
                history = _recent_context(conversation)
                ChatMessage.objects.create(
                    conversation=conversation,
                    role=ChatMessage.Role.USER,
                    content=current_question,
                )
            else:
                history = [
                    {
                        "role": message["role"],
                        "content": message["content"][:MAX_CONTEXT_MESSAGE_LENGTH],
                        "title": message["answer_title"],
                    }
                    for message in public_messages[-MAX_CONTEXT_MESSAGES:]
                ]
                public_messages.append(
                    {
                        "role": ChatMessage.Role.USER,
                        "answer_title": "",
                        "content": current_question,
                        "source_name": "",
                        "source_url": "",
                        "created_at": timezone.now().isoformat(),
                    }
                )
            answers = _assistant_answers(current_question, history, request)
            if conversation is not None:
                for answer in answers:
                    ChatMessage.objects.create(
                        conversation=conversation,
                        role=ChatMessage.Role.ASSISTANT,
                        answer_title=answer.title[:280],
                        content=answer.content,
                        source_name=answer.source_name,
                        source_url=answer.source_url,
                    )
            else:
                public_messages.extend(
                    {
                        "role": ChatMessage.Role.ASSISTANT,
                        "answer_title": answer.title[:280],
                        "content": answer.content,
                        "source_name": answer.source_name,
                        "source_url": answer.source_url,
                        "created_at": timezone.now().isoformat(),
                    }
                    for answer in answers
                )
        if conversation is not None:
            conversation.save(update_fields=["updated_at"])
            return redirect("chat_conversation", conversation_id=conversation.pk)
        request.session[PUBLIC_CHAT_SESSION_KEY] = public_messages[
            -MAX_CONTEXT_MESSAGES:
        ]
        return redirect("chatbot")

    page_obj = None
    if conversation is not None:
        message_list = conversation.messages.all()
        paginator = Paginator(message_list, 30)
        page_obj = paginator.get_page(request.GET.get("page", paginator.num_pages or 1))
    if conversation is not None:
        chat_messages = page_obj.object_list
    elif not is_authenticated:
        chat_messages = [
            {
                **message,
                "created_at": datetime.fromisoformat(message["created_at"]),
            }
            for message in public_messages
        ]
    else:
        chat_messages = []
    for message in chat_messages:
        if conversation is None:
            message["rendered_content"] = _format_chat_content(message["content"])
        else:
            message.rendered_content = _format_chat_content(message.content)
    return render(
        request,
        "pregnancy/chatbot.html",
        {
            "conversation": conversation,
            "chat_messages": chat_messages,
            "message_page": page_obj,
            "recent_conversations": (
                ChatConversation.objects.filter(user=request.user).order_by(
                    "-updated_at"
                )[:8]
                if is_authenticated
                else []
            ),
            "suggested_questions": FAQ.objects.filter(
                is_published=True,
            ).order_by(
                "position", "pk"
            )[:5],
        },
    )


def public_home(request):
    if request.user.is_authenticated:
        return post_authentication_redirect(request.user)
    return chatbot(request)


@require_http_methods(["GET"])
def new_public_chat(request):
    if not request.user.is_authenticated:
        request.session.pop(PUBLIC_CHAT_SESSION_KEY, None)
    return redirect("chatbot")


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
