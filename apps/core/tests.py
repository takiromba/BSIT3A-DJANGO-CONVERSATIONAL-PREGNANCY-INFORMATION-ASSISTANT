from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils.formats import date_format
from django.utils import timezone

from .forms import PregnancyProfileForm
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
        PregnancyProfile.objects.create(
            user=user,
            estimated_conception_date=timezone.localdate() - timedelta(days=70),
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
        PregnancyProfile.objects.create(
            user=user,
            estimated_conception_date=timezone.localdate() - timedelta(days=70),
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


class PregnancyDatasetImportTests(TestCase):
    def test_import_command_creates_dataset_without_duplicates(self):
        call_command("import_pregnancy_data", verbosity=0)
        first_count = FAQ.objects.filter(is_published=True).count()
        call_command("import_pregnancy_data", verbosity=0)
        second_count = FAQ.objects.filter(is_published=True).count()

        self.assertGreaterEqual(first_count, 30)
        self.assertEqual(first_count, second_count)

    def test_question_matching_handles_alternative_phrases_and_warning_signs(self):
        call_command("import_pregnancy_data", verbosity=0)

        alternative_answer = search_answers("Normal lang bala nga pirmi ko ginasuka?")
        self.assertTrue(alternative_answer)
        self.assertIn("nausea", alternative_answer[0].content.lower())

        urgent_answer = search_answers(
            "I have heavy bleeding and severe abdominal pain"
        )
        self.assertTrue(urgent_answer)
        self.assertIn("urgent assessment", urgent_answer[0].content.lower())


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
                "first_name": "Prenatal",
                "last_name": "User",
                "email": "prenatal@example.com",
                "date_of_birth": "1995-04-12",
                "pregnancy_status": PregnancyProfile.PregnancyStatus.PREGNANT,
                "estimated_conception_date": "2026-01-01",
                "blood_type": "A+",
                "privacy_acknowledgement": "on",
            },
        )
        self.assertRedirects(
            response,
            reverse("dashboard"),
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
            reverse("profile"),
            fetch_redirect_response=False,
        )
        self.assertEqual(profile.appointments.count(), 1)

    def test_bookmarks_are_private_and_can_be_toggled(self):
        PregnancyProfile.objects.create(
            user=self.user,
            estimated_conception_date=timezone.localdate() - timedelta(days=70),
        )
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
        PregnancyProfile.objects.create(
            user=self.user,
            estimated_conception_date=timezone.localdate() - timedelta(days=70),
        )
        response = self.client.get(reverse("pregnancy_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pregnancy/prenatal_profile.html")

        response = self.client.get(reverse("bookmarks"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pregnancy/bookmarks.html")

    def test_navigation_keeps_core_links_without_a_separate_record_item(self):
        PregnancyProfile.objects.create(
            user=self.user,
            estimated_conception_date=timezone.localdate() - timedelta(days=70),
        )
        response = self.client.get(reverse("dashboard"))
        content = response.content.decode()

        for url in (
            reverse("dashboard"),
            reverse("chatbot"),
            reverse("pregnancy_information"),
            reverse("faq_list"),
            reverse("profile"),
            reverse("logout"),
        ):
            with self.subTest(url=url):
                self.assertIn(url, content)

        self.assertNotIn(reverse("pregnancy_profile"), content)
        self.assertNotIn("My Pregnancy Record", content)

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
            response, reverse("pregnancy_profile"), fetch_redirect_response=False
        )
        self.assertTrue(user.check_password("Sufficiently-Strong-Password-39!"))
        self.assertEqual(user.first_name, "Taylor")

    def test_new_registered_user_sees_the_profile_completion_form(self):
        self.client.post(
            reverse("register"),
            {
                "username": "fresh-pregnancy-user",
                "first_name": "New",
                "last_name": "User",
                "email": "fresh@example.com",
                "password1": "Sufficiently-Strong-Password-39!",
                "password2": "Sufficiently-Strong-Password-39!",
            },
        )

        response = self.client.get(reverse("profile"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pregnancy/prenatal_profile.html")
        self.assertContains(response, "Complete Your Profile")
        self.assertEqual(
            PregnancyProfile.objects.filter(
                user__username="fresh-pregnancy-user"
            ).count(),
            1,
        )

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
        PregnancyProfile.objects.create(
            user=self.user,
            date_of_birth=date(1995, 4, 12),
            pregnancy_status=PregnancyProfile.PregnancyStatus.PREGNANT,
            estimated_conception_date=timezone.localdate() - timedelta(days=70),
        )
        self.client.force_login(self.user)

    def _payload(self, **overrides):
        payload = {
            "save_profile": "1",
            "first_name": "Taylor",
            "last_name": "Jones",
            "email": "taylor@example.com",
            "date_of_birth": "1995-04-12",
            "pregnancy_status": PregnancyProfile.PregnancyStatus.PREGNANT,
            "estimated_conception_date": (
                timezone.localdate() - timedelta(days=70)
            ).isoformat(),
            "blood_type": "",
        }
        payload.update(overrides)
        return payload

    def test_profile_updates_current_user_and_uses_success_message(self):
        response = self.client.post(
            reverse("profile"),
            self._payload(),
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
            self._payload(email="not-an-email"),
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
        PregnancyProfile.objects.create(
            user=self.user,
            estimated_conception_date=timezone.localdate() - timedelta(days=70),
        )
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


class OnboardingFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="onboarding-user",
            password="secret1234",
        )
        self.client.force_login(self.user)

    def _complete_record(self):
        return PregnancyProfile.objects.create(
            user=self.user,
            estimated_conception_date=timezone.localdate() - timedelta(days=70),
        )

    def _onboarding_payload(self, **overrides):
        payload = {
            "save_profile": "1",
            "first_name": "Taylor",
            "last_name": "Jones",
            "email": "onboarding-user@example.com",
            "date_of_birth": "1995-04-12",
            "pregnancy_status": PregnancyProfile.PregnancyStatus.PREGNANT,
            "estimated_conception_date": (
                timezone.localdate() - timedelta(days=70)
            ).isoformat(),
            "blood_type": "",
        }
        payload.update(overrides)
        return payload

    def test_incomplete_record_redirects_protected_pages_to_onboarding(self):
        for url in (
            reverse("dashboard"),
            reverse("bookmarks"),
            reverse("info:info_list"),
        ):
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url),
                    reverse("pregnancy_profile"),
                    fetch_redirect_response=False,
                )

    def test_incomplete_record_keeps_account_public_and_onboarding_pages_open(self):
        for url in (
            reverse("pregnancy_profile"),
            reverse("profile"),
            reverse("chatbot"),
            reverse("pregnancy_information"),
            reverse("faq_list"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_incomplete_record_is_routed_away_from_the_public_home(self):
        self.assertRedirects(
            self.client.get(reverse("public_home")),
            reverse("pregnancy_profile"),
            fetch_redirect_response=False,
        )

    def test_completed_record_opens_the_dashboard(self):
        self._complete_record()
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pregnancy/dashboard.html")

    def test_legacy_record_with_conception_date_skips_onboarding(self):
        self._complete_record()
        response = self.client.get(reverse("public_home"))

        self.assertRedirects(
            response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

    def test_onboarding_form_renders_a_single_submittable_form(self):
        response = self.client.get(reverse("pregnancy_profile"))
        content = response.content.decode()

        self.assertEqual(content.count('id="pregnancy-record-form"'), 1)
        self.assertEqual(content.count('name="save_profile"'), 1)
        self.assertNotContains(response, "Additional Information")
        self.assertNotContains(response, "Privacy & Consent")
        self.assertNotContains(response, 'id="profile-overview"')

    def test_onboarding_policy_checkbox_is_visible_and_unchecked_by_default(self):
        response = self.client.get(reverse("pregnancy_profile"))
        content = response.content.decode()

        self.assertContains(response, "Privacy & Data Policy")
        self.assertContains(response, "not registered in Django admin")
        self.assertContains(response, "authorized staff administrators")
        self.assertContains(response, "associated messages")
        self.assertContains(
            response,
            "I have read and understood the Privacy &amp; Data Policy, and I agree "
            "to the collection and use of my information as explained above.",
        )
        self.assertContains(response, "When OpenAI is selected")
        self.assertContains(response, "configured Ollama endpoint")
        self.assertContains(response, "does not silently switch providers")
        checkbox = next(
            line
            for line in content.splitlines()
            if 'name="privacy_acknowledgement"' in line
        ).split(">", 1)[0]
        self.assertIn('type="checkbox"', checkbox)
        self.assertNotIn("checked", checkbox)
        self.assertLess(
            content.index("Privacy &amp; Data Policy"),
            content.index("Save Changes"),
        )

    def test_onboarding_does_not_save_without_policy_acknowledgement(self):
        response = self.client.post(
            reverse("pregnancy_profile"),
            self._onboarding_payload(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Please acknowledge the Privacy &amp; Data Policy before saving "
            "your profile.",
        )
        profile = PregnancyProfile.objects.get(user=self.user)
        self.assertIsNone(profile.date_of_birth)
        self.assertEqual(self.user.first_name, "")

    def test_onboarding_saves_valid_profile_with_policy_acknowledgement(self):
        response = self.client.post(
            reverse("pregnancy_profile"),
            self._onboarding_payload(privacy_acknowledgement="on"),
        )

        self.assertRedirects(
            response, reverse("dashboard"), fetch_redirect_response=False
        )
        profile = PregnancyProfile.objects.get(user=self.user)
        self.assertEqual(profile.date_of_birth.isoformat(), "1995-04-12")
        self.assertEqual(
            profile.pregnancy_status, PregnancyProfile.PregnancyStatus.PREGNANT
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Taylor")

    def test_onboarding_profile_validation_still_applies_with_acknowledgement(self):
        payload = self._onboarding_payload(
            date_of_birth="",
            privacy_acknowledgement="on",
        )
        response = self.client.post(reverse("pregnancy_profile"), payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter your date of birth to complete this form.")
        self.assertNotContains(
            response,
            "Please acknowledge the Privacy &amp; Data Policy before saving",
        )
        self.assertIsNone(PregnancyProfile.objects.get(user=self.user).date_of_birth)

    def test_completed_profile_edit_does_not_require_policy_acknowledgement(self):
        self._complete_record()

        response = self.client.post(
            reverse("pregnancy_profile"),
            self._onboarding_payload(),
        )

        self.assertRedirects(
            response, reverse("profile"), fetch_redirect_response=False
        )

    def test_onboarding_profile_layout_is_responsive(self):
        response = self.client.get(reverse("pregnancy_profile"))
        css_path = (
            Path(__file__).resolve().parents[2]
            / "static"
            / "css"
            / "pregnabot.css"
        )
        css = css_path.read_text(encoding="utf-8")

        self.assertContains(response, 'class="my-profile-page is-profile-onboarding"')
        self.assertIn(
            ".my-profile-page.is-profile-onboarding .my-profile-editor "
            "{ width: 100%; max-width: 960px; justify-self: center; }",
            css,
        )
        self.assertIn(
            ".form-grid { display: grid; "
            "grid-template-columns: repeat(2, minmax(0, 1fr));",
            css,
        )
        self.assertIn(
            ".form-grid { grid-template-columns: minmax(0, 1fr); }",
            css,
        )

    def test_completed_profile_shows_overview_and_closed_editor(self):
        self._complete_record()
        response = self.client.get(reverse("pregnancy_profile"))

        self.assertContains(response, 'id="profile-overview"')
        self.assertNotContains(response, "Privacy & Data Policy")
        self.assertNotContains(response, 'name="privacy_acknowledgement"')
        self.assertContains(response, "Personal Information")
        self.assertContains(response, "Pregnancy Details")
        self.assertContains(response, "Address Information")
        self.assertContains(response, "Emergency Contact")
        self.assertContains(response, '<details class="my-profile-editor">')

    def test_legacy_record_keeps_dashboard_access_with_blank_dob_and_status(self):
        profile = self._complete_record()
        self.assertIsNone(profile.date_of_birth)
        self.assertEqual(profile.pregnancy_status, "")

        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertRedirects(
            self.client.get(reverse("public_home")),
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

    def test_empty_profile_remains_incomplete(self):
        PregnancyProfile.objects.create(user=self.user)

        self.assertRedirects(
            self.client.get(reverse("dashboard")),
            reverse("pregnancy_profile"),
            fetch_redirect_response=False,
        )

    def test_planning_pregnancy_submission_completes_onboarding(self):
        response = self.client.post(
            reverse("pregnancy_profile"),
            self._onboarding_payload(
                pregnancy_status=PregnancyProfile.PregnancyStatus.PLANNING,
                estimated_conception_date="",
                privacy_acknowledgement="on",
            ),
        )

        self.assertRedirects(
            response, reverse("dashboard"), fetch_redirect_response=False
        )
        profile = PregnancyProfile.objects.get(user=self.user)
        self.assertEqual(
            profile.pregnancy_status, PregnancyProfile.PregnancyStatus.PLANNING
        )
        self.assertIsNone(profile.estimated_conception_date)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_other_status_submission_completes_onboarding(self):
        response = self.client.post(
            reverse("pregnancy_profile"),
            self._onboarding_payload(
                pregnancy_status=PregnancyProfile.PregnancyStatus.OTHER,
                estimated_conception_date="",
                privacy_acknowledgement="on",
            ),
        )

        self.assertRedirects(
            response, reverse("dashboard"), fetch_redirect_response=False
        )
        profile = PregnancyProfile.objects.get(user=self.user)
        self.assertEqual(
            profile.pregnancy_status, PregnancyProfile.PregnancyStatus.OTHER
        )
        self.assertIsNone(profile.estimated_conception_date)

    def test_incomplete_record_can_bookmark_a_public_topic(self):
        topic = PregnancyTopic.objects.create(
            title="Public topic during onboarding",
            slug="public-topic-during-onboarding",
            category=PregnancyTopic.Category.NUTRITION,
            description="Public description.",
            content="Public content.",
        )
        toggle_url = reverse("bookmark_toggle", args=[topic.pk])

        response = self.client.post(toggle_url)

        self.assertRedirects(
            response,
            reverse("topic_detail", args=[topic.slug]),
            fetch_redirect_response=False,
        )
        self.assertTrue(
            TopicBookmark.objects.filter(user=self.user, topic=topic).exists()
        )

        self.client.logout()
        response = self.client.post(toggle_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        self.assertEqual(TopicBookmark.objects.count(), 1)

    def test_onboarding_gate_does_not_affect_anonymous_guests(self):
        self.client.logout()

        for url in (reverse("public_home"), reverse("chatbot"), reverse("chat_new")):
            with self.subTest(url=url):
                self.assertEqual(
                    self.client.get(url, follow=True).status_code,
                    200,
                )


class PregnancyProfileFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="phase1a-user",
            password="secret1234",
        )

    def _payload(self, **overrides):
        payload = {
            "first_name": "Taylor",
            "last_name": "Jones",
            "email": "phase1a@example.com",
            "date_of_birth": "1995-04-12",
            "pregnancy_status": PregnancyProfile.PregnancyStatus.PREGNANT,
            "estimated_conception_date": (
                timezone.localdate() - timedelta(days=70)
            ).isoformat(),
            "blood_type": "",
        }
        payload.update(overrides)
        return payload

    def test_date_of_birth_is_required(self):
        payload = self._payload()
        payload.pop("date_of_birth")
        form = PregnancyProfileForm(data=payload, user=self.user)

        self.assertFalse(form.is_valid())
        self.assertIn("date_of_birth", form.errors)

    def test_future_date_of_birth_is_rejected(self):
        form = PregnancyProfileForm(
            data=self._payload(
                date_of_birth=(timezone.localdate() + timedelta(days=1)).isoformat()
            ),
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("date_of_birth", form.errors)

    def test_pregnancy_status_is_required(self):
        form = PregnancyProfileForm(
            data=self._payload(pregnancy_status=""),
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("pregnancy_status", form.errors)

    def test_current_pregnancy_requires_an_estimated_conception_date(self):
        form = PregnancyProfileForm(
            data=self._payload(
                pregnancy_status=PregnancyProfile.PregnancyStatus.PREGNANT,
                estimated_conception_date="",
            ),
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("estimated_conception_date", form.errors)

    def test_future_conception_date_does_not_duplicate_the_missing_error(self):
        form = PregnancyProfileForm(
            data=self._payload(
                pregnancy_status=PregnancyProfile.PregnancyStatus.PREGNANT,
                estimated_conception_date=(
                    timezone.localdate() + timedelta(days=1)
                ).isoformat(),
            ),
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        errors = form.errors["estimated_conception_date"]
        self.assertIn(
            "The estimated conception date cannot be in the future.",
            errors,
        )
        self.assertNotIn(
            "Enter an estimated conception date for a current pregnancy.",
            errors,
        )

    def test_malformed_conception_date_reports_only_the_format_error(self):
        form = PregnancyProfileForm(
            data=self._payload(
                pregnancy_status=PregnancyProfile.PregnancyStatus.PREGNANT,
                estimated_conception_date="not-a-date",
            ),
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        errors = form.errors["estimated_conception_date"]
        self.assertIn("Enter a valid date.", errors)
        self.assertNotIn(
            "Enter an estimated conception date for a current pregnancy.",
            errors,
        )

    def test_planning_pregnancy_needs_no_estimated_conception_date(self):
        form = PregnancyProfileForm(
            data=self._payload(
                pregnancy_status=PregnancyProfile.PregnancyStatus.PLANNING,
                estimated_conception_date="",
            ),
            user=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_other_status_needs_no_estimated_conception_date(self):
        form = PregnancyProfileForm(
            data=self._payload(
                pregnancy_status=PregnancyProfile.PregnancyStatus.OTHER,
                estimated_conception_date="",
            ),
            user=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_blood_type_choices_are_unchanged_and_optional(self):
        self.assertEqual(
            PregnancyProfile.BLOOD_TYPE_CHOICES,
            [
                ("A+", "A+"),
                ("A-", "A-"),
                ("B+", "B+"),
                ("B-", "B-"),
                ("AB+", "AB+"),
                ("AB-", "AB-"),
                ("O+", "O+"),
                ("O-", "O-"),
                ("unknown", "Prefer not to say / Unknown"),
            ],
        )

        for blood_type in ("", "O+", "AB-", "unknown"):
            with self.subTest(blood_type=blood_type):
                form = PregnancyProfileForm(
                    data=self._payload(
                        pregnancy_status=PregnancyProfile.PregnancyStatus.PLANNING,
                        estimated_conception_date="",
                        blood_type=blood_type,
                    ),
                    user=self.user,
                )
                self.assertTrue(form.is_valid(), form.errors)


class PregnancyProfileViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="profile-view-user",
            email="profile-view@example.com",
            password="secret1234",
        )
        self.client.force_login(self.user)

    def _payload(self, **overrides):
        payload = {
            "save_profile": "1",
            "first_name": "Taylor",
            "last_name": "Jones",
            "email": "profile-view@example.com",
            "date_of_birth": "1995-04-12",
            "pregnancy_status": PregnancyProfile.PregnancyStatus.PREGNANT,
            "estimated_conception_date": (
                timezone.localdate() - timedelta(days=70)
            ).isoformat(),
            "blood_type": "",
            "privacy_acknowledgement": "on",
        }
        payload.update(overrides)
        return payload

    def _completed_profile(self, **overrides):
        values = {
            "estimated_conception_date": timezone.localdate() - timedelta(days=70),
            "pregnancy_status": PregnancyProfile.PregnancyStatus.PREGNANT,
            "date_of_birth": date(1995, 4, 12),
            "blood_type": "A+",
        }
        values.update(overrides)
        return PregnancyProfile.objects.create(user=self.user, **values)

    def _assert_onboarding_still_incomplete(self):
        self.assertRedirects(
            self.client.get(reverse("dashboard")),
            reverse("pregnancy_profile"),
            fetch_redirect_response=False,
        )

    def test_invalid_submission_redisplays_the_entered_values(self):
        response = self.client.post(
            reverse("pregnancy_profile"),
            self._payload(last_name="", blood_type="A+"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.assertContains(response, 'value="Taylor"')
        self.assertContains(response, 'value="profile-view@example.com"')
        self.assertContains(response, 'value="1995-04-12"')

        profile = PregnancyProfile.objects.get(user=self.user)
        self.assertEqual(profile.pregnancy_status, "")
        self.assertIsNone(profile.estimated_conception_date)
        self._assert_onboarding_still_incomplete()

    def test_pregnant_status_without_conception_date_blocks_onboarding(self):
        response = self.client.post(
            reverse("pregnancy_profile"),
            self._payload(estimated_conception_date=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Enter an estimated conception date for a current pregnancy.",
        )

        profile = PregnancyProfile.objects.get(user=self.user)
        self.assertEqual(profile.pregnancy_status, "")
        self.assertIsNone(profile.estimated_conception_date)
        self._assert_onboarding_still_incomplete()

    def test_missing_date_of_birth_blocks_onboarding(self):
        payload = self._payload(
            pregnancy_status=PregnancyProfile.PregnancyStatus.PLANNING,
            estimated_conception_date="",
        )
        payload.pop("date_of_birth")

        response = self.client.post(reverse("pregnancy_profile"), payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Enter your date of birth to complete this form.",
        )
        self.assertIsNone(PregnancyProfile.objects.get(user=self.user).date_of_birth)
        self._assert_onboarding_still_incomplete()

    def test_future_date_of_birth_blocks_onboarding(self):
        response = self.client.post(
            reverse("pregnancy_profile"),
            self._payload(
                pregnancy_status=PregnancyProfile.PregnancyStatus.PLANNING,
                estimated_conception_date="",
                date_of_birth=(timezone.localdate() + timedelta(days=1)).isoformat(),
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The date of birth cannot be in the future.")
        self.assertIsNone(PregnancyProfile.objects.get(user=self.user).date_of_birth)
        self._assert_onboarding_still_incomplete()

    def test_invalid_edit_keeps_previously_saved_values(self):
        profile = self._completed_profile()
        saved_conception_date = profile.estimated_conception_date

        response = self.client.post(
            reverse("pregnancy_profile"),
            self._payload(pregnancy_status="", blood_type="A+"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Select your pregnancy status to complete this form.",
        )

        profile.refresh_from_db()
        self.assertEqual(profile.estimated_conception_date, saved_conception_date)
        self.assertEqual(profile.blood_type, "A+")
        self.assertEqual(profile.date_of_birth, date(1995, 4, 12))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_valid_edit_keeps_previously_saved_values(self):
        profile = self._completed_profile()
        saved_conception_date = profile.estimated_conception_date

        response = self.client.post(
            reverse("pregnancy_profile"),
            self._payload(
                estimated_conception_date=saved_conception_date.isoformat(),
                blood_type="A+",
            ),
            follow=True,
        )

        self.assertRedirects(response, reverse("profile"))
        self.assertContains(response, "Your profile has been updated.")

        profile.refresh_from_db()
        self.assertEqual(profile.estimated_conception_date, saved_conception_date)
        self.assertEqual(profile.blood_type, "A+")
        self.assertEqual(
            profile.pregnancy_status,
            PregnancyProfile.PregnancyStatus.PREGNANT,
        )
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_legacy_profile_edit_keeps_the_saved_conception_date(self):
        saved_conception_date = timezone.localdate() - timedelta(days=70)
        profile = PregnancyProfile.objects.create(
            user=self.user,
            estimated_conception_date=saved_conception_date,
        )
        self.assertIsNone(profile.date_of_birth)
        self.assertEqual(profile.pregnancy_status, "")

        response = self.client.get(reverse("pregnancy_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{saved_conception_date.isoformat()}"')

        response = self.client.post(
            reverse("pregnancy_profile"),
            self._payload(
                estimated_conception_date=saved_conception_date.isoformat(),
            ),
        )

        self.assertRedirects(
            response,
            reverse("profile"),
            fetch_redirect_response=False,
        )
        profile.refresh_from_db()
        self.assertEqual(profile.estimated_conception_date, saved_conception_date)
        self.assertEqual(
            profile.pregnancy_status,
            PregnancyProfile.PregnancyStatus.PREGNANT,
        )
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_opening_my_profile_displays_the_saved_values(self):
        self._completed_profile(
            blood_type="O+",
            phone_number="+63 912 345 6789",
            healthcare_provider="Dr. Ana Reyes",
            city="Iloilo City",
            province="Iloilo",
            postal_code="5000",
            emergency_contact_name="Juan Dela Cruz",
            emergency_contact_relationship="Partner",
            emergency_contact_number="+63 912 987 6543",
        )

        response = self.client.get(reverse("profile"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pregnancy/prenatal_profile.html")
        self.assertContains(response, "April 12, 1995")
        self.assertContains(response, "profile-view@example.com")
        self.assertContains(response, "+63 912 345 6789")
        self.assertContains(response, "Dr. Ana Reyes")
        self.assertContains(response, "Iloilo City")
        self.assertContains(response, "Iloilo")
        self.assertContains(response, "5000")
        self.assertContains(response, "Juan Dela Cruz")
        self.assertContains(response, "Partner")
        self.assertContains(response, "+63 912 987 6543")
        self.assertContains(response, "Personal Information")
        self.assertContains(response, "Pregnancy Details")
        self.assertContains(response, "Address Information")
        self.assertContains(response, "Emergency Contact")
        self.assertNotContains(response, "Medical Appointments")
        self.assertRegex(response.content.decode(), '<details class="my-profile-editor">')
        self.assertContains(response, 'id="pregnancy-record-form"')
        self.assertContains(response, 'name="save_profile"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_profile_saves_and_persists_all_additional_fields(self):
        fields = {
            "phone_number": "+63 912 345 6789",
            "healthcare_provider": "Dr. Ana Reyes",
            "city": "Iloilo City",
            "province": "Iloilo",
            "postal_code": "5000",
            "emergency_contact_name": "Juan Dela Cruz",
            "emergency_contact_relationship": "Partner",
            "emergency_contact_number": "+63 912 987 6543",
        }

        response = self.client.post(reverse("profile"), self._payload(**fields))

        self.assertRedirects(
            response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )
        profile = PregnancyProfile.objects.get(user=self.user)
        for field_name, expected in fields.items():
            with self.subTest(field=field_name):
                self.assertEqual(getattr(profile, field_name), expected)

        response = self.client.get(reverse("profile"))
        for expected in fields.values():
            with self.subTest(value=expected):
                self.assertContains(response, expected)

    def test_partial_profile_update_preserves_fields_not_submitted(self):
        profile = self._completed_profile(
            phone_number="+63 900 000 0001",
            healthcare_provider="Existing Provider",
            city="Old City",
            province="Old Province",
            postal_code="1111",
            emergency_contact_name="Existing Contact",
            emergency_contact_relationship="Relative",
            emergency_contact_number="+63 900 000 0002",
        )

        response = self.client.post(
            reverse("profile"),
            self._payload(city="New City"),
        )

        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)
        profile.refresh_from_db()
        self.assertEqual(profile.city, "New City")
        self.assertEqual(profile.phone_number, "+63 900 000 0001")
        self.assertEqual(profile.healthcare_provider, "Existing Provider")
        self.assertEqual(profile.province, "Old Province")
        self.assertEqual(profile.postal_code, "1111")
        self.assertEqual(profile.emergency_contact_name, "Existing Contact")
        self.assertEqual(profile.emergency_contact_relationship, "Relative")
        self.assertEqual(profile.emergency_contact_number, "+63 900 000 0002")

    def test_optional_profile_fields_can_be_cleared(self):
        optional_fields = PregnancyProfileForm.OPTIONAL_PROFILE_FIELDS
        self._completed_profile(
            **{field_name: "Saved value" for field_name in optional_fields}
        )

        response = self.client.post(
            reverse("profile"),
            self._payload(**{field_name: "" for field_name in optional_fields}),
        )

        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)
        profile = PregnancyProfile.objects.get(user=self.user)
        for field_name in optional_fields:
            with self.subTest(field=field_name):
                self.assertEqual(getattr(profile, field_name), "")

    def test_invalid_submission_keeps_previous_saved_profile_fields(self):
        profile = self._completed_profile(
            city="Saved City",
            phone_number="Saved Phone",
        )

        response = self.client.post(
            reverse("profile"),
            self._payload(email="not-an-email", city="Submitted City"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a valid email address.")
        self.assertContains(response, 'value="Submitted City"')
        self.assertRegex(response.content.decode(), '<details class="my-profile-editor" open>')
        profile.refresh_from_db()
        self.assertEqual(profile.city, "Saved City")
        self.assertEqual(profile.phone_number, "Saved Phone")

    def test_profile_reads_and_writes_only_the_authenticated_users_record(self):
        own_profile = self._completed_profile(city="Own City")
        other_user = get_user_model().objects.create_user(username="other-profile-user")
        other_profile = PregnancyProfile.objects.create(
            user=other_user,
            city="Private Other City",
            emergency_contact_name="Private Other Contact",
        )

        response = self.client.get(reverse("profile"))
        self.assertContains(response, "Own City")
        self.assertNotContains(response, "Private Other City")
        self.assertNotContains(response, "Private Other Contact")

        response = self.client.post(
            reverse("profile"),
            self._payload(city="Updated Own City", user=str(other_user.pk)),
        )
        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)
        own_profile.refresh_from_db()
        other_profile.refresh_from_db()
        self.assertEqual(own_profile.city, "Updated Own City")
        self.assertEqual(other_profile.city, "Private Other City")
        self.assertEqual(other_profile.emergency_contact_name, "Private Other Contact")

    def test_pregnancy_week_and_due_date_display_only_for_valid_current_pregnancy(self):
        profile = self._completed_profile()
        response = self.client.get(reverse("profile"))
        self.assertContains(response, f"{profile.gestational_week()} weeks")
        expected_due_date = date_format(profile.estimated_due_date(), "F j, Y")
        self.assertContains(response, expected_due_date)

        profile.pregnancy_status = PregnancyProfile.PregnancyStatus.PLANNING
        profile.save(update_fields=["pregnancy_status"])
        response = self.client.get(reverse("profile"))
        self.assertNotContains(response, "Current Week")
        self.assertNotContains(response, "Expected Due Date")

        profile.pregnancy_status = PregnancyProfile.PregnancyStatus.PREGNANT
        profile.estimated_conception_date = timezone.localdate() + timedelta(days=1)
        profile.save(update_fields=["pregnancy_status", "estimated_conception_date"])
        response = self.client.get(reverse("profile"))
        self.assertNotContains(response, "Current Week")
        self.assertNotContains(response, "Expected Due Date")

    def test_profile_survives_logout_and_login(self):
        self.client.post(reverse("profile"), self._payload(blood_type="O+"))

        self.client.post(reverse("logout"))
        self.client.force_login(self.user)

        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Taylor"')

        profile = PregnancyProfile.objects.get(user=self.user)
        self.assertEqual(profile.blood_type, "O+")
        self.assertEqual(
            profile.pregnancy_status,
            PregnancyProfile.PregnancyStatus.PREGNANT,
        )

    def test_repeated_saves_update_the_same_profile(self):
        for _ in range(2):
            self.client.post(reverse("profile"), self._payload(blood_type="O+"))

        self.assertEqual(PregnancyProfile.objects.filter(user=self.user).count(), 1)

    def test_profile_writes_are_scoped_to_the_authenticated_user(self):
        other = get_user_model().objects.create_user(username="unrelated-profile-user")

        self.client.post(reverse("profile"), self._payload(user=str(other.pk)))

        self.assertEqual(PregnancyProfile.objects.filter(user=self.user).count(), 1)
        self.assertFalse(PregnancyProfile.objects.filter(user=other).exists())


class SettingsViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="settings-user",
            password="secret1234",
            first_name="Ana",
            last_name="Reyes",
            email="ana@example.com",
        )
        PregnancyProfile.objects.create(
            user=self.user,
            pregnancy_status=PregnancyProfile.PregnancyStatus.PREGNANT,
            estimated_conception_date=timezone.localdate() - timedelta(days=70),
            date_of_birth=date(1994, 3, 8),
        )
        self.client.force_login(self.user)

    def _account_payload(self, **overrides):
        payload = {
            "update_account": "1",
            "first_name": "Ana",
            "last_name": "Reyes",
            "email": "ana@example.com",
        }
        payload.update(overrides)
        return payload

    def _password_payload(self, **overrides):
        payload = {
            "change_password": "1",
            "old_password": "secret1234",
            "new_password1": "Br1ght-Future-2026",
            "new_password2": "Br1ght-Future-2026",
        }
        payload.update(overrides)
        return payload

    def test_settings_page_requires_authentication(self):
        self.client.logout()

        response = self.client.get(reverse("settings"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_settings_page_displays_the_signed_in_account(self):
        get_user_model().objects.create_user(
            username="other-settings-user", email="someone-else@example.com"
        )

        response = self.client.get(reverse("settings"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pregnancy/settings.html")
        self.assertContains(response, "settings-user")
        self.assertContains(response, 'value="Ana"')
        self.assertContains(response, 'value="ana@example.com"')
        self.assertContains(response, "Notification Preferences")
        self.assertContains(response, 'id="privacy-data-heading"')
        self.assertContains(response, "Your pregnancy profile is shown and edited")
        self.assertContains(response, "not registered in Django admin")
        self.assertContains(response, "Authorized staff administrators")
        self.assertContains(response, "associated messages")
        self.assertContains(response, "AI chatbot provider")
        self.assertContains(response, "When OpenAI is selected")
        self.assertContains(response, "configured Ollama endpoint")
        self.assertContains(response, "does not silently switch providers")
        self.assertContains(response, "About PregnaBot")
        self.assertNotContains(response, "someone-else@example.com")

    def test_sidebar_links_to_settings_and_marks_it_active(self):
        response = self.client.get(reverse("settings"))

        self.assertContains(response, f'href="{reverse("settings")}"')
        self.assertContains(response, "is-active")

    def test_account_details_update_the_signed_in_user(self):
        response = self.client.post(
            reverse("settings"),
            self._account_payload(
                first_name="Bea", last_name="Cruz", email="bea@example.com"
            ),
        )

        self.assertRedirects(
            response, reverse("settings"), fetch_redirect_response=False
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Bea")
        self.assertEqual(self.user.last_name, "Cruz")
        self.assertEqual(self.user.email, "bea@example.com")

    def test_account_update_keeps_the_signed_in_user_after_reload(self):
        self.client.post(
            reverse("settings"),
            self._account_payload(first_name="Bea"),
        )

        response = self.client.get(reverse("settings"))

        self.assertContains(response, 'value="Bea"')

    def test_account_update_ignores_a_supplied_user_id(self):
        other = get_user_model().objects.create_user(
            username="unrelated-settings-user",
            first_name="Original",
            email="unrelated@example.com",
        )

        self.client.post(
            reverse("settings"),
            self._account_payload(user=str(other.pk), first_name="Hijacked"),
        )

        other.refresh_from_db()
        self.assertEqual(other.first_name, "Original")
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Hijacked")

    def test_account_update_cannot_change_the_username(self):
        self.client.post(reverse("settings"), self._account_payload(username="renamed"))

        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "settings-user")

    def test_account_update_rejects_an_email_already_in_use(self):
        get_user_model().objects.create_user(
            username="email-owner", email="taken@example.com"
        )

        response = self.client.post(
            reverse("settings"), self._account_payload(email="taken@example.com")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "That email address is already in use.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ana@example.com")

    def test_invalid_account_submission_keeps_the_entered_values(self):
        response = self.client.post(
            reverse("settings"), self._account_payload(last_name="")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.assertContains(response, 'value="Ana"')

    def test_password_change_updates_the_password_and_keeps_the_session(self):
        response = self.client.post(reverse("settings"), self._password_payload())

        self.assertRedirects(
            response, reverse("settings"), fetch_redirect_response=False
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Br1ght-Future-2026"))
        self.assertFalse(self.user.check_password("secret1234"))
        self.assertEqual(self.client.get(reverse("settings")).status_code, 200)

    def test_password_change_requires_the_current_password(self):
        response = self.client.post(
            reverse("settings"), self._password_payload(old_password="wrong-password")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your old password was entered incorrectly.")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("secret1234"))

    def test_password_change_rejects_a_weak_new_password(self):
        response = self.client.post(
            reverse("settings"),
            self._password_payload(new_password1="123", new_password2="123"),
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("secret1234"))

    def test_password_change_rejects_a_mismatched_confirmation(self):
        response = self.client.post(
            reverse("settings"),
            self._password_payload(new_password2="Different-Pass-2026"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The two password fields didn’t match.")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("secret1234"))

    def test_incomplete_users_are_sent_to_onboarding_from_settings(self):
        self.user.pregnancy_profile.delete()

        response = self.client.get(reverse("settings"))

        self.assertRedirects(
            response, reverse("pregnancy_profile"), fetch_redirect_response=False
        )
