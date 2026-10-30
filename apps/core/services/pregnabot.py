import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

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
    "dugo nga nagaguwa",
    "nagaguwa ang dugo",
    "grabe ang sakit ulo",
    "daw malabo ang panulok",
    "malabo ang paningin",
    "difficult breathing",
)

NEGATION_TOKENS = {
    "cannot",
    "cant",
    "didnt",
    "doesnt",
    "dont",
    "hindi",
    "indi",
    "isnt",
    "never",
    "no",
    "not",
    "wala",
    "without",
}

NEGATION_PHRASES = (
    "can t",
    "didn t",
    "doesn t",
    "don t",
    "isn t",
)

UNCERTAINTY_PHRASES = (
    "not sure",
    "not certain",
    "can t tell",
    "cant tell",
    "cannot tell",
    "unsure",
    "hindi ko alam",
    "indi ko sure",
    "wala ko kabalo",
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
    "basta",
    "lang",
    "bala",
    "pirmi",
    "samtang",
    "bisan",
    "wala",
    "ginhimo",
}

GENERIC_PREGNANCY_TERMS = {
    "during",
    "pregnancy",
    "pregnant",
    "while",
}

FOOD_TERMS = {"food", "foods", "eat", "eating"}
FOOD_AVOIDANCE_MARKERS = (
    "avoid",
    "avoidance",
    "unsafe",
    "not safe",
    "should not eat",
    "should not be eaten",
    "shouldn t eat",
    "shouldn t be eaten",
    "do not eat",
    "don t eat",
    "cannot eat",
    "can t eat",
    "can not eat",
    "not consume",
)


@dataclass(frozen=True)
class Answer:
    title: str
    content: str
    source_name: str = ""
    source_url: str = ""


DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "pregnancy_faqs.json"


def _normalize_text(value):
    if not value:
        return ""
    text = value.casefold().replace("&", " and ").replace("’", "'")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _has_food_avoidance_intent(question):
    normalized = _normalize_text(question)
    words = set(normalized.split())
    has_food_term = bool(words & FOOD_TERMS)
    has_avoidance_marker = any(
        marker in normalized for marker in FOOD_AVOIDANCE_MARKERS
    )
    return has_food_term and has_avoidance_marker


def _question_score(query, phrase):
    query_text = _normalize_text(query)
    phrase_text = _normalize_text(phrase)
    if not query_text or not phrase_text:
        return 0.0
    if query_text == phrase_text:
        return 1.0
    if query_text in phrase_text or phrase_text in query_text:
        return 0.9

    query_tokens = {
        token
        for token in query_text.split()
        if len(token) > 2 and token not in STOP_WORDS
    }
    phrase_tokens = {
        token
        for token in phrase_text.split()
        if len(token) > 2 and token not in STOP_WORDS
    }

    if query_tokens and phrase_tokens:
        query_specific = query_tokens - GENERIC_PREGNANCY_TERMS
        phrase_specific = phrase_tokens - GENERIC_PREGNANCY_TERMS
        shared_specific = query_specific & phrase_specific
        if query_specific and phrase_specific and not shared_specific:
            return 0.0
        overlap = len(shared_specific) / max(
            len(query_specific),
            len(phrase_specific),
            1,
        )
        if overlap >= 0.5:
            return 0.7 + overlap * 0.2

        if query_specific and phrase_specific:
            return 0.0

    ratio = SequenceMatcher(None, query_text, phrase_text).ratio()
    return ratio if ratio >= 0.4 else 0.0


def _load_dataset_entries():
    if not DATASET_PATH.exists():
        return []
    try:
        data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    entries = []
    for item in data:
        if not isinstance(item, dict):
            continue
        entries.append(item)
    return entries


DATASET_ENTRIES = _load_dataset_entries()


