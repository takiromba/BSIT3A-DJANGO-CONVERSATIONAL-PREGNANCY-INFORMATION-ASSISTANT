from datetime import timedelta
import re

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .models import ChatConversation, ChatMessage, FAQ, PregnancyTopic

User = get_user_model()

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=1)
INVALID_LOGIN_MESSAGE = 'Invalid username or password.'
LOCKED_MESSAGE = 'Too many failed attempts. Locked for 1 minute.'


def _reset_lock_state(request):
    request.session['failed_attempts'] = 0
    request.session['lock_time'] = None


def _get_lock_state(request):
    failed_attempts = request.session.get('failed_attempts', 0)
    lock_time = request.session.get('lock_time')

    if not lock_time:
        return failed_attempts, None

    try:
        unlock_time = timezone.datetime.fromisoformat(lock_time)
    except (TypeError, ValueError):
        _reset_lock_state(request)
        return 0, None

    if timezone.now() < unlock_time:
        remaining = int((unlock_time - timezone.now()).total_seconds())
        return failed_attempts, remaining

    _reset_lock_state(request)
    return 0, None


def _set_lock_state(request):
    lock_until = timezone.now() + LOCK_DURATION
    request.session['failed_attempts'] = MAX_FAILED_ATTEMPTS
    request.session['lock_time'] = lock_until.isoformat()
    return int(LOCK_DURATION.total_seconds())


