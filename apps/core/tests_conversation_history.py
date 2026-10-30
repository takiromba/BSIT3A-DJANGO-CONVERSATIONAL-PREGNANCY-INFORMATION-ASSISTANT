from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ChatConversation, ChatMessage, PregnancyProfile


class ConversationHistoryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="history-reader",
            password="test-password",
        )
        PregnancyProfile.objects.create(
            user=self.user,
            pregnancy_status=PregnancyProfile.PregnancyStatus.PLANNING,
        )
        self.client.force_login(self.user)
        self.url = reverse("conversation_history")

    def create_conversation(self, title, *, user=None, updated_at=None, message=None):
        conversation = ChatConversation.objects.create(
            user=user or self.user,
            title=title,
        )
        if updated_at:
            ChatConversation.objects.filter(pk=conversation.pk).update(
                updated_at=updated_at
            )
        if message:
            ChatMessage.objects.create(
                conversation=conversation,
                role=ChatMessage.Role.USER,
                content=message,
            )
        return conversation

    def test_history_shows_only_current_users_saved_conversations_and_real_preview(self):
        own = self.create_conversation(
            "My prenatal question",
            message="How can I manage morning sickness?",
        )
        self.create_conversation(
            "Another user's private chat",
            user=get_user_model().objects.create_user(username="other-reader"),
            message="Private conversation content",
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, own.title)
        self.assertContains(response, "How can I manage morning sickness?")
        self.assertNotContains(response, "Another user's private chat")
        self.assertContains(response, reverse("chat_conversation", args=[own.pk]))
        self.assertContains(response, "Guest chats are temporary")

    def test_search_matches_conversation_titles_and_saved_messages(self):
        title_match = self.create_conversation("Nutrition discussion")
        message_match = self.create_conversation(
            "A different title",
            message="I have a question about prenatal vitamins.",
        )
        self.create_conversation("Unrelated question", message="Weather today")

        response = self.client.get(self.url, {"q": "prenatal vitamins"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, message_match.title)
        self.assertNotContains(response, title_match.title)
        self.assertNotContains(response, "Unrelated question")

    def test_date_filters_use_conversation_update_dates(self):
        recent = self.create_conversation("Recent conversation")
        old = self.create_conversation(
            "Older conversation",
            updated_at=timezone.now() - timedelta(days=10),
        )

        today_response = self.client.get(self.url, {"range": "today"})
        seven_day_response = self.client.get(self.url, {"range": "7"})
        thirty_day_response = self.client.get(self.url, {"range": "30"})

        self.assertContains(today_response, recent.title)
        self.assertNotContains(today_response, old.title)
        self.assertContains(seven_day_response, recent.title)
        self.assertNotContains(seven_day_response, old.title)
        self.assertContains(thirty_day_response, old.title)
        self.assertEqual(today_response.context["selected_filter"], "today")

    def test_pagination_preserves_search_and_date_filter(self):
        for index in range(9):
            self.create_conversation(f"Prenatal topic {index}")

        response = self.client.get(self.url, {"q": "prenatal", "range": "30", "page": 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertContains(response, "page=1&amp;q=prenatal&amp;range=30")

    def test_anonymous_users_are_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={self.url}",
            fetch_redirect_response=False,
        )