def is_urgent(question):
    if not question or not question.strip():
        return False

    clauses = re.split(r"[.!?;]+|\bbut\b", question, flags=re.IGNORECASE)
    for raw_clause in clauses:
        clause = _normalize_text(raw_clause)
        for phrase in URGENT_PHRASES:
            normalized_phrase = _normalize_text(phrase)
            start = 0
            while (start := clause.find(normalized_phrase, start)) >= 0:
                prefix = clause[:start]
                if any(uncertainty in prefix for uncertainty in UNCERTAINTY_PHRASES):
                    return True
                preceding_words = prefix.split()[-4:]
                preceding_text = " ".join(preceding_words)
                is_negated = bool(
                    NEGATION_TOKENS.intersection(preceding_words)
                ) or any(
                    phrase in preceding_text for phrase in NEGATION_PHRASES
                )
                if not is_negated:
                    return True
                start += len(normalized_phrase)
    return False


def _terms(question):
    return list(
        dict.fromkeys(
            term
            for term in re.findall(r"[\w']{3,}", _normalize_text(question))
            if term not in STOP_WORDS and len(term) >= 3
        )
    )[:12]


def _has_relevant_terms(terms, title, *content):
    title_text = _normalize_text(title)
    content_text = _normalize_text(" ".join(content))
    if len(terms) == 1:
        return terms[0] in title_text
    matched_terms = sum(term in title_text or term in content_text for term in terms)
    return matched_terms >= 2


def _dataset_answer_matches(question):
    matches = []
    food_avoidance_query = _has_food_avoidance_intent(question)
    for record in DATASET_ENTRIES:
        if record.get("is_published") is not True:
            continue
        variants = [record.get("question", "")]
        variants.extend(record.get("alternate_questions", []) or [])
        if food_avoidance_query and not any(
            _has_food_avoidance_intent(variant) for variant in variants
        ):
            continue
        best_score = max(
            (_question_score(question, variant) for variant in variants if variant),
            default=0.0,
        )
        if best_score <= 0.0:
            continue
        answer = Answer(
            record.get("question", "Pregnancy information"),
            record.get("answer", ""),
            record.get("source_name", ""),
            record.get("source_url", ""),
        )
        matches.append((best_score, record.get("is_warning_sign", False), answer))
    matches.sort(key=lambda result: (result[1], result[0]), reverse=True)
    return matches


def retrieve_answers(question, limit=3):
    """Return matching published knowledge without an urgent/no-match fallback."""
    food_avoidance_query = _has_food_avoidance_intent(question)
    terms = _terms(question)
    faq_query = Q()
    topic_query = Q()
    if terms:
        for term in terms:
            faq_query |= Q(question__icontains=term) | Q(answer__icontains=term)
            topic_query |= (
                Q(title__icontains=term)
                | Q(description__icontains=term)
                | Q(content__icontains=term)
            )

    ranked = []
    if terms:
        for faq in (
            FAQ.objects.filter(is_published=True)
            .filter(faq_query)
            .select_related("topic")
        ):
            if food_avoidance_query and not _has_food_avoidance_intent(faq.question):
                continue
            question_text = faq.question.casefold()
            answer_text = faq.answer.casefold()
            if not _has_relevant_terms(terms, faq.question, faq.answer):
                continue
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

        topics = PregnancyTopic.objects.filter(is_published=True).filter(topic_query)
        if food_avoidance_query:
            topics = topics.none()
        for topic in topics:
            title = topic.title.casefold()
            if not _has_relevant_terms(
                terms,
                topic.title,
                topic.description,
                topic.content,
            ):
                continue
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
                    Answer(
                        topic.title, topic.content, topic.source_name, topic.source_url
                    ),
                )
            )

    ranked.sort(key=lambda result: result[:3], reverse=True)
    dataset_matches = _dataset_answer_matches(question)
    combined = [(score, 0, answer) for score, _, _, answer in ranked if score > 0]
    combined.extend(
        (match_score * 10 + (3 if is_warning else 0), 1 if is_warning else 0, answer)
        for match_score, is_warning, answer in dataset_matches
    )
    combined.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [answer for _, _, answer in combined[:limit]]


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

    matches = retrieve_answers(question, limit=limit)
    if matches:
        return matches
    return [
        Answer(
            _("No matching answer"),
            _(
                "I could not find a sufficiently relevant answer in my current pregnancy information database. Please try rephrasing your question or browse the Pregnancy Information section. For personal medical concerns, contact a qualified healthcare professional."
            ),
        )
    ]


def reply(question):
    """Compatibility helper for callers that only need one answer string."""
    return search_answers(question, limit=1)[0].content