def _validate_registration_data(data):
    errors = {}

    username = data.get('username', '').strip()
    first_name = data.get('first_name', '').strip()
    last_name = data.get('last_name', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    if not username:
        errors['username'] = 'Username is required.'
    elif User.objects.filter(username=username).exists():
        errors['username'] = 'Username already taken.'

    if not first_name:
        errors['first_name'] = 'First name is required.'

    if not last_name:
        errors['last_name'] = 'Last name is required.'

    if not email:
        errors['email'] = 'Email is required.'
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors['email'] = 'Enter a valid email address.'
        else:
            if User.objects.filter(email=email).exists():
                errors['email'] = 'Email already registered.'

    if not password:
        errors['password'] = 'Password is required.'
    elif len(password) < 8:
        errors['password'] = 'Password must be at least 8 characters.'
    else:
        try:
            validate_password(password)
        except ValidationError as exc:
            errors['password'] = ' '.join(exc.messages)

    if password != confirm_password:
        errors['confirm_password'] = 'Passwords do not match.'

    return errors


@require_http_methods(['GET', 'POST'])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    failed_attempts, remaining = _get_lock_state(request)
    if remaining is not None:
        messages.error(request, f'Too many failed attempts. Try again in {remaining} seconds.')
        return render(request, 'auth/login.html', {'locked': True, 'remaining': remaining})

    if request.method == 'GET':
        return render(request, 'auth/login.html')

    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')
    user = authenticate(request, username=username, password=password)

    if user is not None:
        _reset_lock_state(request)
        login(request, user)
        return redirect('dashboard')

    failed_attempts += 1
    request.session['failed_attempts'] = failed_attempts
    if failed_attempts >= MAX_FAILED_ATTEMPTS:
        remaining = _set_lock_state(request)
        messages.error(request, LOCKED_MESSAGE)
        return render(request, 'auth/login.html', {'locked': True, 'remaining': remaining})

    remaining_attempts = MAX_FAILED_ATTEMPTS - failed_attempts
    messages.error(request, f'{INVALID_LOGIN_MESSAGE} {remaining_attempts} attempts remaining.')
    return render(request, 'auth/login.html')


@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')


@login_required(login_url='login')
def home(request):
    topics_by_category = {
        topic.category: topic
        for topic in PregnancyTopic.objects.filter(is_published=True)
    }
    recent_conversations = (
        ChatConversation.objects.filter(user=request.user)
        .prefetch_related(
            Prefetch(
                'messages',
                queryset=ChatMessage.objects.filter(
                    role=ChatMessage.Role.USER,
                ).order_by('-created_at'),
                to_attr='recent_user_messages',
            )
        )[:5]
    )
    last_activity = (
        ChatConversation.objects.filter(user=request.user)
        .order_by('-updated_at')
        .first()
    )
    return render(request, 'pregnancy/dashboard.html', {
        'display_name': _display_name(request.user),
        'question_count': ChatMessage.objects.filter(
            conversation__user=request.user,
            role=ChatMessage.Role.USER,
        ).count(),
        'last_activity': last_activity,
        'recent_conversations': recent_conversations,
        'topic_count': PregnancyTopic.objects.filter(is_published=True).count(),
        'categories': [
            {**category, 'topic': topics_by_category.get(category['value'])}
            for category in CATEGORY_META
        ],
    })


@require_http_methods(['GET', 'POST'])
def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'GET':
        return render(request, 'auth/register.html')

    form_data = {
        'username': request.POST.get('username', ''),
        'first_name': request.POST.get('first_name', ''),
        'last_name': request.POST.get('last_name', ''),
        'email': request.POST.get('email', ''),
        'password': request.POST.get('password', ''),
        'confirm_password': request.POST.get('confirm_password', ''),
    }

    errors = _validate_registration_data(form_data)
    if errors:
        return render(request, 'auth/register.html', {'errors': errors, 'form_data': form_data})

    user = User.objects.create_user(
        username=form_data['username'].strip(),
        first_name=form_data['first_name'].strip(),
        last_name=form_data['last_name'].strip(),
        email=form_data['email'].strip(),
        password=form_data['password'],
    )
    login(request, user)
    return redirect('dashboard')


CATEGORY_META = [
    {
        'value': PregnancyTopic.Category.SYMPTOMS,
        'title': 'Common Pregnancy Symptoms',
        'icon': 'fa-person-circle-question',
        'color': 'rose',
    },
    {
        'value': PregnancyTopic.Category.NUTRITION,
        'title': 'Nutrition & Healthy Practices',
        'icon': 'fa-apple-whole',
        'color': 'mint',
    },
    {
        'value': PregnancyTopic.Category.PRENATAL,
        'title': 'Prenatal Care',
        'icon': 'fa-kit-medical',
        'color': 'blue',
    },
    {
        'value': PregnancyTopic.Category.DEVELOPMENT,
        'title': 'Stages & Fetal Development',
        'icon': 'fa-baby',
        'color': 'lavender',
    },
    {
        'value': PregnancyTopic.Category.CONCERNS,
        'title': 'Common Concerns',
        'icon': 'fa-heart',
        'color': 'peach',
    },
    {
        'value': PregnancyTopic.Category.WARNING_SIGNS,
        'title': 'Warning Signs',
        'icon': 'fa-triangle-exclamation',
        'color': 'rose',
    },
]

URGENT_PHRASES = (
    'heavy bleeding',
    'heavy vaginal bleeding',
    'severe bleeding',
    'severe vaginal bleeding',
    'chest pain',
    'difficulty breathing',
    'trouble breathing',
    'unable to breathe',
    "can't breathe",
    'seizure',
    'passed out',
    'fainted',
    'severe abdominal pain',
    'severe belly pain',
    'severe headache',
    'vision changes',
    'baby stopped moving',
    'no fetal movement',
    'decreased fetal movement',
    'reduced fetal movement',
)

STOP_WORDS = {
    'about', 'after', 'also', 'been', 'being', 'can', 'could', 'does', 'from',
    'have', 'help', 'here', 'into', 'just', 'more', 'most', 'much', 'need',
    'should', 'some', 'tell', 'that', 'them', 'there', 'they', 'this', 'what',
    'when', 'where', 'which', 'with', 'would', 'your',
}


def _display_name(user):
    return user.get_full_name().strip() or user.get_username()


@login_required(login_url='login')
def pregnancy_information(request):
    query = request.GET.get('q', '').strip()
    topics = PregnancyTopic.objects.filter(is_published=True)
    category = request.GET.get('category', '').strip()
    category_values = {value for value, _label in PregnancyTopic.Category.choices}
    if category not in category_values:
        category = ''
    if category:
        topics = topics.filter(category=category)
    if query:
        topics = topics.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(content__icontains=query)
        )
    topic_list = list(topics)
    topic_groups = [
        {
            **category,
            'topics': [topic for topic in topic_list if topic.category == category['value']],
        }
        for category in CATEGORY_META
        if any(topic.category == category['value'] for topic in topic_list)
    ]
    return render(request, 'pregnancy/information.html', {
        'query': query,
        'selected_category': category,
        'topic_groups': topic_groups,
        'topic_count': len(topic_list),
    })


@login_required(login_url='login')
def topic_detail(request, slug):
    topic = get_object_or_404(
        PregnancyTopic.objects.filter(is_published=True),
        slug=slug,
    )
    return render(request, 'pregnancy/topic_detail.html', {
        'topic': topic,
        'faqs': topic.faqs.filter(is_published=True),
    })


@login_required(login_url='login')
def faq_list(request):
    query = request.GET.get('q', '').strip()
    faqs = FAQ.objects.filter(is_published=True).select_related('topic')
    if query:
        faqs = faqs.filter(
            Q(question__icontains=query)
            | Q(answer__icontains=query)
            | Q(topic__title__icontains=query)
        )
    return render(request, 'pregnancy/faq.html', {
        'faqs': faqs,
        'query': query,
    })


