from django.urls import path

from . import views

app_name = "assistant"

urlpatterns = [
    path("chat/", views.ChatView.as_view(), name="chat"),
    path("cancel/", views.CancelView.as_view(), name="cancel"),
    path("conversations/", views.ConversationsView.as_view(), name="conversations"),
    path(
        "conversations/<uuid:conv_id>/messages/",
        views.ConversationMessagesView.as_view(),
        name="conversation_messages",
    ),
    path("usage/", views.UsageView.as_view(), name="usage"),
]
