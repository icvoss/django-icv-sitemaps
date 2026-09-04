"""Unit tests for the icv_sitemaps.cache fail-open wrappers (#9, #51/ADR-037)."""

import logging
from unittest.mock import patch

from django.core.cache import cache, caches

from icv_sitemaps.cache import safe_delete, safe_get, safe_set


class TestSafeGet:
    def test_returns_cached_value_on_success(self, db):
        cache.set("k", "v", 3600)
        assert safe_get("k") == "v"

    def test_returns_default_when_backend_raises(self, db):
        with patch.object(cache, "get", side_effect=ConnectionError("redis down")):
            assert safe_get("k") is None
            assert safe_get("k", default="fallback") == "fallback"

    def test_logs_at_exception_level_on_failure(self, db, caplog):
        with (
            caplog.at_level(logging.ERROR, logger="icv_sitemaps.cache"),
            patch.object(cache, "get", side_effect=ConnectionError("redis down")),
        ):
            safe_get("my-key")

        assert any("my-key" in record.message for record in caplog.records)


class TestSafeSet:
    def test_sets_value_on_success(self, db):
        safe_set("k", "v", 3600)
        assert cache.get("k") == "v"

    def test_does_not_raise_when_backend_raises(self, db):
        with patch.object(cache, "set", side_effect=ConnectionError("redis down")):
            safe_set("k", "v", 3600)  # must not raise


class TestSafeDelete:
    def test_deletes_key_on_success(self, db):
        cache.set("k", "v", 3600)
        safe_delete("k")
        assert cache.get("k") is None

    def test_does_not_raise_when_backend_raises(self, db):
        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            safe_delete("k")  # must not raise

    def test_logs_at_warning_level_not_debug_on_failure(self, db, caplog):
        """A failed delete leaves stale content cached, which is a
        correctness problem, not a performance one: it must be visible at
        WARNING (or above), not buried at DEBUG.
        """
        with (
            caplog.at_level(logging.WARNING, logger="icv_sitemaps.cache"),
            patch.object(cache, "delete", side_effect=ConnectionError("redis down")),
        ):
            safe_delete("stale-key")

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("stale-key" in record.message for record in warning_records)


def _configure_two_caches(settings):
    """Configure a "default" and an "icv" CACHES alias, each its own LocMem instance.

    Django resets the ``caches`` connection handler when ``CACHES`` changes,
    so setting it via the pytest-django ``settings`` fixture is sufficient.
    LOCATION must differ between the two: LocMemCache backends sharing a
    LOCATION share the same underlying store.
    """
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "icv-sitemaps-test-default",
        },
        "icv": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "icv-sitemaps-test-icv",
        },
    }


class TestCachesAlias:
    def test_safe_set_writes_to_the_configured_alias_only(self, db, settings):
        _configure_two_caches(settings)

        with patch("icv_sitemaps.conf.ICV_CACHES_ALIAS", "icv"):
            safe_set("k", "v", 60)

        assert caches["icv"].get("k") == "v", "CACHE WRITE WENT TO THE DEFAULT ALIAS"
        assert caches["default"].get("k") is None, "CACHE WRITE WENT TO THE DEFAULT ALIAS"

    def test_safe_get_reads_from_the_configured_alias(self, db, settings):
        _configure_two_caches(settings)
        caches["icv"].set("k", "from-icv", 60)

        with patch("icv_sitemaps.conf.ICV_CACHES_ALIAS", "icv"):
            assert safe_get("k") == "from-icv"

    def test_safe_delete_removes_from_the_configured_alias(self, db, settings):
        _configure_two_caches(settings)
        caches["icv"].set("k", "v", 60)
        caches["default"].set("k", "v", 60)

        with patch("icv_sitemaps.conf.ICV_CACHES_ALIAS", "icv"):
            safe_delete("k")

        assert caches["icv"].get("k") is None
        assert caches["default"].get("k") == "v", "DELETE REMOVED FROM THE DEFAULT ALIAS INSTEAD OF THE OVERRIDE"
