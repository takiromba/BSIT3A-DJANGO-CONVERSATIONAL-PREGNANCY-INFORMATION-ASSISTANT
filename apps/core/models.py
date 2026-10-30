from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PregnancyTopic(models.Model):
    class Category(models.TextChoices):
        SYMPTOMS = "symptoms", _("Common Pregnancy Symptoms")
        NUTRITION = "nutrition", _("Nutrition and Healthy Practices")
        PRENATAL = "prenatal", _("Prenatal Care")
        DEVELOPMENT = "development", _("Pregnancy Stages and Fetal Development")
        CONCERNS = "concerns", _("Common Pregnancy Concerns")
        WARNING_SIGNS = "warning-signs", _(
            "Warning Signs and When to Seek Medical Care"
        )

    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    category = models.CharField(max_length=32, choices=Category.choices)
    description = models.CharField(max_length=280)
    content = models.TextField()
    icon = models.CharField(max_length=48, default="fa-heart")
    position = models.PositiveSmallIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    source_name = models.CharField(max_length=120, blank=True)
    source_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "title"]

    @classmethod
    def category_metadata(cls):
        styles = {
            cls.Category.SYMPTOMS: ("fa-person-circle-question", "rose"),
            cls.Category.NUTRITION: ("fa-apple-whole", "mint"),
            cls.Category.PRENATAL: ("fa-kit-medical", "blue"),
            cls.Category.DEVELOPMENT: ("fa-baby", "lavender"),
            cls.Category.CONCERNS: ("fa-heart", "peach"),
            cls.Category.WARNING_SIGNS: ("fa-triangle-exclamation", "rose"),
        }
        return [
            {
                "value": value,
                "title": title,
                "icon": styles[value][0],
                "color": styles[value][1],
            }
            for value, title in cls.Category.choices
        ]

    def __str__(self):
        return self.title


class FAQ(models.Model):
    question = models.CharField(max_length=280)
    answer = models.TextField()
    topic = models.ForeignKey(
        PregnancyTopic,
        related_name="faqs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    position = models.PositiveSmallIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    source_name = models.CharField(max_length=120, blank=True)
    source_url = models.URLField(blank=True)

    class Meta:
        ordering = ["position", "question"]
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"

    def __str__(self):
        return self.question


class ChatConversation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="pregnabot_conversations",
        on_delete=models.CASCADE,
    )
    title = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-pk"]

    def __str__(self):
        return f"{self.user}: {self.title}"


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "You"
        ASSISTANT = "assistant", "PregnaBot"

    conversation = models.ForeignKey(
        ChatConversation,
        related_name="messages",
        on_delete=models.CASCADE,
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    answer_title = models.CharField(max_length=280, blank=True)
    content = models.TextField()
    source_name = models.CharField(max_length=120, blank=True)
    source_url = models.URLField(blank=True)
    helpful = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.get_role_display()}: {self.content[:60]}"


class PregnancyProfile(models.Model):
    BLOOD_TYPE_CHOICES = [
        ("A+", "A+"),
        ("A-", "A-"),
        ("B+", "B+"),
        ("B-", "B-"),
        ("AB+", "AB+"),
        ("AB-", "AB-"),
        ("O+", "O+"),
        ("O-", "O-"),
        ("unknown", "Prefer not to say / Unknown"),
    ]

    class PregnancyStatus(models.TextChoices):
        PREGNANT = "pregnant", _("Currently Pregnant")
        PLANNING = "planning", _("Planning Pregnancy")
        OTHER = "other", _("Other")

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="pregnancy_profile",
        on_delete=models.CASCADE,
    )
    date_of_birth = models.DateField(null=True, blank=True)
    pregnancy_status = models.CharField(
        max_length=16,
        choices=PregnancyStatus.choices,
        blank=True,
    )
    estimated_conception_date = models.DateField(null=True, blank=True)
    blood_type = models.CharField(max_length=7, choices=BLOOD_TYPE_CHOICES, blank=True)
    phone_number = models.CharField(max_length=32, blank=True)
    healthcare_provider = models.CharField(max_length=150, blank=True)
    city = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_relationship = models.CharField(max_length=80, blank=True)
    emergency_contact_number = models.CharField(max_length=32, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def estimated_due_date(self):
        if not self.estimated_conception_date:
            return None
        return self.estimated_conception_date + timedelta(days=266)

    def gestational_age_days(self, on_date=None):
        if not self.estimated_conception_date:
            return None
        today = on_date or timezone.localdate()
        return max(0, (today - self.estimated_conception_date).days + 14)

    def gestational_week(self, on_date=None):
        days = self.gestational_age_days(on_date)
        return days // 7 if days is not None else None

    def trimester(self, on_date=None):
        week = self.gestational_week(on_date)
        if week is None:
            return None
        if week < 14:
            return 1
        if week < 28:
            return 2
        return 3

    def __str__(self):
        return f"Pregnancy profile for {self.user}"


class PrenatalAppointment(models.Model):
    profile = models.ForeignKey(
        PregnancyProfile,
        related_name="appointments",
        on_delete=models.CASCADE,
    )
    title = models.CharField(max_length=120)
    scheduled_at = models.DateTimeField()
    notes = models.TextField(blank=True)
    reminder_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_at", "pk"]

    def __str__(self):
        return f"{self.title} — {self.scheduled_at:%Y-%m-%d %H:%M}"


class TopicBookmark(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="pregnancy_topic_bookmarks",
        on_delete=models.CASCADE,
    )
    topic = models.ForeignKey(
        PregnancyTopic,
        related_name="bookmarks",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "topic"],
                name="unique_user_topic_bookmark",
            )
        ]

    def __str__(self):
        return f"{self.user}: {self.topic}"
