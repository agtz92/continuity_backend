from django.urls import path

from . import views

app_name = "assistant"

urlpatterns = [
    path("chat/", views.ChatView.as_view(), name="chat"),
    # The `canned` tier's chat: a catalogue and a runner, no streaming.
    path("actions/", views.ActionsView.as_view(), name="actions"),
    path(
        "actions/<str:action_id>/",
        views.RunActionView.as_view(),
        name="run_action",
    ),
    path("cancel/", views.CancelView.as_view(), name="cancel"),
    path(
        "parse-capture/",
        views.ParseCaptureView.as_view(),
        name="parse_capture",
    ),
    path("conversations/", views.ConversationsView.as_view(), name="conversations"),
    path(
        "conversations/<uuid:conv_id>/messages/",
        views.ConversationMessagesView.as_view(),
        name="conversation_messages",
    ),
    path("usage/", views.UsageView.as_view(), name="usage"),
    path("healthz/", views.HealthView.as_view(), name="healthz"),
]
