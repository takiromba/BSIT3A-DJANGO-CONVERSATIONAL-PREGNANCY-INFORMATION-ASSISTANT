from django.urls import path

from . import accounts, chatbot, content, dashboard, prenatal

urlpatterns = [
    path("", accounts.login_view, name="login"),
    path("home/", dashboard.home, name="dashboard"),
    path("chat/", chatbot.chatbot, name="chatbot"),
    path("chat/<int:conversation_id>/", chatbot.chatbot, name="chat_conversation"),
    path(
        "chat/<int:conversation_id>/rename/",
        chatbot.rename_conversation,
        name="chat_rename",
    ),
    path(
        "chat/<int:conversation_id>/delete/",
        chatbot.delete_conversation,
        name="chat_delete",
    ),
    path(
        "chat/<int:conversation_id>/export/",
        chatbot.export_conversation,
        name="chat_export",
    ),
    path(
        "chat/message/<int:message_id>/feedback/",
        chatbot.message_feedback,
        name="chat_feedback",
    ),
    path("feedback/", chatbot.feedback_analytics, name="feedback_analytics"),
    path(
        "pregnancy-info/", content.pregnancy_information, name="pregnancy_information"
    ),
    path("pregnancy-info/<slug:slug>/", content.topic_detail, name="topic_detail"),
    path("faqs/", content.faq_list, name="faq_list"),
    path("profile/", accounts.profile, name="profile"),
    path("pregnancy-profile/", prenatal.pregnancy_profile, name="pregnancy_profile"),
    path(
        "pregnancy-profile/appointments/<int:appointment_id>/delete/",
        prenatal.delete_appointment,
        name="appointment_delete",
    ),
    path("bookmarks/", prenatal.bookmarks, name="bookmarks"),
    path(
        "bookmarks/<int:topic_id>/toggle/",
        prenatal.toggle_bookmark,
        name="bookmark_toggle",
    ),
    path("logout/", accounts.logout_view, name="logout"),
    path("register/", accounts.register_view, name="register"),
]
