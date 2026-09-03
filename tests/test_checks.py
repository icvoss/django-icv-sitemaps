"""Tests for the icv_sitemaps.W001 system check (#34).

``ICV_SITEMAPS_BASE_URL`` is read inside the check function body, not at
module import time, so it responds to
``patch("icv_sitemaps.conf.ICV_SITEMAPS_BASE_URL", ...)`` the same way the
call sites in ``services/`` and ``views.py`` do. ``override_settings`` is a
silent no-op for this setting: see conf.py's module-level constant pattern.
"""

import inspect
from unittest.mock import patch

from django.core.checks.registry import registry

from icv_sitemaps.apps import IcvSitemapsConfig
from icv_sitemaps.checks import check_base_url_configured


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