def _pregnabot_reply(question):
    normalized_question = question.casefold()
    if any(phrase in normalized_question for phrase in URGENT_PHRASES):
        return (
            'These symptoms may need urgent assessment. Please contact your '
            'maternity-care team or local emergency services now. Do not wait '
            'for an online response. If symptoms are severe or you feel unsafe, '
            'seek emergency care immediately.'
        )

    terms = list(dict.fromkeys(
        term for term in re.findall(r"[a-zA-Z']{3,}", normalized_question)
        if term not in STOP_WORDS
    ))[:12]
    if not terms:
        return (
            'I could not find a matching answer in the current information '
            'library. Try asking about a specific pregnancy topic, or contact '
            'your healthcare professional for personal advice.'
        )

    faq_query = Q()
    for term in terms:
        faq_query |= Q(question__icontains=term) | Q(answer__icontains=term)
    faq_matches = FAQ.objects.filter(is_published=True).filter(faq_query)
    faq_scores = {}
    for faq in faq_matches:
        answer_text = f'{faq.question} {faq.answer}'.casefold()
        faq_scores[faq.pk] = (
            sum(term in answer_text for term in terms),
            faq,
        )
    if faq_scores:
        best_faq = max(
            faq_scores.values(),
            key=lambda match: (match[0], -match[1].position),
        )[1]
        return best_faq.answer

    topic_query = Q()
    for term in terms:
        topic_query |= (
            Q(title__icontains=term)
            | Q(description__icontains=term)
            | Q(content__icontains=term)
        )
    topic_matches = PregnancyTopic.objects.filter(
        is_published=True,
    ).filter(topic_query)
    topic_scores = {}
    for topic in topic_matches:
        title = topic.title.casefold()
        searchable_text = f'{title} {topic.description} {topic.content}'.casefold()
        topic_scores[topic.pk] = (
            sum(term in title for term in terms) * 2
            + sum(term in searchable_text for term in terms),
            topic,
        )
    if topic_scores:
        best_topic = max(
            topic_scores.values(),
            key=lambda match: (match[0], -match[1].position),
        )[1]
        return f'{best_topic.title}\n\n{best_topic.content}'

    return (
        'I could not find a matching answer in the current information '
        'library. Try the search above or browse Pregnancy Information. '
        'For personal medical advice, please contact your healthcare professional.'
    )


@login_required(login_url='login')
@require_http_methods(['GET', 'POST'])
def chatbot(request, conversation_id=None):
    conversation = None
    if conversation_id is not None:
        conversation = get_object_or_404(
            ChatConversation,
            pk=conversation_id,
            user=request.user,
        )

    if request.method == 'POST':
        question = request.POST.get('question', '').strip()
        if not question:
            messages.error(request, 'Please enter a question before sending.')
            if conversation:
                return redirect('chat_conversation', conversation_id=conversation.pk)
            return redirect('chatbot')
        if len(question) > 4000:
            messages.error(request, 'Please keep your question under 4,000 characters.')
            if conversation:
                return redirect('chat_conversation', conversation_id=conversation.pk)
            return redirect('chatbot')

        if conversation is None:
            conversation = ChatConversation.objects.create(
                user=request.user,
                title=question[:117] + ('…' if len(question) > 117 else ''),
            )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.USER,
            content=question,
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.ASSISTANT,
            content=_pregnabot_reply(question),
        )
        conversation.save(update_fields=['updated_at'])
        return redirect('chat_conversation', conversation_id=conversation.pk)

    if conversation is not None:
        conversation = get_object_or_404(
            ChatConversation.objects.prefetch_related('messages'),
            pk=conversation.pk,
            user=request.user,
        )
    return render(request, 'pregnancy/chatbot.html', {
        'conversation': conversation,
        'chat_messages': conversation.messages.all() if conversation else [],
        'recent_conversations': ChatConversation.objects.filter(
            user=request.user,
        ).order_by('-updated_at')[:8],
    })


@login_required(login_url='login')
@require_http_methods(['GET', 'POST'])
def profile(request):
    errors = {}
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()

        if not first_name:
            errors['first_name'] = 'Please enter your first name.'
        if not last_name:
            errors['last_name'] = 'Please enter your last name.'
        try:
            validate_email(email)
        except ValidationError:
            errors['email'] = 'Please enter a valid email address.'
        else:
            if email and User.objects.filter(email__iexact=email).exclude(
                pk=request.user.pk,
            ).exists():
                errors['email'] = 'That email address is already in use.'

        if not errors:
            request.user.first_name = first_name
            request.user.last_name = last_name
            request.user.email = email
            request.user.save(update_fields=['first_name', 'last_name', 'email'])
            messages.success(request, 'Your profile has been updated.')
            return redirect('profile')

    return render(request, 'pregnancy/profile.html', {
        'display_name': _display_name(request.user),
        'errors': errors,
    })
