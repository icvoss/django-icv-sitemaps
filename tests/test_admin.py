"""Tests for icv-sitemaps admin registrations."""

from django.contrib.admin.sites import AdminSite

from icv_sitemaps.admin import (
    AdsEntryAdmin,
    DiscoveryFileConfigAdmin,
    RedirectLogAdmin,
    RedirectRuleAdmin,
    RobotsRuleAdmin,
    SitemapFileAdmin,
    SitemapGenerationLogAdmin,
    SitemapSectionAdmin,
)
from icv_sitemaps.models import (
    AdsEntry,
    DiscoveryFileConfig,
    RedirectLog,
    RedirectRule,
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


class TestRedirectRuleAdmin:
    def setup_method(self):
        self.site = AdminSite()
        self.admin = RedirectRuleAdmin(RedirectRule, self.site)

    def test_list_display_contains_key_fields(self):
        assert "source_pattern" in self.admin.list_display
        assert "destination" in self.admin.list_display
        assert "status_code" in self.admin.list_display
        assert "hit_count" in self.admin.list_display
        assert "is_active" in self.admin.list_display

    def test_registered(self):
        from django.contrib import admin

        assert admin.site.is_registered(RedirectRule)


class TestRedirectLogAdmin:
    def setup_method(self):
        self.site = AdminSite()
        self.admin = RedirectLogAdmin(RedirectLog, self.site)

    def test_list_display_contains_key_fields(self):
        assert "path" in self.admin.list_display
        assert "hit_count" in self.admin.list_display
        assert "resolved" in self.admin.list_display

    def test_read_only(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/admin/")
        assert self.admin.has_add_permission(request) is False
        assert self.admin.has_change_permission(request) is False

    def test_registered(self):
        from django.contrib import admin

        assert admin.site.is_registered(RedirectLog)


class TestCreateGoneFrom404Action:
    """The 410-from-404 bulk action surfaces per-row failures, not just a count."""

    def test_failures_are_reported_not_swallowed(self, db):
        from unittest.mock import MagicMock, patch

        from icv_sitemaps.admin import create_gone_from_404
        from icv_sitemaps.testing.factories import RedirectLogFactory

        RedirectLogFactory(path="/gone-1", resolved=False)
        RedirectLogFactory(path="/gone-2", resolved=False)

        modeladmin = MagicMock()
        request = MagicMock()
        queryset = RedirectLog.objects.all()

        with (
            patch(
                "icv_sitemaps.services.redirects.add_redirect",
                side_effect=ValueError("bad redirect"),
            ),
            patch("icv_sitemaps.admin.logger") as mock_logger,
        ):
            create_gone_from_404(modeladmin, request, queryset)

        # Each failure is logged...
        assert mock_logger.warning.call_count == 2
        # ...and the operator is told failures occurred (warning-level message).
        levels = [kwargs.get("level") for _args, kwargs in modeladmin.message_user.call_args_list]
        assert "warning" in levels
        # No rows were marked resolved, since every add_redirect failed.
        assert RedirectLog.objects.filter(resolved=True).count() == 0
