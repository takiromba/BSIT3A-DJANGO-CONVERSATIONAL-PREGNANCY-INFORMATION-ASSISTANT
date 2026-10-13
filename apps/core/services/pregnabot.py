import re
from dataclasses import dataclass

from django.db.models import Q
from django.utils.translation import gettext as _

from apps.core.models import FAQ, PregnancyTopic

URGENT_PHRASES = (
    "heavy bleeding",
    "heavy vaginal bleeding",
    "severe bleeding",
    "severe vaginal bleeding",
    "chest pain",
    "difficulty breathing",
    "trouble breathing",
    "unable to breathe",
    "can't breathe",
    "seizure",
    "passed out",
    "fainted",
    "severe abdominal pain",
    "severe belly pain",
    "severe headache",
    "vision changes",
    "baby stopped moving",
    "no fetal movement",
    "decreased fetal movement",
    "reduced fetal movement",
    "matinding pagdurugo",
    "malakas na pagdurugo",
    "hirap huminga",
    "nahihirapang huminga",
    "kombulsyon",
    "nawalan ng malay",
    "nahimatay",
    "matinding pananakit ng tiyan",
    "hindi gumagalaw ang sanggol",
    "bumaba ang galaw ng sanggol",
)

STOP_WORDS = {
    "about",
    "after",
    "also",
    "been",
    "being",
    "can",
    "could",
    "does",
    "from",
    "have",
    "help",
    "here",
    "into",
    "just",
    "more",
    "most",
    "much",
    "need",
    "should",
    "some",
    "tell",
    "that",
    "them",
    "there",
    "they",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
    "ang",
    "mga",
    "sa",
    "ako",
    "ko",
    "ba",
    "na",
    "ng",
    "mo",
    "ito",
    "iyan",
    "nito",
    "para",
    "po",
    "opo",
    "may",
    "kung",
    "ano",
    "paano",
    "kailan",
}


@dataclass(frozen=True)
class Answer:
    title: str
    content: str
    source_name: str = ""
    source_url: str = ""


def is_urgent(question):
    normalized_question = question.casefold()
    return any(phrase in normalized_question for phrase in URGENT_PHRASES)


def _terms(question):
    return list(
        dict.fromkeys(
            term
            for term in re.findall(r"[a-zA-Z']{3,}", question.casefold())
            if term not in STOP_WORDS
        )
    )[:12]


def search_answers(question, limit=3):
    if is_urgent(question):
        return [
            Answer(
                _("Urgent symptoms"),
                _(
                    "These symptoms may need urgent assessment. Please contact your maternity-care team or local emergency services now. Do not wait for an online response. If symptoms are severe or you feel unsafe, seek emergency care immediately."
                ),
            )
        ]

    terms = _terms(question)
    if not terms:
        return [
            Answer(
                _("No matching answer"),
                _(
                    "I could not find a matching answer in the current information library. Try asking about a specific pregnancy topic, or contact your healthcare professional for personal advice."
                ),
            )
        ]

    faq_query = Q()
    topic_query = Q()
    for term in terms:
        faq_query |= Q(question__icontains=term) | Q(answer__icontains=term)
        topic_query |= (
            Q(title__icontains=term)
            | Q(description__icontains=term)
            | Q(content__icontains=term)
        )

    ranked = []
    for faq in (
        FAQ.objects.filter(is_published=True).filter(faq_query).select_related("topic")
    ):
        question_text = faq.question.casefold()
        answer_text = faq.answer.casefold()
        score = sum(term in question_text for term in terms) * 3 + sum(
            term in answer_text for term in terms
        )
        ranked.append(
            (
                score,
                -faq.position,
                -faq.pk,
                Answer(faq.question, faq.answer, faq.source_name, faq.source_url),
            )
        )

    for topic in PregnancyTopic.objects.filter(
        is_published=True,
    ).filter(topic_query):
        title = topic.title.casefold()
        score = (
            sum(term in title for term in terms) * 3
            + sum(term in topic.description.casefold() for term in terms) * 2
            + sum(term in topic.content.casefold() for term in terms)
        )
        ranked.append(
            (
                score,
                -topic.position,
                -topic.pk,
                Answer(topic.title, topic.content, topic.source_name, topic.source_url),
            )
        )

    ranked.sort(key=lambda result: result[:3], reverse=True)
    matches = [item[3] for item in ranked[:limit] if item[0] > 0]
    return matches or [
        Answer(
            _("No matching answer"),
            _(
                "I could not find a matching answer in the current information library. Try asking about a specific pregnancy topic, or contact your healthcare professional for personal advice."
            ),
        )
    ]


def reply(question):
    """Compatibility helper for callers that only need one answer string."""
    return search_answers(question, limit=1)[0].content
