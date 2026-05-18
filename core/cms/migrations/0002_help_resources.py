# Generated for HelpCategory + HelpResource models

import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cms', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='HelpCategory',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('slug', models.SlugField(max_length=80, unique=True)),
                ('name', models.CharField(max_length=120)),
                ('description', models.TextField(blank=True, default='')),
                ('icon', models.CharField(blank=True, default='', max_length=40)),
                ('order', models.IntegerField(default=0)),
                ('locale', models.CharField(db_index=True, default='es', max_length=8)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Help category',
                'verbose_name_plural': 'Help categories',
                'ordering': ['order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='HelpResource',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('slug', models.SlugField(max_length=160, unique=True)),
                ('title', models.CharField(max_length=255)),
                ('excerpt', models.TextField(blank=True, default='')),
                ('content_json', models.JSONField(blank=True, default=dict)),
                ('content_html', models.TextField(blank=True, default='')),
                ('cover_image_url', models.URLField(blank=True, default='')),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('published', 'Published'), ('archived', 'Archived')], db_index=True, default='draft', max_length=16)),
                ('published_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('author_user_id', models.UUIDField()),
                ('tags', models.JSONField(blank=True, default=list)),
                ('seo_title', models.CharField(blank=True, default='', max_length=255)),
                ('seo_description', models.CharField(blank=True, default='', max_length=320)),
                ('locale', models.CharField(db_index=True, default='es', max_length=8)),
                ('order', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='resources', to='cms.helpcategory')),
            ],
            options={
                'ordering': ['category__order', 'order', '-published_at'],
                'indexes': [models.Index(fields=['status', 'locale', 'category'], name='cms_helpres_status_a1c2b3_idx')],
            },
        ),
    ]
