from django.db import migrations


TOPICS = [
    {
        'title': 'Common Pregnancy Symptoms',
        'slug': 'common-pregnancy-symptoms',
        'category': 'symptoms',
        'description': 'Understand common changes and when to ask your care team for help.',
        'icon': 'fa-person-circle-question',
        'position': 1,
        'content': (
            'Pregnancy can bring changes such as nausea, tiredness, breast '
            'tenderness, and changes in appetite. Experiences differ from '
            'person to person, and symptoms may change over time.\n\n'
            'Mention new, persistent, or worrying symptoms at your prenatal '
            'appointments. A healthcare professional can help you understand '
            'what is expected for you and discuss options for relief. Seek '
            'urgent care for severe symptoms or warning signs.'
        ),
    },
    {
        'title': 'Nutrition & Healthy Practices',
        'slug': 'nutrition-and-healthy-practices',
        'category': 'nutrition',
        'description': 'Everyday ways to support your wellbeing during pregnancy.',
        'icon': 'fa-apple-whole',
        'position': 2,
        'content': (
            'Aim for a varied, balanced eating pattern and drink fluids '
            'regularly. Your nutritional needs are personal; ask your '
            'healthcare professional which foods, prenatal vitamins, and '
            'supplements are right for you.\n\n'
            'Check with your care team before starting or stopping a '
            'supplement, medicine, or major diet change. If nausea or another '
            'symptom makes eating or drinking difficult, let them know.'
        ),
    },
    {
        'title': 'Prenatal Care',
        'slug': 'prenatal-care',
        'category': 'prenatal',
        'description': 'Prepare for checkups, screening discussions, and questions for your provider.',
        'icon': 'fa-kit-medical',
        'position': 3,
        'content': (
            'Prenatal visits give you and your care team time to discuss your '
            'health, questions, and the care that may be recommended for you. '
            'The timing and content of appointments can vary based on your '
            'needs and local guidance.\n\n'
            'Keep a note of questions, medicines, and symptoms you would like '
            'to discuss. Ask your provider which screenings or tests are '
            'available, what they involve, and when to seek help between visits.'
        ),
    },
    {
        'title': 'Stages & Fetal Development',
        'slug': 'stages-and-fetal-development',
        'category': 'development',
        'description': 'Learn how pregnancy is commonly described in stages and milestones.',
        'icon': 'fa-baby',
        'position': 4,
        'content': (
            'Pregnancy is often described in three trimesters, but development '
            'and individual experiences do not follow an identical schedule. '
            'Your care team can explain how pregnancy is dated and what a '
            'particular checkup or scan may tell you.\n\n'
            'Milestone information is a general guide, not a way to diagnose '
            'your pregnancy. Ask your provider to interpret findings in the '
            'context of your own health and pregnancy.'
        ),
    },
    {
        'title': 'Common Pregnancy Concerns',
        'slug': 'common-pregnancy-concerns',
        'category': 'concerns',
        'description': 'Find a supportive starting point for questions about pregnancy and wellbeing.',
        'icon': 'fa-heart',
        'position': 5,
        'content': (
            'It is normal to have questions about physical changes, sleep, '
            'mood, work, travel, or medicines. What is appropriate can depend '
            'on your health and stage of pregnancy, so bring personal '
            'concerns to your healthcare professional.\n\n'
            'Do not start or stop prescribed medicine based only on general '
            'information. If you feel overwhelmed or unsafe, contact someone '
            'you trust and reach out to a qualified professional.'
        ),
    },
    {
        'title': 'Warning Signs',
        'slug': 'warning-signs',
        'category': 'warning-signs',
        'description': 'Know when symptoms call for prompt or emergency medical attention.',
        'icon': 'fa-triangle-exclamation',
        'position': 6,
        'content': (
            'Get urgent medical help for severe symptoms such as heavy '
            'bleeding, severe abdominal pain, chest pain, difficulty breathing, '
            'a seizure, or fainting. Contact your maternity-care team promptly '
            'if you are concerned about a change in your pregnancy, including '
            'reduced fetal movement when you have been advised to monitor it.\n\n'
            'Warning signs and recommended actions can vary. If symptoms feel '
            'severe, you feel unsafe, or you cannot reach your care team, '
            'contact local emergency services. Do not wait for a chatbot '
            'response in an urgent situation.'
        ),
    },
]

FAQS = [
    {
        'question': 'Are pregnancy symptoms the same for everyone?',
        'answer': (
            'No. Symptoms and their timing vary from person to person. Ask your '
            'healthcare professional about symptoms that are new, persistent, '
            'or worrying to you.'
        ),
        'topic': 'common-pregnancy-symptoms',
        'position': 1,
    },
    {
        'question': 'Which vitamins or supplements should I take?',
        'answer': (
            'Supplement needs vary. Ask your healthcare professional which '
            'prenatal vitamins or supplements are suitable for you, and check '
            'with them before starting or stopping a product.'
        ),
        'topic': 'nutrition-and-healthy-practices',
        'position': 2,
    },
    {
        'question': 'What should I ask at a prenatal appointment?',
        'answer': (
            'You can bring questions about symptoms, medicines, screenings, '
            'nutrition, and what to do between visits. Your care team can '
            'explain which recommendations fit your personal needs.'
        ),
        'topic': 'prenatal-care',
        'position': 3,
    },
    {
        'question': 'Can I use general milestone information to assess my pregnancy?',
        'answer': (
            'No. Milestones are general educational guides and cannot assess '
            'an individual pregnancy. Ask your healthcare professional to '
            'interpret your checkups and any test results.'
        ),
        'topic': 'stages-and-fetal-development',
        'position': 4,
    },
    {
        'question': 'Should I stop a medicine when I find out I am pregnant?',
        'answer': (
            'Do not start or stop a prescribed medicine based only on general '
            'information. Contact the healthcare professional who prescribed '
            'it or your maternity-care team for advice specific to you.'
        ),
        'topic': 'common-pregnancy-concerns',
        'position': 5,
    },
    {
        'question': 'What should I do if I have a severe warning sign?',
        'answer': (
            'Seek urgent medical help for severe symptoms such as heavy '
            'bleeding, severe pain, chest pain, difficulty breathing, seizure, '
            'or fainting. Contact your maternity-care team or local emergency '
            'services now; do not wait for an online response.'
        ),
        'topic': 'warning-signs',
        'position': 6,
    },
]


def seed_library(apps, schema_editor):
    PregnancyTopic = apps.get_model('core', 'PregnancyTopic')
    FAQ = apps.get_model('core', 'FAQ')
    topics = {}

    for values in TOPICS:
        topic, _created = PregnancyTopic.objects.get_or_create(
            slug=values['slug'],
            defaults=values,
        )
        topics[values['slug']] = topic

    for values in FAQS:
        faq_values = values.copy()
        topic_slug = faq_values.pop('topic')
        FAQ.objects.get_or_create(
            question=faq_values['question'],
            defaults={**faq_values, 'topic_id': topics[topic_slug].pk},
        )


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_library, migrations.RunPython.noop),
    ]
