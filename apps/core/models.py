from django.db import models

from django.conf import settings


class PregnancyTopic(models.Model):
    class Category(models.TextChoices):
        SYMPTOMS = 'symptoms', 'Common Symptoms'
        NUTRITION = 'nutrition', 'Nutrition & Healthy Practices'
        PRENATAL = 'prenatal', 'Prenatal Care'
        DEVELOPMENT = 'development', 'Stages & Fetal Development'
        CONCERNS = 'concerns', 'Common Concerns'
        WARNING_SIGNS = 'warning-signs', 'Warning Signs'

    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    category = models.CharField(max_length=32, choices=Category.choices)
    description = models.CharField(max_length=280)
    content = models.TextField()
    icon = models.CharField(max_length=48, default='fa-heart')
    position = models.PositiveSmallIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'title']

    def __str__(self):
        return self.title


class FAQ(models.Model):
    question = models.CharField(max_length=280)
    answer = models.TextField()
    topic = models.ForeignKey(
        PregnancyTopic,
        related_name='faqs',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    position = models.PositiveSmallIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ['position', 'question']
        verbose_name = 'FAQ'
        verbose_name_plural = 'FAQs'

    def __str__(self):
        return self.question


class ChatConversation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='pregnabot_conversations',
        on_delete=models.CASCADE,
    )
    title = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-pk']

    def __str__(self):
        return f'{self.user}: {self.title}'


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = 'user', 'You'
        ASSISTANT = 'assistant', 'PregnaBot'

    conversation = models.ForeignKey(
        ChatConversation,
        related_name='messages',
        on_delete=models.CASCADE,
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']

    def __str__(self):
        return f'{self.get_role_display()}: {self.content[:60]}'
