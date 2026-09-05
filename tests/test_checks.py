"""Tests for icv_sitemaps system checks (#34, #50).

``ICV_SITEMAPS_BASE_URL`` is read inside the check function body, not at
module import time, so it responds to
``patch("icv_sitemaps.conf.ICV_SITEMAPS_BASE_URL", ...)`` the same way the
call sites in ``services/`` and ``views.py`` do. ``override_settings`` is a
silent no-op for this setting: see conf.py's module-level constant pattern.
"""

import inspect
from unittest.mock import patch

from django.conf import settings as django_settings
from django.core.checks.registry import registry

from icv_sitemaps.apps import IcvSitemapsConfig
from icv_sitemaps.checks import check_base_url_configured, check_tenant_model


class TestCheckBaseUrlConfigured:
    def test_warns_when_base_url_empty(self):
        with patch("icv_sitemaps.conf.ICV_SITEMAPS_BASE_URL", ""):
            messages = check_base_url_configured(None)

        assert len(messages) == 1
        message = messages[0]
        assert message.id == "icv_sitemaps.W001"
        assert message.level == 30  # logging.WARNING; must not be an Error
        assert "ICV_SITEMAPS_BASE_URL" in message.msg
        assert "<loc>" in message.hint
        assert "https://example.com" in message.hint

    def test_no_warning_when_base_url_set(self):
        with patch("icv_sitemaps.conf.ICV_SITEMAPS_BASE_URL", "https://example.com"):
            messages = check_base_url_configured(None)

        assert messages == []

    def test_check_is_registered(self):
        """The check must actually run on manage.py check, not just exist."""
        assert check_base_url_configured in registry.registered_checks

    def test_registered_check_fires_through_the_registry(self):
        """The check is registered, and firing it through the registry yields W001.

        Runs only this package's own registered checks rather than
        ``registry.run_checks()``, which executes every check in the project.
        On Django 6.1 that set includes database-backed checks, so the
        unqualified call trips pytest-django's database guard and fails for a
        reason that has nothing to do with this check. Resolving the callable
        out of the registry still proves registration, which a direct call to
        ``check_base_url_configured`` would not.
        """
        registered = [
            check
            for check in registry.get_checks(include_deployment_checks=False)
            if getattr(check, "__module__", "").startswith("icv_sitemaps")
        ]
        assert registered, "no icv_sitemaps check is registered with Django's check framework"

        # Registration must come from IcvSitemapsConfig.ready(), not merely from
        # this module importing icv_sitemaps.checks. Importing the module runs
        # the @register() decorator either way, so without this the assertion
        # above passes even when apps.py never wires the checks up, which is
        # the only thing that makes them run in a real project.
        ready_source = inspect.getsource(IcvSitemapsConfig.ready)
        assert "checks" in ready_source, "IcvSitemapsConfig.ready() does not import the checks module"

        with patch("icv_sitemaps.conf.ICV_SITEMAPS_BASE_URL", ""):
            ids = [message.id for check in registered for message in check(app_configs=None)]

        assert "icv_sitemaps.W001" in ids


class TestCheckTenantModel:
    """Tests for icv_sitemaps.W003 and icv_sitemaps.E001 (issue #50).

    Mirrors icv_email.checks' equivalent W001/E001 pair. ``conf`` is read
    inside the check function body, so both ``icv_sitemaps.conf.ICV_TENANT_MODEL``
    (the module-level constant used for the floor comparison) and
    ``django.conf.settings.ICV_TENANT_MODEL`` (the raw project setting, used
    to decide whether the floor is "active" vs. "explicitly chosen") are
    exercised directly, matching how the check itself reads them.
    """

    def test_warns_when_floor_is_active_and_settings_has_no_override(self):
        """The test settings module never sets ICV_TENANT_MODEL, so no explicit
        removal is needed; only the module-level conf constant is patched."""
        assert not hasattr(django_settings, "ICV_TENANT_MODEL")

        with patch("icv_sitemaps.conf.ICV_TENANT_MODEL", "auth.Group"):
            messages = check_tenant_model(None)

        warning_ids = [m.id for m in messages]
        assert "icv_sitemaps.W003" in warning_ids
        message = next(m for m in messages if m.id == "icv_sitemaps.W003")
        assert message.level == 30  # logging.WARNING; must not be an Error
        assert "ICV_TENANT_MODEL" in message.msg
        assert "auth.Group" in message.hint

    def test_no_warning_when_settings_explicitly_chooses_the_floor_value(self):
        with (
            patch("icv_sitemaps.conf.ICV_TENANT_MODEL", "auth.Group"),
            patch.object(django_settings, "ICV_TENANT_MODEL", "auth.Group", create=True),
        ):
            messages = check_tenant_model(None)

        warning_ids = [m.id for m in messages]
        assert "icv_sitemaps.W003" not in warning_ids

    def test_no_warning_when_a_real_tenant_model_is_configured(self):
        with (
            patch("icv_sitemaps.conf.ICV_TENANT_MODEL", "sitemaps_testapp.Tenant"),
            patch.object(django_settings, "ICV_TENANT_MODEL", "sitemaps_testapp.Tenant", create=True),
        ):
            messages = check_tenant_model(None)

        assert messages == []

    def test_errors_when_tenant_model_cannot_resolve(self):
        with patch("icv_sitemaps.conf.ICV_TENANT_MODEL", "nonexistent.Model"):
            messages = check_tenant_model(None)

        error_ids = [m.id for m in messages]
        assert "icv_sitemaps.E001" in error_ids
        message = next(m for m in messages if m.id == "icv_sitemaps.E001")
        assert message.level == 40  # logging.ERROR
        assert "nonexistent.Model" in message.hint

    def test_check_is_registered(self):
        assert check_tenant_model in registry.registered_checks
