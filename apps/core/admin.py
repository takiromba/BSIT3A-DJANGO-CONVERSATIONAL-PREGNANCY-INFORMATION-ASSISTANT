from django.contrib import admin

from .models import ChatConversation, ChatMessage, FAQ, PregnancyTopic


@admin.register(PregnancyTopic)
class PregnancyTopicAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'is_published', 'position', 'updated_at')
    list_filter = ('category', 'is_published')
    search_fields = ('title', 'description', 'content')
    prepopulated_fields = {'slug': ('title',)}
    ordering = ('position', 'title')


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ('question', 'topic', 'is_published', 'position')
    list_filter = ('is_published', 'topic')
    search_fields = ('question', 'answer')
    ordering = ('position', 'question')


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ('role', 'content', 'created_at')
    can_delete = False


@admin.register(ChatConversation)
class ChatConversationAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'created_at', 'updated_at')
    list_filter = ('created_at',)
    search_fields = ('title', 'user__username', 'user__email')
    readonly_fields = ('user', 'title', 'created_at', 'updated_at')
    inlines = (ChatMessageInline,)
