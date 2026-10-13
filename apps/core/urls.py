from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('home/', views.home, name='dashboard'),
    path('chat/', views.chatbot, name='chatbot'),
    path('chat/<int:conversation_id>/', views.chatbot, name='chat_conversation'),
    path('pregnancy-info/', views.pregnancy_information, name='pregnancy_information'),
    path('pregnancy-info/<slug:slug>/', views.topic_detail, name='topic_detail'),
    path('faqs/', views.faq_list, name='faq_list'),
    path('profile/', views.profile, name='profile'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
]