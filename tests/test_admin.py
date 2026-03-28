"""Tests for icv-sitemaps admin registrations."""

from django.contrib.admin.sites import AdminSite

from icv_sitemaps.admin import (
    AdsEntryAdmin,
    DiscoveryFileConfigAdmin,
    RobotsRuleAdmin,
    SitemapFileAdmin,
    SitemapGenerationLogAdmin,
    SitemapSectionAdmin,
)
from icv_sitemaps.models import (
    AdsEntry,
    DiscoveryFileConfig,
    RobotsRule,
    SitemapFile,
    SitemapGenerationLog,
    SitemapSection,
)


class TestAdminRegistrations:
    """Verify that all 6 models are registered with admin classes."""

    def test_sitemap_section_is_registered(self):
        from django.contrib import admin

        assert admin.site.is_registered(SitemapSection)

    def test_sitemap_file_is_registered(self):
        from django.contrib import admin

        assert admin.site.is_registered(SitemapFile)

    def test_sitemap_generation_log_is_registered(self):
        from django.contrib import admin

        assert admin.site.is_registered(SitemapGenerationLog)

    def test_robots_rule_is_registered(self):
        from django.contrib import admin

        assert admin.site.is_registered(RobotsRule)

    def test_ads_entry_is_registered(self):
        from django.contrib import admin

        assert admin.site.is_registered(AdsEntry)

    def test_discovery_file_config_is_registered(self):
        from django.contrib import admin

        assert admin.site.is_registered(DiscoveryFileConfig)


class TestSitemapSectionAdmin:
    def setup_method(self):
        self.site = AdminSite()
        self.admin = SitemapSectionAdmin(SitemapSection, self.site)

    def test_list_display_contains_key_fields(self):
        assert "name" in self.admin.list_display
        assert "is_active" in self.admin.list_display
        assert "is_stale" in self.admin.list_display

    def test_readonly_fields_include_stats(self):
        assert "url_count" in self.admin.readonly_fields
        assert "file_count" in self.admin.readonly_fields

    def test_actions_include_mark_stale(self):
        action_names = [a if isinstance(a, str) else a.__name__ for a in self.admin.actions]
        assert any("stale" in str(a).lower() for a in action_names)


class TestSitemapFileAdmin:
    def setup_method(self):
        self.site = AdminSite()
        self.admin = SitemapFileAdmin(SitemapFile, self.site)

    def test_has_no_add_permission(self):
        from unittest.mock import MagicMock

        request = MagicMock()
        assert self.admin.has_add_permission(request) is False

    def test_has_no_change_permission(self):
        from unittest.mock import MagicMock

        request = MagicMock()
        assert self.admin.has_change_permission(request) is False


class TestSitemapGenerationLogAdmin:
    def setup_method(self):
        self.site = AdminSite()
        self.admin = SitemapGenerationLogAdmin(SitemapGenerationLog, self.site)

    def test_has_no_add_permission(self):
        from unittest.mock import MagicMock

        request = MagicMock()
        assert self.admin.has_add_permission(request) is False

    def test_has_no_change_permission(self):
        from unittest.mock import MagicMock

        request = MagicMock()
        assert self.admin.has_change_permission(request) is False


class TestRobotsRuleAdmin:
    def setup_method(self):
        self.site = AdminSite()
        self.admin = RobotsRuleAdmin(RobotsRule, self.site)

    def test_list_display_contains_key_fields(self):
        assert "user_agent" in self.admin.list_display
        assert "directive" in self.admin.list_display
        assert "is_active" in self.admin.list_display


class TestAdsEntryAdmin:
    def setup_method(self):
        self.site = AdminSite()
        self.admin = AdsEntryAdmin(AdsEntry, self.site)

    def test_list_display_contains_key_fields(self):
        assert "domain" in self.admin.list_display
        assert "relationship" in self.admin.list_display
        assert "is_app_ads" in self.admin.list_display


class TestDiscoveryFileConfigAdmin:
    def setup_method(self):
        self.site = AdminSite()
        self.admin = DiscoveryFileConfigAdmin(DiscoveryFileConfig, self.site)

    def test_list_display_contains_key_fields(self):
        assert "file_type" in self.admin.list_display
        assert "is_active" in self.admin.list_display
