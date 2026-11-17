"""Django's /admin/ site is off unless DJANGO_ADMIN_ENABLED (default: DEBUG)."""

import importlib

import pytest
from django.urls import clear_url_caches

import continuity.urls


def _reload_urls():
    clear_url_caches()
    importlib.reload(continuity.urls)


@pytest.fixture(autouse=True)
def _restore_urls():
    yield
    _reload_urls()


@pytest.mark.django_db
def test_admin_site_disabled_returns_404(client, settings):
    settings.DJANGO_ADMIN_ENABLED = False
    _reload_urls()
    assert client.get("/admin/login/").status_code == 404


@pytest.mark.django_db
def test_admin_site_enabled_serves_login(client, settings):
    settings.DJANGO_ADMIN_ENABLED = True
    _reload_urls()
    assert client.get("/admin/login/").status_code == 200
