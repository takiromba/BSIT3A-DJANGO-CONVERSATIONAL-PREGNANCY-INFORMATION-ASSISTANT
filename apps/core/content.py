from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from .models import FAQ, PregnancyTopic


def pregnancy_information(request):
    query = request.GET.get("q", "").strip()
    topics = PregnancyTopic.objects.filter(is_published=True)
    category = request.GET.get("category", "").strip()
    category_values = {value for value, _label in PregnancyTopic.Category.choices}
    if category not in category_values:
        category = ""
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
            **category_metadata,
            "topics": [
                topic
                for topic in topic_list
                if topic.category == category_metadata["value"]
            ],
        }
        for category_metadata in PregnancyTopic.category_metadata()
        if any(topic.category == category_metadata["value"] for topic in topic_list)
    ]
    return render(
        request,
        "pregnancy/information.html",
        {
            "query": query,
            "selected_category": category,
            "topic_groups": topic_groups,
            "topic_count": len(topic_list),
        },
    )


def topic_detail(request, slug):
    topic = get_object_or_404(
        PregnancyTopic.objects.filter(is_published=True),
        slug=slug,
    )
    return render(
        request,
        "pregnancy/topic_detail.html",
        {
            "topic": topic,
            "faqs": topic.faqs.filter(is_published=True),
        },
    )


def faq_list(request):
    query = request.GET.get("q", "").strip()
    faqs = FAQ.objects.filter(is_published=True).select_related("topic")
    if query:
        faqs = faqs.filter(
            Q(question__icontains=query)
            | Q(answer__icontains=query)
            | Q(topic__title__icontains=query)
        )
    return render(
        request,
        "pregnancy/faq.html",
        {
            "faqs": faqs,
            "query": query,
        },
    )
