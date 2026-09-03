"""Tests for the icv_sitemaps.W001 system check (#34).

``ICV_SITEMAPS_BASE_URL`` is read inside the check function body, not at
module import time, so it responds to
``patch("icv_sitemaps.conf.ICV_SITEMAPS_BASE_URL", ...)`` the same way the
call sites in ``services/`` and ``views.py`` do. ``override_settings`` is a
silent no-op for this setting: see conf.py's module-level constant pattern.
"""

from unittest.mock import patch

from django.core.checks.registry import registry

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
        with patch("icv_sitemaps.conf.ICV_SITEMAPS_BASE_URL", ""):
            all_messages = registry.run_checks()

        ids = [m.id for m in all_messages]
        assert "icv_sitemaps.W001" in ids
