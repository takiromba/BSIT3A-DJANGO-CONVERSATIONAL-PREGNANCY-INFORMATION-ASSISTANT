from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ChatConversation, ChatMessage, FAQ, PregnancyTopic


class HomeViewTests(TestCase):
    def test_home_renders_for_authenticated_user(self):
        user = get_user_model().objects.create_user(username='admin', password='secret1234')

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pregnancy/dashboard.html')
        self.assertContains(response, 'Good morning')

    def test_home_requires_login(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 302)

    def test_logout_requires_post(self):
        user = get_user_model().objects.create_user(username='admin', password='secret1234')
        self.client.force_login(user)

        response = self.client.get(reverse('logout'))

        self.assertEqual(response.status_code, 405)

    def test_logout_post_ends_the_session(self):
        user = get_user_model().objects.create_user(username='admin', password='secret1234')
        self.client.force_login(user)

        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_dashboard_uses_only_the_current_users_chat_statistics(self):
        user = get_user_model().objects.create_user(
            username='pregnant-user',
            password='secret1234',
        )
        other = get_user_model().objects.create_user(
            username='another-user',
            password='secret1234',
        )
        for owner in (user, other):
            conversation = ChatConversation.objects.create(
                user=owner,
                title='A question',
            )
            ChatMessage.objects.create(
                conversation=conversation,
                role=ChatMessage.Role.USER,
                content='How can I stay hydrated?',
            )

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, '<strong>1</strong>', html=False)
        self.assertEqual(response.context['question_count'], 1)
        self.assertEqual(len(response.context['recent_conversations']), 1)


class PregnancyInformationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='reader',
            password='secret1234',
        )
        self.client.force_login(self.user)

    def test_information_search_filters_published_topics(self):
        topic = PregnancyTopic.objects.create(
            title='Nutrition basics',
            slug='nutrition-basics-test',
            category=PregnancyTopic.Category.NUTRITION,
            description='Simple food guidance.',
            content='Choose a balanced diet.',
        )
        PregnancyTopic.objects.create(
            title='Prenatal visits',
            slug='prenatal-visits-test',
            category=PregnancyTopic.Category.PRENATAL,
            description='Prepare for appointments.',
            content='Talk with your provider.',
        )
        PregnancyTopic.objects.create(
            title='Hidden topic',
            slug='hidden-topic-test',
            category=PregnancyTopic.Category.NUTRITION,
            description='Not published.',
            content='Hidden content.',
            is_published=False,
        )

        response = self.client.get(reverse('pregnancy_information'), {'q': 'balanced'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, topic.title)
        self.assertNotContains(response, 'Prenatal visits')
        self.assertNotContains(response, 'Hidden topic')

    def test_topic_categories_are_filterable(self):
        topic = PregnancyTopic.objects.create(
            title='Care test',
            slug='care-test',
            category=PregnancyTopic.Category.PRENATAL,
            description='Checkups and care.',
            content='Ask questions.',
        )

        response = self.client.get(
            reverse('pregnancy_information'),
            {'category': PregnancyTopic.Category.PRENATAL},
        )

        self.assertContains(response, topic.title)
        self.assertEqual(response.context['topic_count'], 2)

    def test_topic_detail_renders_published_content(self):
        topic = PregnancyTopic.objects.create(
            title='A helpful topic',
            slug='helpful-topic-test',
            category=PregnancyTopic.Category.CONCERNS,
            description='A short introduction.',
            content='Discuss personal questions with your care team.',
        )

        response = self.client.get(reverse('topic_detail', args=[topic.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, topic.content)

    def test_faq_search_returns_matching_published_answers(self):
        faq = FAQ.objects.create(
            question='How should I prepare for visits?',
            answer='Write down questions for your provider.',
        )
        response = self.client.get(reverse('faq_list'), {'q': 'provider'})

        self.assertContains(response, faq.question)


class ChatbotTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='chat-user',
            password='secret1234',
        )
        self.client.force_login(self.user)

    def test_question_creates_private_conversation_and_library_answer(self):
        response = self.client.post(
            reverse('chatbot'),
            {'question': 'What vitamins and supplements should I take?'},
        )

        conversation = ChatConversation.objects.get(user=self.user)
        messages = list(conversation.messages.all())
        self.assertRedirects(
            response,
            reverse('chat_conversation', args=[conversation.pk]),
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, ChatMessage.Role.USER)
        self.assertEqual(messages[1].role, ChatMessage.Role.ASSISTANT)
        self.assertIn('Supplement needs vary', messages[1].content)

    def test_urgent_symptom_gets_immediate_care_message(self):
        response = self.client.post(
            reverse('chatbot'),
            {'question': 'I have heavy bleeding and feel faint'},
        )

        conversation = ChatConversation.objects.get(user=self.user)
        reply = conversation.messages.get(role=ChatMessage.Role.ASSISTANT)
        self.assertRedirects(
            response,
            reverse('chat_conversation', args=[conversation.pk]),
        )
        self.assertIn('urgent assessment', reply.content)
        self.assertIn('Do not wait', reply.content)

    def test_user_cannot_open_another_users_conversation(self):
        other = get_user_model().objects.create_user(
            username='other-chat-user',
            password='secret1234',
        )
        conversation = ChatConversation.objects.create(
            user=other,
            title='Private conversation',
        )

        response = self.client.get(
            reverse('chat_conversation', args=[conversation.pk]),
        )

        self.assertEqual(response.status_code, 404)


class ProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='profile-user',
            password='secret1234',
            email='before@example.com',
        )
        self.client.force_login(self.user)

    def test_profile_updates_current_user_and_uses_success_message(self):
        response = self.client.post(
            reverse('profile'),
            {
                'first_name': 'Taylor',
                'last_name': 'Jones',
                'email': 'taylor@example.com',
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertRedirects(response, reverse('profile'))
        self.assertEqual(self.user.first_name, 'Taylor')
        self.assertEqual(self.user.last_name, 'Jones')
        self.assertEqual(self.user.email, 'taylor@example.com')
        self.assertContains(response, 'Your profile has been updated.')

    def test_profile_rejects_an_invalid_email(self):
        response = self.client.post(
            reverse('profile'),
            {
                'first_name': 'Taylor',
                'last_name': 'Jones',
                'email': 'not-an-email',
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user.email, 'before@example.com')
        self.assertContains(response, 'Please enter a valid email address.')
