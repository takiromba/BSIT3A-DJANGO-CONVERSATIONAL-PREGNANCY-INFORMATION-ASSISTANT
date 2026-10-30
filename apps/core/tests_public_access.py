from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    FAQ,
    ChatConversation,
    ChatMessage,
    PregnancyProfile,
    PregnancyTopic,
)
from .services.pregnabot import Answer


class PublicPregnancyGuideTests(TestCase):
    def test_root_opens_chatbot_without_login(self):
        response = self.client.get(reverse("public_home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pregnancy/chatbot.html")
        self.assertContains(response, "Chat with PregnaBot")

    def test_login_remains_available_and_authenticated_root_keeps_dashboard_flow(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

        user = get_user_model().objects.create_user(username="registered-user")
        PregnancyProfile.objects.create(
            user=user,
            estimated_conception_date=timezone.localdate() - timedelta(days=70),
        )
        self.client.force_login(user)
        response = self.client.get(reverse("public_home"))

        self.assertRedirects(
            response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

    def test_public_chat_retains_session_context_without_saving_history(self):
        histories = []

        def answer_question(question, history, request):
            histories.append(history)
            return [
                Answer(
                    title=question,
                    content=f"Answer to {question}",
                    source_name="Pregnancy library",
                )
            ]

        with patch(
            "apps.core.chatbot._assistant_answers",
            side_effect=answer_question,
        ):
            first_response = self.client.post(
                reverse("chatbot"),
                {"question": "What are some hydration tips?"},
            )
            self.assertEqual(first_response.status_code, 302)
            self.client.post(
                reverse("chatbot"),
                {"question": "What about that?"},
            )

        self.assertEqual(len(histories), 2)
        self.assertEqual(histories[1][-1]["role"], ChatMessage.Role.ASSISTANT)
        self.assertEqual(
            histories[1][-1]["content"],
            "Answer to What are some hydration tips?",
        )
        self.assertFalse(ChatConversation.objects.exists())
        self.assertFalse(ChatMessage.objects.exists())

        response = self.client.get(reverse("chatbot"))
        self.assertContains(response, "What are some hydration tips?")
        self.assertContains(response, "Answer to What about that?")
        self.assertContains(response, "Pregnancy library")

    def test_public_new_chat_clears_temporary_context(self):
        captured_histories = []

        def answer_question(question, history, request):
            captured_histories.append(history)
            return [
                Answer(
                    title=question,
                    content=f"Answer to {question}",
                    source_name="Pregnancy library",
                )
            ]

        with patch(
            "apps.core.chatbot._assistant_answers",
            side_effect=answer_question,
        ):
            self.client.post(
                reverse("chatbot"),
                {"question": "A temporary guest question"},
            )
            response = self.client.get(reverse("chatbot"))
            self.assertContains(
                response,
                f'href="{reverse("chat_new")}"',
            )

            response = self.client.get(reverse("chat_new"), follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "A temporary guest question")
            self.assertNotIn("public_chat_messages", self.client.session)

            self.client.post(
                reverse("chatbot"),
                {"question": "A fresh guest question"},
            )

        self.assertEqual(captured_histories[0], [])
        self.assertEqual(captured_histories[1], [])
        self.assertFalse(ChatConversation.objects.exists())
        self.assertFalse(ChatMessage.objects.exists())

    def test_published_information_and_faq_are_public(self):
        topic = PregnancyTopic.objects.create(
            title="Public nutrition guide",
            slug="public-nutrition-guide",
            category=PregnancyTopic.Category.NUTRITION,
            description="Published nutrition advice.",
            content="Browse this public information.",
        )
        faq = FAQ.objects.create(
            question="A public pregnancy question?",
            answer="A published answer.",
        )

        for url in (
            reverse("pregnancy_information"),
            reverse("topic_detail", args=[topic.slug]),
            reverse("faq_list"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        self.assertContains(
            self.client.get(reverse("pregnancy_information")),
            topic.title,
        )
        self.assertContains(self.client.get(reverse("faq_list")), faq.question)

    def test_anonymous_visitors_cannot_access_private_pages_or_saved_chat(self):
        user = get_user_model().objects.create_user(username="private-user")
        conversation = ChatConversation.objects.create(user=user, title="Private chat")
        private_urls = (
            reverse("dashboard"),
            reverse("profile"),
            reverse("pregnancy_profile"),
            reverse("bookmarks"),
            reverse("info:info_list"),
            reverse("users:user_list"),
            reverse("chat_conversation", args=[conversation.pk]),
        )

        for url in private_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)

        self.assertEqual(ChatConversation.objects.count(), 1)
