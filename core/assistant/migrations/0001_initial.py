import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AccountProfile",
            fields=[
                ("user_id", models.UUIDField(primary_key=True, serialize=False)),
                (
                    "plan",
                    models.CharField(
                        choices=[("free", "Free"), ("pro", "Pro"), ("admin", "Admin")],
                        default="free",
                        max_length=16,
                    ),
                ),
                ("plan_renews_at", models.DateTimeField(blank=True, null=True)),
                ("stripe_customer_id", models.CharField(blank=True, default="", max_length=255)),
                ("stripe_subscription_id", models.CharField(blank=True, default="", max_length=255)),
                ("context_version", models.IntegerField(default=0)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="Conversation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("user_id", models.UUIDField(db_index=True)),
                ("title", models.CharField(blank=True, default="", max_length=255)),
                ("archived", models.BooleanField(default=False)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.AddIndex(
            model_name="conversation",
            index=models.Index(
                fields=["user_id", "-updated_at"], name="assistant_c_user_id_idx"
            ),
        ),
        migrations.CreateModel(
            name="Message",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="messages",
                        to="assistant.conversation",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("user", "User"),
                            ("assistant", "Assistant"),
                            ("tool", "Tool"),
                        ],
                        max_length=16,
                    ),
                ),
                ("content", models.JSONField()),
                ("model", models.CharField(blank=True, default="", max_length=64)),
                ("stop_reason", models.CharField(blank=True, default="", max_length=32)),
                ("tokens_in", models.IntegerField(default=0)),
                ("tokens_out", models.IntegerField(default=0)),
                ("cache_read_in", models.IntegerField(default=0)),
                ("cache_creation_in", models.IntegerField(default=0)),
                ("created", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["created"],
            },
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(
                fields=["conversation", "created"], name="assistant_m_conv_idx"
            ),
        ),
        migrations.CreateModel(
            name="UsageDay",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("user_id", models.UUIDField()),
                ("date", models.DateField()),
                ("messages_sent", models.IntegerField(default=0)),
                ("tokens_in", models.IntegerField(default=0)),
                ("tokens_out", models.IntegerField(default=0)),
                ("cache_read_in", models.IntegerField(default=0)),
                ("cost_usd_cents", models.IntegerField(default=0)),
            ],
        ),
        migrations.AddConstraint(
            model_name="usageday",
            constraint=models.UniqueConstraint(
                fields=("user_id", "date"), name="unique_usage_per_user_per_day"
            ),
        ),
        migrations.AddIndex(
            model_name="usageday",
            index=models.Index(fields=["user_id", "-date"], name="assistant_u_user_id_idx"),
        ),
    ]
