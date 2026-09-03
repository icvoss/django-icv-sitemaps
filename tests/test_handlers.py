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


class TestHandlersCallTheNamedInvalidators:
    """Regression guard for #37: handlers.py was rewired from inline
    cache-key literals to the named invalidate_*_cache functions extracted
    from services/robots.py, services/ads.py and services/discovery.py.
    These spy on the real function (wraps=...) so a call is proven, not
    merely a key string matching a constant imported from the same module.
    """

    def test_on_robots_rule_save_calls_invalidate_robots_cache(self, db):
        from icv_sitemaps.services import robots as robots_module

        with patch.object(robots_module, "invalidate_robots_cache", wraps=robots_module.invalidate_robots_cache) as spy:
            rule = RobotsRuleFactory()

        spy.assert_called_once_with(tenant_id=rule.tenant_id)

    def test_on_robots_rule_delete_calls_invalidate_robots_cache(self, db):
        from icv_sitemaps.services import robots as robots_module

        rule = RobotsRuleFactory()

        with patch.object(robots_module, "invalidate_robots_cache", wraps=robots_module.invalidate_robots_cache) as spy:
            rule.delete()

        spy.assert_called_once_with(tenant_id=rule.tenant_id)

    def test_on_ads_entry_save_calls_invalidate_ads_cache_with_is_app_ads(self, db):
        from icv_sitemaps.services import ads as ads_module

        with patch.object(ads_module, "invalidate_ads_cache", wraps=ads_module.invalidate_ads_cache) as spy:
            entry = AdsEntryFactory(is_app_ads=True)

        spy.assert_called_once_with(is_app_ads=True, tenant_id=entry.tenant_id)

    def test_on_ads_entry_delete_calls_invalidate_ads_cache_with_is_app_ads(self, db):
        from icv_sitemaps.services import ads as ads_module

        entry = AdsEntryFactory(is_app_ads=False)

        with patch.object(ads_module, "invalidate_ads_cache", wraps=ads_module.invalidate_ads_cache) as spy:
            entry.delete()

        spy.assert_called_once_with(is_app_ads=False, tenant_id=entry.tenant_id)

    def test_on_discovery_config_save_calls_invalidate_discovery_cache_with_file_type(self, db):
        from icv_sitemaps.services import discovery as discovery_module

        with patch.object(
            discovery_module, "invalidate_discovery_cache", wraps=discovery_module.invalidate_discovery_cache
        ) as spy:
            config = DiscoveryFileConfigFactory(file_type="humans_txt")

        spy.assert_called_once_with("humans_txt", tenant_id=config.tenant_id)

    def test_on_discovery_config_delete_calls_invalidate_discovery_cache_with_file_type(self, db):
        from icv_sitemaps.services import discovery as discovery_module

        config = DiscoveryFileConfigFactory(file_type="security_txt")

        with patch.object(
            discovery_module, "invalidate_discovery_cache", wraps=discovery_module.invalidate_discovery_cache
        ) as spy:
            config.delete()

        spy.assert_called_once_with("security_txt", tenant_id=config.tenant_id)


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
