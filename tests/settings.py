"""
Django settings for icv-sitemaps tests.

Minimal configuration — no migration modules so syncdb creates tables directly.
"""

import os

SECRET_KEY = "icv-sitemaps-test-secret-key"  # noqa: S105

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "icv_sitemaps",
    "sitemaps_testapp",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

MIGRATION_MODULES = {
    "icv_sitemaps": None,
    "sitemaps_testapp": None,
    "contenttypes": None,
    "auth": None,
    "admin": None,
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

USE_TZ = True
TIME_ZONE = "UTC"

ROOT_URLCONF = "icv_sitemaps.urls"

# Storage: use in-memory / temp for tests
DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"

# icv-sitemaps settings
ICV_SITEMAPS_BASE_URL = "https://example.com"
ICV_SITEMAPS_ASYNC_GENERATION = False  # Never kick off Celery in unit tests
ICV_SITEMAPS_PING_ENABLED = False  # Never hit real search engines in tests
ICV_SITEMAPS_GZIP = False  # Simpler storage assertions
ICV_SITEMAPS_CACHE_TIMEOUT = 0  # No caching in tests

if os.environ.get("ICV_SITEMAPS_TEST_AUTH_OVERRIDE"):
    # Exercised by tests/test_models.py in a subprocess: proves the user FK
    # follows ICV_AUTH_USER_MODEL rather than AUTH_USER_MODEL (ADR-037).
    ICV_AUTH_USER_MODEL = os.environ["ICV_SITEMAPS_TEST_AUTH_OVERRIDE"]

if os.environ.get("ICV_SITEMAPS_TEST_TENANT_OVERRIDE"):
    # Exercised by tests/test_tenant_fk.py in a subprocess: proves the
    # tenant_ref FK follows ICV_TENANT_MODEL rather than the auth.Group
    # floor (issue #50).
    ICV_TENANT_MODEL = os.environ["ICV_SITEMAPS_TEST_TENANT_OVERRIDE"]
