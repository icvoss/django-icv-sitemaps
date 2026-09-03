"""Tests for the signal handlers in ``icv_sitemaps.handlers`` (#9).

Every handler here invalidates a cache key via ``icv_sitemaps.cache.safe_delete``
rather than calling ``django.core.cache.cache.delete`` directly, so that an
unreachable cache backend cannot turn a model save or delete into a 500 in
the admin (or in any other consumer write path). These tests prove the
model-level write still succeeds when the cache backend raises on delete,
which is the worst of the 26 call sites the audit for #9 found: an
unreachable Redis previously meant *saving* a RobotsRule, AdsEntry,
DiscoveryFileConfig or RedirectRule would raise.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache

from icv_sitemaps.testing.factories import (
    AdsEntryFactory,
    DiscoveryFileConfigFactory,
    RedirectRuleFactory,
    RobotsRuleFactory,
)


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


class TestRobotsRuleSignalsSurviveCacheFailure:
    def test_save_succeeds_when_cache_delete_raises(self, db):
        rule = RobotsRuleFactory()

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            rule.path = "/changed/"
            rule.save()

        rule.refresh_from_db()
        assert rule.path == "/changed/"

    def test_delete_succeeds_when_cache_delete_raises(self, db):
        rule = RobotsRuleFactory()
        pk = rule.pk

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            rule.delete()

        from icv_sitemaps.models.discovery import RobotsRule

        assert not RobotsRule.objects.filter(pk=pk).exists()


class TestAdsEntrySignalsSurviveCacheFailure:
    def test_save_succeeds_when_cache_delete_raises(self, db):
        entry = AdsEntryFactory()

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            entry.publisher_id = "pub-changed"
            entry.save()

        entry.refresh_from_db()
        assert entry.publisher_id == "pub-changed"

    def test_app_ads_save_succeeds_when_cache_delete_raises(self, db):
        entry = AdsEntryFactory(is_app_ads=True)

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            entry.publisher_id = "pub-changed"
            entry.save()

        entry.refresh_from_db()
        assert entry.publisher_id == "pub-changed"

    def test_delete_succeeds_when_cache_delete_raises(self, db):
        entry = AdsEntryFactory()
        pk = entry.pk

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            entry.delete()

        from icv_sitemaps.models.discovery import AdsEntry

        assert not AdsEntry.objects.filter(pk=pk).exists()


class TestDiscoveryFileConfigSignalsSurviveCacheFailure:
    def test_save_succeeds_when_cache_delete_raises(self, db):
        config = DiscoveryFileConfigFactory(file_type="humans_txt")

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            config.content = "changed"
            config.save()

        config.refresh_from_db()
        assert config.content == "changed"

    def test_delete_succeeds_when_cache_delete_raises(self, db):
        config = DiscoveryFileConfigFactory(file_type="security_txt")
        pk = config.pk

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            config.delete()

        from icv_sitemaps.models.discovery import DiscoveryFileConfig

        assert not DiscoveryFileConfig.objects.filter(pk=pk).exists()


class TestRedirectRuleSignalsSurviveCacheFailure:
    def test_save_succeeds_when_cache_delete_raises(self, db):
        rule = RedirectRuleFactory()

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            rule.destination = "/changed/"
            rule.save()

        rule.refresh_from_db()
        assert rule.destination == "/changed/"

    def test_delete_succeeds_when_cache_delete_raises(self, db):
        rule = RedirectRuleFactory()
        pk = rule.pk

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            rule.delete()

        from icv_sitemaps.models.redirects import RedirectRule

        assert not RedirectRule.objects.filter(pk=pk).exists()
