"""Compatibility exports for callers using the former monolithic views module."""

from .accounts import login_view, logout_view, pregnancy_profile, profile, register_view
from .chatbot import (
    chatbot,
    delete_conversation,
    export_conversation,
    feedback_analytics,
    message_feedback,
    rename_conversation,
)
from .content import faq_list, pregnancy_information, topic_detail
from .dashboard import home
from .preferences import settings_view
from .prenatal import bookmarks, toggle_bookmark

__all__ = [
    "bookmarks",
    "chatbot",
    "delete_conversation",
    "export_conversation",
    "faq_list",
    "feedback_analytics",
    "home",
    "login_view",
    "logout_view",
    "message_feedback",
    "pregnancy_information",
    "pregnancy_profile",
    "profile",
    "register_view",
    "rename_conversation",
    "settings_view",
    "toggle_bookmark",
    "topic_detail",
]
