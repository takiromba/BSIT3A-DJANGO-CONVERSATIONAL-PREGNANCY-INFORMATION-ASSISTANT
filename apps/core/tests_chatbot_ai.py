import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .chatbot import MAX_QUESTIONS_PER_SUBMISSION
from .models import FAQ, ChatConversation, ChatMessage, PregnancyProfile
from .services.ai_provider import ProviderError, ProviderTimeout
from .services.pregnabot import DATASET_PATH, is_urgent


@override_settings(AI_PROVIDER="ollama")
class ChatbotAIIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="ai-chat-user",
            password="safe-test-password",
        )
        self.client.force_login(self.user)
        dataset_patch = patch("apps.core.services.pregnabot.DATASET_ENTRIES", [])
        dataset_patch.start()
        self.addCleanup(dataset_patch.stop)

    def _faq(self, **overrides):
        values = {
            "question": "How should I discuss folate supplements during pregnancy?",
            "answer": "Ask a healthcare professional which supplement is right for you.",
            "source_name": "Example Health Service",
            "source_url": "https://example.org/pregnancy/folate",
        }
        values.update(overrides)
        return FAQ.objects.create(**values)

    def _send(self, question, conversation=None):
        url = (
            reverse("chat_conversation", args=[conversation.pk])
            if conversation
            else reverse("chatbot")
        )
        return self.client.post(url, {"question": question})

    def _bundled_dataset(self):
        return json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    @patch("apps.core.services.ai_provider.generate_response")
    def test_negated_bleeding_does_not_suppress_chest_pain_guidance(self, generate):
        generate.return_value = "This should not be used for urgent symptoms."
        response = self._send("No bleeding. Chest pain.")

        conversation = ChatConversation.objects.get(user=self.user)
        assistant = conversation.messages.get(role=ChatMessage.Role.ASSISTANT)
        self.assertRedirects(
            response,
            reverse("chat_conversation", args=[conversation.pk]),
        )
        self.assertIn("urgent assessment", assistant.content)
        self.assertIn("Do not wait", assistant.content)
        generate.assert_not_called()

    @patch("apps.core.services.ai_provider.generate_response")
    def test_contrastive_abdominal_pain_triggers_urgent_guidance(self, generate):
        response = self._send("No fever, but severe abdominal pain.")

        conversation = ChatConversation.objects.get(user=self.user)
        assistant = conversation.messages.get(role=ChatMessage.Role.ASSISTANT)
        self.assertRedirects(
            response,
            reverse("chat_conversation", args=[conversation.pk]),
        )
        self.assertIn("urgent assessment", assistant.content)
        self.assertIn("Do not wait", assistant.content)
        generate.assert_not_called()

    def test_genuinely_negated_urgent_symptom_does_not_trigger_guidance(self):
        self.assertFalse(is_urgent("I do not have chest pain."))

    def test_existing_urgent_symptom_detection_remains_enabled(self):
        self.assertTrue(is_urgent("I have heavy bleeding."))

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="A healthcare professional can help with that follow-up.",
    )
    def test_existing_conversation_form_and_follow_up_keep_same_conversation(
        self,
        generate,
    ):
        faq = self._faq()
        conversation = ChatConversation.objects.create(
            user=self.user,
            title="Folate supplements",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.USER,
            content="What should I ask about folate?",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.ASSISTANT,
            answer_title=faq.question,
            content=faq.answer,
        )

        page = self.client.get(reverse("chat_conversation", args=[conversation.pk]))

        self.assertContains(
            page,
            f'action="{reverse("chat_conversation", args=[conversation.pk])}"',
        )

        response = self._send("Can you explain that further?", conversation)

        self.assertRedirects(
            response,
            reverse("chat_conversation", args=[conversation.pk]),
        )
        self.assertEqual(ChatConversation.objects.filter(user=self.user).count(), 1)
        self.assertEqual(conversation.messages.count(), 4)
        self.assertEqual(
            list(
                conversation.messages.order_by("pk").values_list("content", flat=True)
            )[:2],
            [
                "What should I ask about folate?",
                faq.answer,
            ],
        )
        generate.assert_called_once()
        self.assertIn(
            "What should I ask about folate?",
            generate.call_args.args[0][1]["content"],
        )

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="A healthcare professional can answer your question.",
    )
    def test_new_chat_creates_a_separate_conversation(self, generate):
        faq = self._faq()
        existing = ChatConversation.objects.create(
            user=self.user,
            title="Earlier conversation",
        )

        response = self._send(faq.question)

        new_conversation = ChatConversation.objects.exclude(pk=existing.pk).get(
            user=self.user
        )
        self.assertNotEqual(new_conversation.pk, existing.pk)
        self.assertEqual(ChatConversation.objects.filter(user=self.user).count(), 2)
        self.assertRedirects(
            response,
            reverse("chat_conversation", args=[new_conversation.pk]),
        )
        self.assertEqual(new_conversation.messages.count(), 2)
        self.assertEqual(existing.messages.count(), 0)
        generate.assert_called_once()

    @patch("apps.core.services.ai_provider.generate_response")
    def test_over_limit_submission_is_rejected_without_partial_messages(
        self,
        generate,
    ):
        submitted_questions = [
            f"Question {index}?" for index in range(MAX_QUESTIONS_PER_SUBMISSION + 1)
        ]

        response = self._send("\n".join(submitted_questions))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("chatbot"))
        self.assertEqual(ChatConversation.objects.filter(user=self.user).count(), 0)
        self.assertEqual(ChatMessage.objects.count(), 0)
        self.assertContains(
            self.client.get(response.url),
            f"no more than {MAX_QUESTIONS_PER_SUBMISSION} questions at a time",
        )
        generate.assert_not_called()

    def test_post_cannot_append_to_another_users_conversation(self):
        other_user = get_user_model().objects.create_user(
            username="other-ai-chat-user",
            password="test-password",
        )
        conversation = ChatConversation.objects.create(
            user=other_user,
            title="Private conversation",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.USER,
            content="Existing private question",
        )
        initial_message_count = conversation.messages.count()

        response = self.client.post(
            reverse("chat_conversation", args=[conversation.pk]),
            {"question": "Try to append a private message"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(conversation.messages.count(), initial_message_count)
        self.assertEqual(ChatConversation.objects.filter(user=self.user).count(), 0)

    @patch("apps.core.services.ai_provider.generate_response")
    def test_food_avoidance_does_not_match_healthy_food_faq(self, generate):
        self._faq(
            question="What foods are healthy during pregnancy?",
            answer=(
                "A balanced diet includes vegetables and fruit. Some foods should "
                "be avoided during pregnancy."
            ),
            source_name="General Pregnancy Source",
            source_url="https://example.org/pregnancy",
        )
        healthy_dataset_entry = {
            "question": "What foods are healthy during pregnancy?",
            "alternate_questions": [],
            "answer": "A balanced diet includes vegetables and fruit.",
            "source_name": "General Pregnancy Source",
            "source_url": "https://example.org/pregnancy",
            "is_warning_sign": False,
            "is_published": True,
        }

        with patch(
            "apps.core.services.pregnabot.DATASET_ENTRIES",
            [healthy_dataset_entry],
        ):
            self._send("What foods should I avoid during pregnancy?")

        assistant = ChatMessage.objects.get(
            conversation__user=self.user,
            role=ChatMessage.Role.ASSISTANT,
        )
        self.assertEqual(assistant.answer_title, "No matching answer")
        self.assertFalse(assistant.source_name)
        self.assertFalse(assistant.source_url)
        self.assertNotIn("What foods are healthy", assistant.answer_title)
        self.assertEqual(
            ChatMessage.objects.filter(conversation=assistant.conversation).count(),
            2,
        )
        generate.assert_not_called()

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="Published food-safety information, paraphrased.",
    )
    def test_food_avoidance_matches_published_explicit_alternate_question(
        self,
        generate,
    ):
        avoidance_entry = {
            "question": "Which foods should be avoided while pregnant?",
            "alternate_questions": [
                "What foods should I avoid during pregnancy?",
            ],
            "answer": "Published answer about food avoidance.",
            "source_name": "Food Safety Source",
            "source_url": "https://example.org/food-safety",
            "is_warning_sign": False,
            "is_published": True,
        }

        with patch(
            "apps.core.services.pregnabot.DATASET_ENTRIES",
            [avoidance_entry],
        ):
            self._send("What foods should I avoid during pregnancy?")

        assistant = ChatMessage.objects.get(
            conversation__user=self.user,
            role=ChatMessage.Role.ASSISTANT,
        )
        self.assertEqual(
            assistant.answer_title,
            "Which foods should be avoided while pregnant?",
        )
        self.assertEqual(assistant.source_name, "Food Safety Source")
        self.assertEqual(assistant.source_url, "https://example.org/food-safety")
        generate.assert_called_once()

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value=(
            "A healthcare professional can help you choose a folate supplement "
            "that is appropriate for you."
        ),
    )
    def test_retrieved_answer_is_paraphrased_with_exact_source_and_title_preserved(
        self,
        generate,
    ):
        faq = self._faq()
        question = "Tell me about folate supplements"

        response = self._send(question)

        conversation = ChatConversation.objects.get(user=self.user)
        assistant = conversation.messages.get(role=ChatMessage.Role.ASSISTANT)
        self.assertRedirects(
            response,
            reverse("chat_conversation", args=[conversation.pk]),
        )
        self.assertEqual(
            assistant.content,
            "A healthcare professional can help you choose a folate supplement "
            "that is appropriate for you.",
        )
        self.assertEqual(assistant.answer_title, faq.question)
        self.assertEqual(assistant.source_name, faq.source_name)
        self.assertEqual(assistant.source_url, faq.source_url)
        self.assertEqual(conversation.messages.count(), 2)
        generate.assert_called_once()
        provider_prompt = generate.call_args.args[0][1]["content"]
        self.assertIn(question, provider_prompt)
        self.assertIn(faq.answer, provider_prompt)
        self.assertNotIn(faq.source_url, provider_prompt)

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="Choose a balanced range of foods and discuss individual needs with a clinician.",
    )
    def test_bundled_nutrition_answer_uses_a_specific_source(self, generate):
        records = self._bundled_dataset()
        nutrition = next(
            record
            for record in records
            if record["question"] == "What foods are healthy during pregnancy?"
        )

        with patch("apps.core.services.pregnabot.DATASET_ENTRIES", records):
            self._send(nutrition["question"])

        assistant = ChatMessage.objects.get(
            conversation__user=self.user,
            role=ChatMessage.Role.ASSISTANT,
        )
        self.assertEqual(assistant.answer_title, nutrition["question"])
        self.assertEqual(assistant.source_name, "MedlinePlus")
        self.assertEqual(
            assistant.source_url,
            "https://medlineplus.gov/pregnancyandnutrition.html",
        )
        self.assertNotEqual(
            assistant.source_url,
            "https://www.who.int/health-topics/pregnancy",
        )
        generate.assert_called_once()

    @patch(
        "apps.core.services.ai_provider.generate_response",
        side_effect=ProviderError("provider unavailable"),
    )
    def test_bundled_fever_fallback_includes_cdc_warning_threshold(self, generate):
        records = self._bundled_dataset()
        fever = next(
            record
            for record in records
            if record["question"] == "What if I have a fever during pregnancy?"
        )

        with patch("apps.core.services.pregnabot.DATASET_ENTRIES", records):
            self._send(fever["question"])

        assistant = ChatMessage.objects.get(
            conversation__user=self.user,
            role=ChatMessage.Role.ASSISTANT,
        )
        self.assertIn("100.4°F (38°C)", assistant.content)
        self.assertIn("Seek medical care immediately", assistant.content)
        self.assertEqual(
            assistant.source_name, "Centers for Disease Control and Prevention"
        )
        self.assertEqual(
            assistant.source_url,
            "https://www.cdc.gov/hearher/maternal-warning-signs/index.html",
        )
        generate.assert_called_once()

    def test_chat_renders_escaped_list_markers_and_escapes_html_content(self):
        conversation = ChatConversation.objects.create(
            user=self.user,
            title="List formatting",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.ASSISTANT,
            content=(
                "First paragraph<br><br>Second paragraph\nNormal line\n"
                "Encoded break &lt;br&gt; marker\n"
                r"Escaped paragraph one\n\nEscaped paragraph two"
                "\nHelpful items:\n"
                "\\- First item\n"
                "\\* Second item\n"
                "1. Numbered item\n"
                "<script>alert('unsafe')</script>"
            ),
        )

        response = self.client.get(
            reverse("chat_conversation", args=[conversation.pk]),
        )
        rendered = response.content.decode()

        self.assertIn(
            "First paragraph<br>Second paragraph<br>Normal line",
            rendered,
        )
        self.assertIn("Encoded break <br> marker", rendered)
        self.assertIn(
            "Escaped paragraph one<br>Escaped paragraph two",
            rendered,
        )
        self.assertContains(
            response,
            "<ul><li>First item</li><li>Second item</li></ul>",
            html=False,
        )
        self.assertContains(
            response,
            "<ol><li>Numbered item</li></ol>",
            html=False,
        )
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>alert('unsafe')</script>", rendered)
        self.assertNotIn(r"\-", rendered)
        self.assertNotIn(r"\*", rendered)

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value=r"First paragraph\n\nSecond paragraph\n- Bullet item\n1. Numbered item",
    )
    def test_ollama_literal_escaped_newlines_render_as_compact_lines(self, generate):
        self._faq()
        self._send("Tell me about folate supplements")
        conversation = ChatConversation.objects.get(user=self.user)

        response = self.client.get(
            reverse("chat_conversation", args=[conversation.pk]),
        )
        rendered = response.content.decode()

        self.assertContains(
            response,
            (
                "First paragraph<br>Second paragraph<br>"
                "<ul><li>Bullet item</li></ul><br>"
                "<ol><li>Numbered item</li></ol>"
            ),
            html=False,
        )
        self.assertNotIn(r"\n", rendered)
        self.assertNotIn("<br><br>", rendered)
        generate.assert_called_once()

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="Talk with a healthcare professional about folate supplements.",
    )
    def test_retrieved_answer_without_source_keeps_source_fields_empty(self, generate):
        self._faq(source_name="", source_url="")

        self._send("Tell me about folate supplements")

        assistant = ChatMessage.objects.get(
            conversation__user=self.user,
            role=ChatMessage.Role.ASSISTANT,
        )
        self.assertEqual(
            assistant.content,
            "Talk with a healthcare professional about folate supplements.",
        )
        self.assertFalse(assistant.source_name)
        self.assertFalse(assistant.source_url)
        generate.assert_called_once()

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="Here is general information about fever during pregnancy.",
    )
    def test_introduction_after_fever_question_is_independent_and_has_no_source(
        self, generate
    ):
        fever_faq = self._faq(
            question="What if I have a fever during pregnancy?",
            answer="Contact a healthcare professional if you are concerned about a fever.",
            source_name="Fever Health Source",
            source_url="https://example.org/pregnancy/fever",
        )

        self._send(fever_faq.question)
        conversation = ChatConversation.objects.get(user=self.user)
        question = "Hello PregnaBot, please introduce yourself."

        self._send(question, conversation)

        assistant = conversation.messages.filter(
            role=ChatMessage.Role.ASSISTANT,
        ).latest("pk")
        self.assertIn("I’m PregnaBot", assistant.content)
        self.assertIn("pregnancy information", assistant.content)
        self.assertNotIn("fever", assistant.content.casefold())
        self.assertEqual(assistant.answer_title, question)
        self.assertFalse(assistant.source_name)
        self.assertFalse(assistant.source_url)

        response = self.client.get(reverse("chat_conversation", args=[conversation.pk]))
        self.assertContains(response, f"PregnaBot · {question}")
        self.assertEqual(
            conversation.messages.filter(role=ChatMessage.Role.USER).count(),
            2,
        )
        generate.assert_called_once()

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="A healthcare professional can assess a fever.",
    )
    def test_newline_separated_questions_create_separate_message_pairs(self, generate):
        fever_faq = self._faq(
            question="What if I have a fever during pregnancy?",
            answer="Contact a healthcare professional if you are concerned about a fever.",
            source_name="Fever Health Source",
            source_url="https://example.org/pregnancy/fever",
        )
        introduction = "Hello PregnaBot, please introduce yourself."

        response = self._send(f"{fever_faq.question}\r\n\r\n{introduction}")

        conversation = ChatConversation.objects.get(user=self.user)
        records = list(conversation.messages.order_by("pk"))
        self.assertRedirects(
            response,
            reverse("chat_conversation", args=[conversation.pk]),
        )
        self.assertEqual(
            [(message.role, message.content) for message in records],
            [
                (ChatMessage.Role.USER, fever_faq.question),
                (
                    ChatMessage.Role.ASSISTANT,
                    "A healthcare professional can assess a fever.",
                ),
                (ChatMessage.Role.USER, introduction),
                (ChatMessage.Role.ASSISTANT, records[3].content),
            ],
        )
        fever_reply, introduction_reply = records[1], records[3]
        self.assertEqual(fever_reply.answer_title, fever_faq.question)
        self.assertEqual(fever_reply.source_name, fever_faq.source_name)
        self.assertEqual(fever_reply.source_url, fever_faq.source_url)
        self.assertEqual(introduction_reply.answer_title, introduction)
        self.assertIn("I’m PregnaBot", introduction_reply.content)
        self.assertNotIn("fever", introduction_reply.content.casefold())
        self.assertFalse(introduction_reply.source_name)
        self.assertFalse(introduction_reply.source_url)
        self.assertEqual(conversation.title, fever_faq.question)
        generate.assert_called_once()

        rendered = self.client.get(reverse("chat_conversation", args=[conversation.pk]))
        self.assertContains(rendered, f"PregnaBot · {fever_faq.question}")
        self.assertContains(rendered, f"PregnaBot · {introduction}")

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="A balanced diet includes a variety of nourishing foods.",
    )
    def test_repeated_questions_create_one_answer_per_question(self, generate):
        faq = self._faq(
            question="What foods are healthy during pregnancy?",
            answer="A balanced diet includes a variety of nourishing foods.",
            source_name="Nutrition Information Source",
            source_url="https://example.org/pregnancy/nutrition",
        )

        self._send(f"{faq.question}\n{faq.question}")

        conversation = ChatConversation.objects.get(user=self.user)
        records = list(conversation.messages.order_by("pk"))
        self.assertEqual(
            [message.role for message in records],
            [
                ChatMessage.Role.USER,
                ChatMessage.Role.ASSISTANT,
                ChatMessage.Role.USER,
                ChatMessage.Role.ASSISTANT,
            ],
        )
        self.assertEqual(conversation.title, faq.question)
        self.assertEqual(
            [
                message.content
                for message in records
                if message.role == ChatMessage.Role.USER
            ],
            [faq.question, faq.question],
        )
        self.assertEqual(
            [
                message.content
                for message in records
                if message.role == ChatMessage.Role.ASSISTANT
            ],
            [generate.return_value, generate.return_value],
        )
        self.assertEqual(generate.call_count, 2)

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="Unsupported generated folate dosage.",
    )
    def test_follow_up_uses_only_current_conversation_history(self, generate):
        faq = self._faq()
        conversation = ChatConversation.objects.create(
            user=self.user,
            title="Folate question",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.USER,
            content="I am asking about folate supplements during pregnancy.",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.ASSISTANT,
            content="I can share general information from the library.",
        )

        other_user = get_user_model().objects.create_user(
            username="other-ai-chat-user",
            password="safe-test-password",
        )
        other_conversation = ChatConversation.objects.create(
            user=other_user,
            title="Private conversation",
        )
        ChatMessage.objects.create(
            conversation=other_conversation,
            role=ChatMessage.Role.USER,
            content="OTHER-USER-PRIVATE-CONTENT",
        )
        PregnancyProfile.objects.create(user=self.user, blood_type="A+")

        self._send("How much should I take?", conversation)

        assistant = conversation.messages.filter(
            role=ChatMessage.Role.ASSISTANT,
        ).latest("pk")
        self.assertEqual(assistant.content, "Unsupported generated folate dosage.")
        self.assertEqual(assistant.source_name, faq.source_name)
        self.assertEqual(assistant.source_url, faq.source_url)
        self.assertEqual(assistant.answer_title, faq.question)
        generate.assert_called_once()
        provider_prompt = generate.call_args.args[0][1]["content"]
        self.assertIn("How much should I take?", provider_prompt)
        self.assertIn(
            "I am asking about folate supplements during pregnancy.",
            provider_prompt,
        )
        self.assertIn("Relevant earlier answer:", provider_prompt)
        self.assertIn(
            "I can share general information from the library.",
            provider_prompt,
        )
        self.assertIn(faq.answer, provider_prompt)
        self.assertNotIn("OTHER-USER-PRIVATE-CONTENT", provider_prompt)
        self.assertNotIn("A+", provider_prompt)

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="A healthcare professional should assess a fever during pregnancy.",
    )
    def test_fever_follow_ups_retrieve_fever_context_not_abdominal_pain(
        self,
        generate,
    ):
        fever_question = "What if I have a fever during pregnancy?"
        fever_answer = (
            "A fever during pregnancy should be assessed, especially if it is "
            "high or persistent. A healthcare professional can advise what "
            "evaluation is needed."
        )
        fever_source = {
            "question": fever_question,
            "alternate_questions": ["Fever during pregnancy"],
            "answer": fever_answer,
            "source_name": "Fever Information Source",
            "source_url": "https://example.org/pregnancy/fever",
            "is_warning_sign": True,
            "is_published": True,
        }
        abdominal_source = {
            "question": (
                "What should I do if I have severe abdominal pain during pregnancy?"
            ),
            "alternate_questions": ["Severe abdominal pain in pregnancy"],
            "answer": "Severe abdominal pain requires prompt medical assessment.",
            "source_name": "Abdominal Pain Source",
            "source_url": "https://example.org/pregnancy/abdominal-pain",
            "is_warning_sign": True,
            "is_published": True,
        }
        follow_ups = (
            "What should I do about it?",
            "What should I do now?",
            "Is that normal?",
            "What about the symptoms?",
        )

        with patch(
            "apps.core.services.pregnabot.DATASET_ENTRIES",
            [fever_source, abdominal_source],
        ):
            for follow_up in follow_ups:
                with self.subTest(follow_up=follow_up):
                    self._send(fever_question)
                    conversation = ChatConversation.objects.filter(
                        user=self.user,
                    ).latest("pk")
                    self._send(follow_up, conversation)

                    assistant = conversation.messages.filter(
                        role=ChatMessage.Role.ASSISTANT,
                    ).latest("pk")
                    self.assertEqual(assistant.answer_title, fever_question)
                    self.assertEqual(
                        assistant.content,
                        "A healthcare professional should assess a fever during pregnancy.",
                    )
                    self.assertNotIn("abdominal pain", assistant.content.casefold())
                    self.assertEqual(assistant.source_name, fever_source["source_name"])
                    self.assertEqual(assistant.source_url, fever_source["source_url"])

        self.assertEqual(generate.call_count, len(follow_ups) * 2)

    @patch(
        "apps.core.services.ai_provider.generate_response",
        side_effect=[
            "The library recommends prompt clinical assessment for pregnancy fever.",
            "Contact your healthcare professional promptly for individual advice.",
        ],
    )
    def test_fever_follow_up_what_should_i_do_now_uses_bundled_context(
        self,
        generate,
    ):
        records = self._bundled_dataset()
        fever = next(
            record
            for record in records
            if record["question"] == "What if I have a fever during pregnancy?"
        )

        with patch("apps.core.services.pregnabot.DATASET_ENTRIES", records):
            self._send(fever["question"])
            conversation = ChatConversation.objects.get(user=self.user)
            self._send("What should I do now?", conversation)

        assistant = conversation.messages.filter(
            role=ChatMessage.Role.ASSISTANT,
        ).latest("pk")
        self.assertEqual(assistant.answer_title, fever["question"])
        self.assertEqual(
            assistant.source_name, "Centers for Disease Control and Prevention"
        )
        self.assertEqual(
            assistant.source_url,
            "https://www.cdc.gov/hearher/maternal-warning-signs/index.html",
        )
        self.assertEqual(
            assistant.content,
            "Contact your healthcare professional promptly for individual advice.",
        )
        follow_up_prompt = generate.call_args_list[1].args[0][1]["content"]
        self.assertIn("Current question:\nWhat should I do now?", follow_up_prompt)
        self.assertIn(fever["question"], follow_up_prompt)
        self.assertIn(fever["answer"], follow_up_prompt)
        self.assertEqual(generate.call_count, 2)

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value=(
            "A balanced diet matters because its nutrients support your health "
            "and your baby's growth."
        ),
    )
    def test_nutrition_follow_ups_stay_with_the_latest_grounded_topic(self, generate):
        nutrition = self._faq(
            question="What foods are healthy during pregnancy?",
            answer=(
                "A balanced diet provides nutrients that support the pregnant "
                "person's health and the baby's growth."
            ),
            source_name="Nutrition Information Source",
            source_url="https://example.org/pregnancy/nutrition",
        )
        self._faq(
            question="Why is feeling tired during pregnancy important?",
            answer="Fatigue information unrelated to the nutrition question.",
            source_name="Fatigue Information Source",
            source_url="https://example.org/pregnancy/fatigue",
        )

        self._send(nutrition.question)
        conversation = ChatConversation.objects.get(user=self.user)
        follow_ups = (
            "Why is that important?",
            "Can you explain more?",
            "What should I do about it?",
            "Are there any risks?",
        )
        for follow_up in follow_ups:
            with self.subTest(follow_up=follow_up):
                self._send(follow_up, conversation)
                assistant = conversation.messages.filter(
                    role=ChatMessage.Role.ASSISTANT,
                ).latest("pk")
                self.assertEqual(assistant.content, generate.return_value)
                self.assertEqual(assistant.answer_title, nutrition.question)
                self.assertEqual(assistant.source_name, nutrition.source_name)
                self.assertEqual(assistant.source_url, nutrition.source_url)
                self.assertNotIn("Fatigue", assistant.content)

        self.assertEqual(generate.call_count, 1 + len(follow_ups))
        follow_up_prompt = generate.call_args_list[1].args[0][1]["content"]
        self.assertIn("Current question:\nWhy is that important?", follow_up_prompt)
        self.assertIn(
            "Relevant earlier question:\nWhat foods are healthy during pregnancy?",
            follow_up_prompt,
        )
        self.assertIn("Relevant earlier answer:", follow_up_prompt)
        self.assertIn(nutrition.answer, follow_up_prompt)
        self.assertIn("Published answer:\n" + nutrition.answer, follow_up_prompt)

    @patch(
        "apps.core.services.ai_provider.generate_response",
        side_effect=[
            "A balanced diet includes vegetables, fruits, whole grains, and lean proteins.",
            "Balanced nutrition supports the pregnant person's health and the baby's growth.",
            "Examples include vegetables, fruits, whole grains, lean proteins, and foods rich in calcium or iron.",
        ],
    )
    def test_examples_follow_up_stays_with_nutrition_topic(self, generate):
        nutrition = next(
            record
            for record in self._bundled_dataset()
            if record["question"] == "What foods are healthy during pregnancy?"
        )

        with patch(
            "apps.core.services.pregnabot.DATASET_ENTRIES",
            self._bundled_dataset(),
        ):
            self._send(nutrition["question"])
            conversation = ChatConversation.objects.get(user=self.user)
            self._send("Why is that important?", conversation)
            self._send("Can you give me example", conversation)

        assistant = conversation.messages.filter(
            role=ChatMessage.Role.ASSISTANT,
        ).latest("pk")
        self.assertEqual(assistant.answer_title, nutrition["question"])
        self.assertEqual(assistant.source_name, nutrition["source_name"])
        self.assertEqual(assistant.source_url, nutrition["source_url"])
        self.assertIn("whole grains", assistant.content)
        self.assertIn("calcium or iron", assistant.content)
        self.assertEqual(generate.call_count, 3)
        final_prompt = generate.call_args_list[-1].args[0][1]["content"]
        self.assertIn("Current question:\nCan you give me example", final_prompt)
        self.assertIn("Published answer:\n" + nutrition["answer"], final_prompt)

    @patch(
        "apps.core.services.ai_provider.generate_response",
        side_effect=[
            "A balanced diet includes vegetables and fruit.",
            "UNSUPPORTED_FOLLOW_UP",
        ],
    )
    def test_follow_up_without_supporting_information_asks_for_clarification(
        self,
        generate,
    ):
        faq = self._faq(
            question="What foods are healthy during pregnancy?",
            answer="A balanced diet includes vegetables and fruit.",
            source_name="Nutrition Information Source",
            source_url="https://example.org/pregnancy/nutrition",
        )

        self._send(faq.question)
        conversation = ChatConversation.objects.get(user=self.user)
        self._send("Why is that important?", conversation)

        assistant = conversation.messages.filter(
            role=ChatMessage.Role.ASSISTANT,
        ).latest("pk")
        self.assertIn(
            "couldn’t find published pregnancy information", assistant.content
        )
        self.assertIn("Could you clarify", assistant.content)
        self.assertFalse(assistant.source_name)
        self.assertFalse(assistant.source_url)
        self.assertNotEqual(assistant.content, faq.answer)
        self.assertEqual(generate.call_count, 2)

    @patch(
        "apps.core.services.ai_provider.generate_response",
        side_effect=[
            "A balanced diet provides nutrients for health.",
            "A balanced diet includes vegetables and fruit.",
        ],
    )
    def test_follow_up_does_not_repeat_the_published_answer_verbatim(self, generate):
        faq = self._faq(
            question="What foods are healthy during pregnancy?",
            answer="A balanced diet includes vegetables and fruit.",
            source_name="Nutrition Information Source",
            source_url="https://example.org/pregnancy/nutrition",
        )

        self._send(faq.question)
        conversation = ChatConversation.objects.get(user=self.user)
        self._send("Why is that important?", conversation)

        assistant = conversation.messages.filter(
            role=ChatMessage.Role.ASSISTANT,
        ).latest("pk")
        self.assertIn("Could you clarify", assistant.content)
        self.assertNotEqual(assistant.content, faq.answer)
        self.assertFalse(assistant.source_name)
        self.assertFalse(assistant.source_url)
        self.assertEqual(generate.call_count, 2)

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="A healthcare professional can assess a fever.",
    )
    def test_standalone_new_question_changes_topic_after_follow_up(self, generate):
        nutrition = self._faq(
            question="What foods are healthy during pregnancy?",
            answer="A balanced diet includes a range of nutritious foods.",
        )
        fever = self._faq(
            question="What should I do if I have a fever during pregnancy?",
            answer="Contact a healthcare professional about a fever during pregnancy.",
            source_name="Fever Information Source",
            source_url="https://example.org/pregnancy/fever",
        )
        self._send(nutrition.question)
        conversation = ChatConversation.objects.get(user=self.user)
        self._send("Why is that important?", conversation)

        self._send(fever.question, conversation)

        assistant = conversation.messages.filter(
            role=ChatMessage.Role.ASSISTANT,
        ).latest("pk")
        self.assertEqual(
            assistant.content,
            "A healthcare professional can assess a fever.",
        )
        self.assertEqual(assistant.answer_title, fever.question)
        self.assertEqual(assistant.source_name, fever.source_name)
        self.assertNotEqual(assistant.content, nutrition.answer)
        self.assertEqual(generate.call_count, 3)
        standalone_prompt = generate.call_args_list[-1].args[0][1]["content"]
        self.assertIn(f"Current question:\n{fever.question}", standalone_prompt)
        self.assertNotIn(nutrition.question, standalone_prompt)

    @patch("apps.core.services.ai_provider.generate_response")
    def test_contextual_question_without_prior_topic_asks_for_clarification(
        self,
        generate,
    ):
        self._send("What should I do about it?")

        assistant = ChatMessage.objects.get(
            conversation__user=self.user,
            role=ChatMessage.Role.ASSISTANT,
        )
        self.assertIn("Could you clarify", assistant.content)
        self.assertFalse(assistant.source_name)
        self.assertFalse(assistant.source_url)
        generate.assert_not_called()

    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="Unsupported response.",
    )
    def test_self_contained_question_does_not_send_unrelated_history(
        self,
        generate,
    ):
        self._faq()
        conversation = ChatConversation.objects.create(
            user=self.user,
            title="Long conversation",
        )
        for index in range(8):
            ChatMessage.objects.create(
                conversation=conversation,
                role=(
                    ChatMessage.Role.USER
                    if index % 2 == 0
                    else ChatMessage.Role.ASSISTANT
                ),
                content=f"history-{index}-" + ("x" * 1500),
            )

        self._send("Tell me about folate supplements", conversation)

        assistant = conversation.messages.filter(
            role=ChatMessage.Role.ASSISTANT,
        ).latest("pk")
        self.assertEqual(assistant.content, "Unsupported response.")
        generate.assert_called_once()
        provider_prompt = generate.call_args.args[0][1]["content"]
        self.assertNotIn("history-", provider_prompt)

    @patch("apps.core.services.ai_provider.generate_response")
    def test_urgent_warning_phrases_skip_provider_and_return_urgent_guidance(
        self,
        generate,
    ):
        warning_questions = (
            "I have heavy vaginal bleeding",
            "I have severe abdominal pain",
            "I am having difficulty breathing",
            "I can't breathe",
            "I had a seizure",
            "Dugo nga nagaguwa",
        )
        for question in warning_questions:
            with self.subTest(question=question):
                self._send(question)

        generate.assert_not_called()
        urgent_answers = ChatMessage.objects.filter(
            conversation__user=self.user,
            role=ChatMessage.Role.ASSISTANT,
        )
        self.assertEqual(urgent_answers.count(), len(warning_questions))
        for answer in urgent_answers:
            self.assertIn("urgent assessment", answer.content)
            self.assertIn("Do not wait", answer.content)

    def test_warning_rules_handle_clear_negation_and_uncertain_wording(self):
        self.assertTrue(is_urgent("I have heavy bleeding"))
        self.assertTrue(is_urgent("I can't breathe"))
        self.assertFalse(is_urgent("I do not have heavy bleeding"))
        self.assertTrue(is_urgent("I can't tell whether I have heavy bleeding"))
        self.assertFalse(is_urgent("I don't have heavy bleeding"))
        self.assertTrue(is_urgent("I am not sure whether this is heavy bleeding"))

    @patch("apps.core.services.ai_provider.generate_response")
    def test_unpublished_content_is_not_sent_or_used_as_fallback(self, generate):
        self._faq(
            question="What is cobalt moon orchid care?",
            answer="UNPUBLISHED-MEDICAL-CONTENT",
            is_published=False,
        )

        self._send("What is cobalt moon orchid care?")

        generate.assert_not_called()
        assistant = ChatMessage.objects.get(
            conversation__user=self.user,
            role=ChatMessage.Role.ASSISTANT,
        )
        self.assertNotIn("UNPUBLISHED-MEDICAL-CONTENT", assistant.content)
        self.assertIn(
            "could not find a sufficiently relevant answer", assistant.content
        )

    @patch("apps.core.services.ai_provider.generate_response")
    def test_no_retrieval_match_uses_existing_insufficient_information_fallback(
        self,
        generate,
    ):
        self._send("Where are cobalt moon orchids?")

        generate.assert_not_called()
        assistant = ChatMessage.objects.get(
            conversation__user=self.user,
            role=ChatMessage.Role.ASSISTANT,
        )
        self.assertIn(
            "could not find a sufficiently relevant answer", assistant.content
        )
        self.assertFalse(assistant.source_name)
        self.assertFalse(assistant.source_url)

    @patch(
        "apps.core.services.ai_provider.generate_response",
        side_effect=[
            ProviderError("private provider detail"),
            ProviderTimeout("private timeout detail"),
        ],
    )
    def test_provider_errors_and_timeouts_fall_back_to_published_answer(
        self,
        generate,
    ):
        faq = self._faq()
        for _ in range(2):
            response = self.client.post(
                reverse("chatbot"),
                {"question": "Tell me about folate supplements"},
                follow=True,
            )
            self.assertContains(response, "The published answer is shown instead.")
            self.assertNotContains(response, "private provider detail")
            self.assertNotContains(response, "private timeout detail")

        conversations = ChatConversation.objects.filter(user=self.user)
        self.assertEqual(conversations.count(), 2)
        for conversation in conversations:
            self.assertEqual(
                conversation.messages.filter(role=ChatMessage.Role.USER).count(),
                1,
            )
            assistant = conversation.messages.get(role=ChatMessage.Role.ASSISTANT)
            self.assertEqual(assistant.content, faq.answer)
            self.assertEqual(assistant.answer_title, faq.question)
            self.assertEqual(assistant.source_name, faq.source_name)
            self.assertEqual(assistant.source_url, faq.source_url)
        self.assertEqual(generate.call_count, 2)

    @override_settings(AI_PROVIDER="openai")
    @patch(
        "apps.core.services.ai_provider.generate_response",
        return_value="Generated by the configured OpenAI provider.",
    )
    def test_chatbot_uses_the_configured_openai_provider(self, generate):
        faq = self._faq()

        self._send("Tell me about folate supplements")

        assistant = ChatMessage.objects.get(
            conversation__user=self.user,
            role=ChatMessage.Role.ASSISTANT,
        )
        self.assertEqual(
            assistant.content,
            "Generated by the configured OpenAI provider.",
        )
        self.assertEqual(assistant.source_name, faq.source_name)
        self.assertEqual(assistant.source_url, faq.source_url)
        generate.assert_called_once()
