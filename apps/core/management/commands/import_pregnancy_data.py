import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.core.models import FAQ, PregnancyTopic

CATEGORY_LABELS = {
    "symptoms": "Common Pregnancy Symptoms",
    "nutrition": "Nutrition and Healthy Practices",
    "prenatal": "Prenatal Care",
    "development": "Pregnancy Stages and Fetal Development",
    "concerns": "Common Pregnancy Concerns",
    "warning-signs": "Warning Signs and When to Seek Medical Care",
}

CATEGORY_ICONS = {
    "symptoms": "fa-person-circle-question",
    "nutrition": "fa-apple-whole",
    "prenatal": "fa-kit-medical",
    "development": "fa-baby",
    "concerns": "fa-heart",
    "warning-signs": "fa-triangle-exclamation",
}


class Command(BaseCommand):
    help = "Import reviewed pregnancy FAQs and category metadata from the JSON dataset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(
                Path(__file__).resolve().parents[2] / "data" / "pregnancy_faqs.json"
            ),
            help="Path to the import dataset JSON file.",
        )

    def handle(self, *args, **options):
        dataset_path = Path(options["file"])
        if not dataset_path.exists():
            raise CommandError(f"Dataset file was not found: {dataset_path}")

        try:
            records = json.loads(dataset_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"The dataset file is not valid JSON: {exc}") from exc

        if not isinstance(records, list):
            raise CommandError("The dataset root must be a list of FAQ records.")

        created_topics = 0
        updated_topics = 0
        created_faqs = 0
        updated_faqs = 0
        skipped = 0

        with transaction.atomic():
            for index, record in enumerate(records, start=1):
                if not isinstance(record, dict):
                    skipped += 1
                    self.stderr.write(
                        self.style.WARNING(
                            f"Skipping item #{index}: expected an object, received {type(record).__name__}."
                        )
                    )
                    continue

                category = (record.get("category") or "").strip()
                question = (record.get("question") or "").strip()
                answer = (record.get("answer") or "").strip()
                source_name = (record.get("source_name") or "").strip()
                source_url = (record.get("source_url") or "").strip()
                is_published = bool(record.get("is_published", True))

                if not category:
                    skipped += 1
                    self.stderr.write(
                        self.style.WARNING(
                            f"Skipping item #{index}: missing category for question '{question or 'unknown'}'."
                        )
                    )
                    continue

                if category not in CATEGORY_LABELS:
                    skipped += 1
                    self.stderr.write(
                        self.style.WARNING(
                            f"Skipping item #{index}: unsupported category '{category}'."
                        )
                    )
                    continue

                if not question or not answer:
                    skipped += 1
                    self.stderr.write(
                        self.style.WARNING(
                            f"Skipping item #{index}: missing question or answer for category '{category}'."
                        )
                    )
                    continue

                topic_title = CATEGORY_LABELS[category]
                topic_slug = slugify(topic_title) or f"pregnancy-{category}"
                topic_defaults = {
                    "title": topic_title,
                    "category": category,
                    "description": f"General information about {topic_title.lower()}.",
                    "content": (
                        "Reviewed pregnancy information designed to support "
                        "general education and safe, patient-centered discussion."
                    ),
                    "icon": CATEGORY_ICONS[category],
                    "position": list(CATEGORY_LABELS).index(category) + 1,
                    "is_published": True,
                    "source_name": source_name,
                    "source_url": source_url,
                }
                topic, topic_created = PregnancyTopic.objects.get_or_create(
                    slug=topic_slug,
                    defaults=topic_defaults,
                )
                if not topic_created:
                    for field_name, value in topic_defaults.items():
                        current_value = getattr(topic, field_name)
                        if not current_value and (
                            field_name in {"title", "description", "content"}
                            or (value and field_name in {"source_name", "source_url"})
                        ):
                            setattr(topic, field_name, value)
                    topic.save(
                        update_fields=[
                            field for field in topic_defaults if hasattr(topic, field)
                        ]
                    )
                    updated_topics += 1
                else:
                    created_topics += 1

                faq_defaults = {
                    "question": question,
                    "topic": topic,
                    "answer": answer,
                    "is_published": is_published,
                    "source_name": source_name,
                    "source_url": source_url,
                    "position": index,
                }
                faq, faq_created = FAQ.objects.get_or_create(
                    question__iexact=question,
                    defaults=faq_defaults,
                )
                if faq_created:
                    faq.topic = topic
                    faq.answer = answer
                    faq.is_published = is_published
                    faq.source_name = source_name
                    faq.source_url = source_url
                    faq.position = index
                    faq.save()
                    created_faqs += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Import complete: "
                f"{created_topics} topics created, {updated_topics} topics refreshed, "
                f"{created_faqs} FAQs created, {updated_faqs} FAQs updated, "
                f"{skipped} entries skipped."
            )
        )
