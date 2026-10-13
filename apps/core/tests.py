from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    FAQ,
    ChatConversation,
    ChatMessage,
    PregnancyProfile,
    PregnancyTopic,
    PrenatalAppointment,
    TopicBookmark,
)
from .services.pregnabot import search_answers


class HomeViewTests(TestCase):
    def test_home_renders_for_authenticated_user(self):
        user = get_user_model().objects.create_user(
            username="admin", password="secret1234"
        )

        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pregnancy/dashboard.html")
        self.assertContains(response, "Good morning")

    def test_home_requires_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 302)

    def test_logout_requires_post(self):
        user = get_user_model().objects.create_user(
            username="admin", password="secret1234"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("logout"))

        self.assertEqual(response.status_code, 405)

    def test_logout_post_ends_the_session(self):
        user = get_user_model().objects.create_user(
            username="admin", password="secret1234"
        )
        self.client.force_login(user)

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_dashboard_uses_only_the_current_users_chat_statistics(self):
        user = get_user_model().objects.create_user(
            username="pregnant-user",
            password="secret1234",
        )
        other = get_user_model().objects.create_user(
            username="another-user",
            password="secret1234",
        )
        for owner in (user, other):
            conversation = ChatConversation.objects.create(
                user=owner,
                title="A question",
            )
            ChatMessage.objects.create(
                conversation=conversation,
                role=ChatMessage.Role.USER,
                content="How can I stay hydrated?",
            )

        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "<strong>1</strong>", html=False)
        self.assertEqual(response.context["question_count"], 1)
        self.assertEqual(len(response.context["recent_conversations"]), 1)


class PregnancyInformationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="reader",
            password="secret1234",
        )
        self.client.force_login(self.user)

    def test_information_search_filters_published_topics(self):
        topic = PregnancyTopic.objects.create(
            title="Nutrition basics",
            slug="nutrition-basics-test",
            category=PregnancyTopic.Category.NUTRITION,
            description="Simple food guidance.",
            content="Choose a balanced diet.",
        )
        PregnancyTopic.objects.create(
            title="Prenatal visits",
            slug="prenatal-visits-test",
            category=PregnancyTopic.Category.PRENATAL,
            description="Prepare for appointments.",
            content="Talk with your provider.",
        )
        PregnancyTopic.objects.create(
            title="Hidden topic",
            slug="hidden-topic-test",
            category=PregnancyTopic.Category.NUTRITION,
            description="Not published.",
            content="Hidden content.",
            is_published=False,
        )

        response = self.client.get(reverse("pregnancy_information"), {"q": "balanced"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, topic.title)
        self.assertNotContains(response, "Prenatal visits")
        self.assertNotContains(response, "Hidden topic")

    def test_topic_categories_are_filterable(self):
        topic = PregnancyTopic.objects.create(
            title="Care test",
            slug="care-test",
            category=PregnancyTopic.Category.PRENATAL,
            description="Checkups and care.",
            content="Ask questions.",
        )

        response = self.client.get(
            reverse("pregnancy_information"),
            {"category": PregnancyTopic.Category.PRENATAL},
        )

        self.assertContains(response, topic.title)
        self.assertEqual(response.context["topic_count"], 2)

    def test_topic_detail_renders_published_content(self):
        topic = PregnancyTopic.objects.create(
            title="A helpful topic",
            slug="helpful-topic-test",
            category=PregnancyTopic.Category.CONCERNS,
            description="A short introduction.",
            content="Discuss personal questions with your care team.",
        )

        response = self.client.get(reverse("topic_detail", args=[topic.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, topic.content)

    def test_faq_search_returns_matching_published_answers(self):
        faq = FAQ.objects.create(
            question="How should I prepare for visits?",
            answer="Write down questions for your provider.",
        )
        response = self.client.get(reverse("faq_list"), {"q": "provider"})

        self.assertContains(response, faq.question)


class ChatbotTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="chat-user",
            password="secret1234",
        )
        self.client.force_login(self.user)

    def test_question_creates_private_conversation_and_library_answer(self):
        response = self.client.post(
            reverse("chatbot"),
            {"question": "What vitamins and supplements should I take?"},
        )

        conversation = ChatConversation.objects.get(user=self.user)
        messages = list(conversation.messages.all())
        self.assertRedirects(
            response,
            reverse("chat_conversation", args=[conversation.pk]),
        )
        self.assertGreaterEqual(len(messages), 2)
        self.assertLessEqual(len(messages), 4)
        self.assertEqual(messages[0].role, ChatMessage.Role.USER)
        self.assertTrue(
            all(message.role == ChatMessage.Role.ASSISTANT for message in messages[1:])
        )
        self.assertTrue(
            any("Supplement needs vary" in message.content for message in messages[1:])
        )

    def test_urgent_symptom_gets_immediate_care_message(self):
        response = self.client.post(
            reverse("chatbot"),
            {"question": "I have heavy bleeding and feel faint"},
        )

        conversation = ChatConversation.objects.get(user=self.user)
        reply = conversation.messages.get(role=ChatMessage.Role.ASSISTANT)
        self.assertRedirects(
            response,
            reverse("chat_conversation", args=[conversation.pk]),
        )
        self.assertIn("urgent assessment", reply.content)
        self.assertIn("Do not wait", reply.content)

    def test_user_cannot_open_another_users_conversation(self):
        other = get_user_model().objects.create_user(
            username="other-chat-user",
            password="secret1234",
        )
        conversation = ChatConversation.objects.create(
            user=other,
            title="Private conversation",
        )

        response = self.client.get(
            reverse("chat_conversation", args=[conversation.pk]),
        )

        self.assertEqual(response.status_code, 404)

    def test_conversation_can_be_renamed_exported_and_deleted_by_its_owner(self):
        conversation = ChatConversation.objects.create(
            user=self.user, title="First title"
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.USER,
            content="Question",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.ASSISTANT,
            answer_title="Answer title",
            content="Answer body",
        )

        response = self.client.post(
            reverse("chat_rename", args=[conversation.pk]),
            {"title": "New title"},
        )
        self.assertRedirects(
            response,
            reverse("chat_conversation", args=[conversation.pk]),
            fetch_redirect_response=False,
        )
        conversation.refresh_from_db()
        self.assertEqual(conversation.title, "New title")

        exported = self.client.get(reverse("chat_export", args=[conversation.pk]))
        self.assertEqual(exported["Content-Type"], "text/plain; charset=utf-8")
        self.assertContains(exported, "Answer title")
        self.assertContains(exported, "Answer body")

        self.client.post(reverse("chat_delete", args=[conversation.pk]))
        self.assertFalse(ChatConversation.objects.filter(pk=conversation.pk).exists())

    def test_chat_actions_cannot_access_another_users_conversation(self):
        other = get_user_model().objects.create_user(username="private-owner")
        conversation = ChatConversation.objects.create(user=other, title="Private")
        response = self.client.post(reverse("chat_delete", args=[conversation.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ChatConversation.objects.filter(pk=conversation.pk).exists())

    def test_feedback_is_saved_only_for_owned_assistant_message(self):
        conversation = ChatConversation.objects.create(user=self.user, title="Feedback")
        answer = ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.ASSISTANT,
            content="Answer",
        )
        response = self.client.post(
            reverse("chat_feedback", args=[answer.pk]),
            {"helpful": "true"},
        )
        self.assertRedirects(
            response,
            reverse("chat_conversation", args=[conversation.pk]),
            fetch_redirect_response=False,
        )
        answer.refresh_from_db()
        self.assertIs(answer.helpful, True)

    def test_feedback_cannot_be_submitted_for_a_foreign_message(self):
        other = get_user_model().objects.create_user(username="feedback-owner")
        conversation = ChatConversation.objects.create(user=other, title="Private")
        answer = ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.ASSISTANT,
            content="Answer",
        )
        response = self.client.post(
            reverse("chat_feedback", args=[answer.pk]),
            {"helpful": "false"},
        )
        self.assertEqual(response.status_code, 404)

    def test_search_answers_rank_matches_and_limit_results(self):
        first = FAQ.objects.create(
            question="How does folate supplementation work?",
            answer="Discuss folate supplementation with your care provider.",
            position=0,
        )
        FAQ.objects.create(
            question="What should I eat during pregnancy?",
            answer="A balanced diet supports nutrition.",
        )
        answers = search_answers("folate supplement")
        self.assertLessEqual(len(answers), 3)
        self.assertEqual(answers[0].title, first.question)


class PregnancyToolkitTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="prenatal-user",
            password="secret1234",
        )
        self.client.force_login(self.user)

    def test_pregnancy_dates_are_estimated_from_conception_date(self):
        profile = PregnancyProfile.objects.create(
            user=self.user,
            estimated_conception_date=date(2026, 1, 1),
        )
        self.assertEqual(profile.estimated_due_date(), date(2026, 9, 24))
        self.assertEqual(profile.gestational_week(date(2026, 4, 10)), 16)
        self.assertEqual(profile.trimester(date(2026, 4, 10)), 2)

    def test_user_can_save_profile_and_an_upcoming_appointment(self):
        scheduled = timezone.localtime(timezone.now() + timedelta(days=7))
        response = self.client.post(
            reverse("pregnancy_profile"),
            {
                "save_profile": "1",
                "estimated_conception_date": "2026-01-01",
                "blood_type": "A+",
            },
        )
        self.assertRedirects(
            response,
            reverse("pregnancy_profile"),
            fetch_redirect_response=False,
        )
        profile = PregnancyProfile.objects.get(user=self.user)
        self.assertEqual(profile.blood_type, "A+")

        response = self.client.post(
            reverse("pregnancy_profile"),
            {
                "add_appointment": "1",
                "title": "Prenatal visit",
                "scheduled_at": scheduled.strftime("%Y-%m-%dT%H:%M"),
                "notes": "Bring questions",
                "reminder_enabled": "on",
            },
        )
        self.assertRedirects(
            response,
            reverse("pregnancy_profile"),
            fetch_redirect_response=False,
        )
        self.assertEqual(profile.appointments.count(), 1)

    def test_bookmarks_are_private_and_can_be_toggled(self):
        topic = PregnancyTopic.objects.create(
            title="Saved topic",
            slug="saved-topic",
            category=PregnancyTopic.Category.PRENATAL,
            description="Care topic",
            content="Read more.",
        )
        self.client.post(reverse("bookmark_toggle", args=[topic.pk]))
        self.assertTrue(
            TopicBookmark.objects.filter(user=self.user, topic=topic).exists()
        )
        response = self.client.get(reverse("bookmarks"))
        self.assertContains(response, topic.title)
        self.client.post(reverse("bookmark_toggle", args=[topic.pk]))
        self.assertFalse(
            TopicBookmark.objects.filter(user=self.user, topic=topic).exists()
        )

    def test_pregnancy_profile_and_bookmark_pages_render(self):
        response = self.client.get(reverse("pregnancy_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pregnancy/prenatal_profile.html")

        response = self.client.get(reverse("bookmarks"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pregnancy/bookmarks.html")

    def test_pregnancy_profile_rejects_future_conception_dates(self):
        response = self.client.post(
            reverse("pregnancy_profile"),
            {
                "save_profile": "1",
                "estimated_conception_date": "2099-01-01",
                "blood_type": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be in the future")

    def test_appointment_delete_is_scoped_to_current_user(self):
        other = get_user_model().objects.create_user(username="other-prenatal-user")
        other_profile = PregnancyProfile.objects.create(user=other)
        appointment = PrenatalAppointment.objects.create(
            profile=other_profile,
            title="Private visit",
            scheduled_at=timezone.now() + timedelta(days=1),
        )
        response = self.client.post(
            reverse("appointment_delete", args=[appointment.pk]),
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(PrenatalAppointment.objects.filter(pk=appointment.pk).exists())


class RegistrationTests(TestCase):
    def test_registration_creates_user_with_validated_password_and_profile(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "new-pregnancy-user",
                "first_name": "Taylor",
                "last_name": "Jones",
                "email": "taylor@example.com",
                "password1": "Sufficiently-Strong-Password-39!",
                "password2": "Sufficiently-Strong-Password-39!",
            },
        )
        user = get_user_model().objects.get(username="new-pregnancy-user")
        self.assertRedirects(
            response, reverse("dashboard"), fetch_redirect_response=False
        )
        self.assertTrue(user.check_password("Sufficiently-Strong-Password-39!"))
        self.assertEqual(user.first_name, "Taylor")

    def test_registration_rejects_mismatched_passwords(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "mismatch-user",
                "first_name": "Taylor",
                "last_name": "Jones",
                "email": "mismatch@example.com",
                "password1": "Sufficiently-Strong-Password-39!",
                "password2": "A-different-password-12!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            get_user_model().objects.filter(username="mismatch-user").exists()
        )


class ProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="profile-user",
            password="secret1234",
            email="before@example.com",
        )
        self.client.force_login(self.user)

    def test_profile_updates_current_user_and_uses_success_message(self):
        response = self.client.post(
            reverse("profile"),
            {
                "first_name": "Taylor",
                "last_name": "Jones",
                "email": "taylor@example.com",
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertRedirects(response, reverse("profile"))
        self.assertEqual(self.user.first_name, "Taylor")
        self.assertEqual(self.user.last_name, "Jones")
        self.assertEqual(self.user.email, "taylor@example.com")
        self.assertContains(response, "Your profile has been updated.")

    def test_profile_rejects_an_invalid_email(self):
        response = self.client.post(
            reverse("profile"),
            {
                "first_name": "Taylor",
                "last_name": "Jones",
                "email": "not-an-email",
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user.email, "before@example.com")
        self.assertContains(response, "Please enter a valid email address.")


class LoginLockoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="lockout-user",
            password="correct-password-123",
        )

    def tearDown(self):
        cache.clear()

    def _login(self, username="lockout-user", password="wrong-password"):
        return self.client.post(
            reverse("login"),
            {"username": username, "password": password},
        )

    def test_lockout_persists_across_new_sessions(self):
        for _ in range(4):
            response = self._login()
            self.assertNotContains(response, "Locked for 1 minute.")

        response = self._login()
        self.assertContains(response, "Locked for 1 minute.")

        self.client.cookies.clear()
        response = self._login()
        self.assertContains(response, "Too many failed attempts.")

    def test_successful_login_resets_failed_attempt_counter(self):
        for _ in range(4):
            self._login()

        response = self._login(password="correct-password-123")
        self.assertRedirects(
            response, reverse("dashboard"), fetch_redirect_response=False
        )

        self.client.post(reverse("logout"))
        for _ in range(4):
            response = self._login()
            self.assertNotContains(response, "Locked for 1 minute.")
        self.assertContains(self._login(), "Locked for 1 minute.")
