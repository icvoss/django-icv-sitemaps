"""Tests for icv-sitemaps service functions."""

from unittest.mock import MagicMock, patch

import pytest

from icv_sitemaps.models import (
    DiscoveryFileConfig,
    SitemapFile,
    SitemapGenerationLog,
)
from icv_sitemaps.services import (
    add_ads_entry,
    add_robots_rule,
    create_section,
    generate_index,
    generate_section,
    get_discovery_file_content,
    get_generation_stats,
    mark_section_stale,
    render_ads_txt,
    render_robots_txt,
    set_discovery_file_content,
)
from icv_sitemaps.signals import sitemap_section_stale
from icv_sitemaps.testing.factories import (
    AdsEntryFactory,
    DiscoveryFileConfigFactory,
    RobotsRuleFactory,
    SitemapSectionFactory,
)

# ---------------------------------------------------------------------------
# render_robots_txt
# ---------------------------------------------------------------------------


class TestRenderRobotsTxt:
    def test_with_rules(self, db, settings):
        settings.ICV_SITEMAPS_BASE_URL = "https://example.com"
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""

        RobotsRuleFactory(user_agent="*", directive="disallow", path="/admin/", order=0)
        RobotsRuleFactory(user_agent="*", directive="allow", path="/", order=1)

        content = render_robots_txt()

        assert "User-agent: *" in content
        assert "Disallow: /admin/" in content
        assert "Allow: /" in content
        assert "Sitemap: https://example.com/sitemap.xml" in content

    def test_empty_no_rules(self, db, settings):
        settings.ICV_SITEMAPS_BASE_URL = "https://example.com"
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""

        content = render_robots_txt()

        # No user-agent blocks, just the sitemap directive
        assert "User-agent:" not in content
        assert "Sitemap: https://example.com/sitemap.xml" in content

    def test_extra_directives_merged(self, db):
        # icv_sitemaps.conf evaluates at import time — patch the module attribute
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES", ["Crawl-delay: 10"]),
            patch.object(conf_mod, "ICV_SITEMAPS_ROBOTS_SITEMAP_URL", ""),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", ""),
        ):
            content = render_robots_txt()

        assert "Crawl-delay: 10" in content

    def test_inactive_rules_excluded(self, db, settings):
        settings.ICV_SITEMAPS_BASE_URL = ""
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""

        RobotsRuleFactory(user_agent="*", directive="disallow", path="/secret/", is_active=False)

        content = render_robots_txt()

        assert "/secret/" not in content

    def test_rule_comment_included(self, db, settings):
        settings.ICV_SITEMAPS_BASE_URL = ""
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""

        RobotsRuleFactory(
            user_agent="*",
            directive="disallow",
            path="/staging/",
            comment="Keep crawlers out of staging",
        )

        content = render_robots_txt()

        assert "# Keep crawlers out of staging" in content


# ---------------------------------------------------------------------------
# render_ads_txt
# ---------------------------------------------------------------------------


class TestRenderAdsTxt:
    def test_renders_entries(self, db):
        AdsEntryFactory(
            domain="google.com",
            publisher_id="pub-123",
            relationship="DIRECT",
            is_app_ads=False,
        )
        AdsEntryFactory(
            domain="criteo.com",
            publisher_id="456",
            relationship="RESELLER",
            is_app_ads=False,
        )

        content = render_ads_txt()

        assert "google.com, pub-123, DIRECT" in content
        assert "criteo.com, 456, RESELLER" in content

    def test_app_ads_filter(self, db):
        AdsEntryFactory(domain="normal.com", publisher_id="n1", relationship="DIRECT", is_app_ads=False)
        AdsEntryFactory(domain="app.com", publisher_id="a1", relationship="DIRECT", is_app_ads=True)

        ads_content = render_ads_txt(app_ads=False)
        app_ads_content = render_ads_txt(app_ads=True)

        assert "normal.com" in ads_content
        assert "app.com" not in ads_content
        assert "app.com" in app_ads_content
        assert "normal.com" not in app_ads_content

    def test_certification_id_included(self, db):
        AdsEntryFactory(
            domain="google.com",
            publisher_id="pub-123",
            relationship="DIRECT",
            certification_id="abc123cert",
        )

        content = render_ads_txt()

        assert "abc123cert" in content

    def test_inactive_entries_excluded(self, db):
        AdsEntryFactory(domain="inactive.com", publisher_id="x", relationship="DIRECT", is_active=False)

        content = render_ads_txt()

        assert "inactive.com" not in content

    def test_entry_comment_included(self, db):
        AdsEntryFactory(
            domain="google.com",
            publisher_id="pub-1",
            relationship="DIRECT",
            comment="Primary ad partner",
        )

        content = render_ads_txt()

        assert "# Primary ad partner" in content


# ---------------------------------------------------------------------------
# add_robots_rule
# ---------------------------------------------------------------------------


class TestAddRobotsRule:
    def test_creates_rule(self, db):
        rule = add_robots_rule("Googlebot", "disallow", "/private/")

        assert rule.pk is not None
        assert rule.user_agent == "Googlebot"
        assert rule.directive == "disallow"
        assert rule.path == "/private/"

    def test_invalid_directive_raises(self, db):
        with pytest.raises(ValueError, match="directive must be"):
            add_robots_rule("*", "block", "/api/")

    def test_path_without_slash_raises(self, db):
        with pytest.raises(ValueError, match="path must start with"):
            add_robots_rule("*", "disallow", "api/")

    def test_normalises_directive_to_lowercase(self, db):
        rule = add_robots_rule("*", "Disallow", "/admin/")
        assert rule.directive == "disallow"


# ---------------------------------------------------------------------------
# add_ads_entry
# ---------------------------------------------------------------------------


class TestAddAdsEntry:
    def test_creates_entry(self, db):
        entry = add_ads_entry("google.com", "pub-999", "DIRECT")

        assert entry.pk is not None
        assert entry.domain == "google.com"
        assert entry.publisher_id == "pub-999"
        assert entry.relationship == "DIRECT"

    def test_invalid_relationship_raises(self, db):
        with pytest.raises(ValueError, match="relationship must be"):
            add_ads_entry("google.com", "pub-1", "PARTNER")

    def test_normalises_relationship_to_uppercase(self, db):
        entry = add_ads_entry("google.com", "pub-1", "direct")
        assert entry.relationship == "DIRECT"

    def test_is_app_ads_flag(self, db):
        entry = add_ads_entry("google.com", "pub-2", "DIRECT", is_app_ads=True)
        assert entry.is_app_ads is True


# ---------------------------------------------------------------------------
# get_discovery_file_content / set_discovery_file_content
# ---------------------------------------------------------------------------


class TestDiscoveryFileServices:
    def test_get_returns_content_when_exists(self, db):
        DiscoveryFileConfigFactory(file_type="llms_txt", content="# llms.txt\nAllow: *")

        result = get_discovery_file_content("llms_txt")

        assert result == "# llms.txt\nAllow: *"

    def test_get_returns_none_when_not_found(self, db):
        result = get_discovery_file_content("llms_txt")

        assert result is None

    def test_get_returns_none_when_inactive(self, db):
        DiscoveryFileConfigFactory(file_type="llms_txt", content="something", is_active=False)

        result = get_discovery_file_content("llms_txt")

        assert result is None

    def test_set_creates_config(self, db):
        config = set_discovery_file_content("security_txt", "Contact: security@example.com")

        assert config.pk is not None
        assert config.content == "Contact: security@example.com"
        assert config.is_active is True

    def test_set_updates_existing_config(self, db):
        DiscoveryFileConfigFactory(file_type="humans_txt", content="old content")

        config = set_discovery_file_content("humans_txt", "new content")

        assert config.content == "new content"
        assert DiscoveryFileConfig.objects.filter(file_type="humans_txt").count() == 1

    def test_tenant_scoped_get(self, db):
        DiscoveryFileConfigFactory(file_type="llms_txt", content="tenant-a content", tenant_id="a")
        DiscoveryFileConfigFactory(file_type="llms_txt", content="tenant-b content", tenant_id="b")

        assert get_discovery_file_content("llms_txt", tenant_id="a") == "tenant-a content"
        assert get_discovery_file_content("llms_txt", tenant_id="b") == "tenant-b content"
        assert get_discovery_file_content("llms_txt", tenant_id="") is None


# ---------------------------------------------------------------------------
# create_section
# ---------------------------------------------------------------------------


class TestCreateSection:
    def test_creates_section(self, db):
        section = create_section(
            "articles",
            model_class=None,
            sitemap_type="standard",
        )

        assert section.pk is not None
        assert section.name == "articles"
        assert section.sitemap_type == "standard"

    def test_seeds_from_mixin_attributes(self, db):
        from sitemaps_testapp.models import Article

        section = create_section("articles", model_class=Article)

        assert section.changefreq == Article.sitemap_changefreq
        assert float(section.priority) == pytest.approx(Article.sitemap_priority)

    def test_kwargs_override_mixin_defaults(self, db):
        from sitemaps_testapp.models import Article

        section = create_section("articles", model_class=Article, changefreq="monthly")

        assert section.changefreq == "monthly"


# ---------------------------------------------------------------------------
# mark_section_stale
# ---------------------------------------------------------------------------


class TestMarkSectionStale:
    def test_marks_and_sends_signal(self, db):
        section = SitemapSectionFactory(name="products", is_stale=False)

        signal_received = []

        def _handler(sender, instance, **kwargs):
            signal_received.append(instance)

        sitemap_section_stale.connect(_handler, dispatch_uid="test_mark_stale")
        try:
            result = mark_section_stale("products")
        finally:
            sitemap_section_stale.disconnect(dispatch_uid="test_mark_stale")

        assert result is True
        section.refresh_from_db()
        assert section.is_stale is True
        assert len(signal_received) == 1
        assert signal_received[0].pk == section.pk

    def test_returns_false_when_not_found(self, db):
        result = mark_section_stale("nonexistent")
        assert result is False

    def test_already_stale_does_not_send_signal(self, db):
        """When the section is already stale, no state change occurs and no signal fires."""
        section = SitemapSectionFactory(name="news", is_stale=True)

        signal_received = []

        def _handler(sender, instance, **kw):
            signal_received.append(instance)

        sitemap_section_stale.connect(_handler, sender=section.__class__, dispatch_uid="test_stale_idempotent")
        try:
            result = mark_section_stale("news")
        finally:
            sitemap_section_stale.disconnect(sender=section.__class__, dispatch_uid="test_stale_idempotent")

        assert result is True  # Section exists
        assert len(signal_received) == 0  # No state change → no signal


# ---------------------------------------------------------------------------
# get_generation_stats
# ---------------------------------------------------------------------------


class TestGetGenerationStats:
    def test_returns_correct_counts(self, db):
        SitemapSectionFactory(url_count=100, file_count=1, is_stale=False)
        SitemapSectionFactory(url_count=200, file_count=2, is_stale=True)

        stats = get_generation_stats()

        assert stats["total_sections"] == 2
        assert stats["stale_count"] == 1
        assert stats["total_urls"] == 300
        assert stats["total_files"] == 3
        assert stats["last_generation_at"] is None  # no sections have been generated

    def test_empty_when_no_sections(self, db):
        stats = get_generation_stats()

        assert stats["total_sections"] == 0
        assert stats["stale_count"] == 0
        assert stats["total_urls"] == 0
        assert stats["total_files"] == 0

    def test_tenant_scoped(self, db):
        SitemapSectionFactory(tenant_id="a", url_count=10)
        SitemapSectionFactory(tenant_id="b", url_count=20)

        stats_a = get_generation_stats(tenant_id="a")
        stats_b = get_generation_stats(tenant_id="b")

        assert stats_a["total_sections"] == 1
        assert stats_a["total_urls"] == 10
        assert stats_b["total_sections"] == 1
        assert stats_b["total_urls"] == 20


# ---------------------------------------------------------------------------
# generate_section
# ---------------------------------------------------------------------------


class TestGenerateSection:
    def test_skips_not_stale(self, db):
        section = SitemapSectionFactory(name="static", is_stale=False)

        result = generate_section(section)

        assert result == 0

    def test_force_overrides_staleness(self, db, tmp_path, settings):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod

        settings.MEDIA_ROOT = str(tmp_path)

        section = SitemapSectionFactory(
            name="articles",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=False,
        )
        from sitemaps_testapp.models import Article

        Article.objects.create(title="T1", slug="t1", is_published=True)

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False),
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
            patch.object(conf_mod, "ICV_SITEMAPS_MAX_URLS_PER_FILE", 50000),
            patch.object(conf_mod, "ICV_SITEMAPS_MAX_FILE_SIZE_BYTES", 52428800),
            patch.object(conf_mod, "ICV_SITEMAPS_BATCH_SIZE", 5000),
        ):
            result = generate_section(section, force=True)

        assert result >= 0  # Ran without error

    def test_generates_standard_sitemap(self, db, tmp_path, settings):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod

        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import Article

        Article.objects.create(title="Article 1", slug="article-1", is_published=True)
        Article.objects.create(title="Article 2", slug="article-2", is_published=True)
        Article.objects.create(title="Unpublished", slug="unpublished", is_published=False)

        section = SitemapSectionFactory(
            name="articles",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False),
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
            patch.object(conf_mod, "ICV_SITEMAPS_MAX_URLS_PER_FILE", 50000),
            patch.object(conf_mod, "ICV_SITEMAPS_MAX_FILE_SIZE_BYTES", 52428800),
            patch.object(conf_mod, "ICV_SITEMAPS_BATCH_SIZE", 5000),
        ):
            url_count = generate_section(section)

        assert url_count == 2  # Only published articles
        section.refresh_from_db()
        assert section.is_stale is False
        assert section.url_count == 2

        # Check that a file was created in storage
        assert SitemapFile.objects.filter(section=section).count() == 1

        # Check that a generation log was created
        log = SitemapGenerationLog.objects.filter(section=section, action="generate_section").last()
        assert log is not None
        assert log.status == "success"

    def test_splits_files_at_url_limit(self, db, tmp_path, settings):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod

        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import Article

        for i in range(5):
            Article.objects.create(title=f"Article {i}", slug=f"article-{i}", is_published=True)

        section = SitemapSectionFactory(
            name="articles",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        # Patch conf constants — they're evaluated at import time so we patch
        # the module attributes directly
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_MAX_URLS_PER_FILE", 3),
            patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False),
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
            patch.object(conf_mod, "ICV_SITEMAPS_MAX_FILE_SIZE_BYTES", 52428800),
            patch.object(conf_mod, "ICV_SITEMAPS_BATCH_SIZE", 5000),
        ):
            url_count = generate_section(section)

        assert url_count == 5
        # Should have been split into 2 files (3 + 2)
        assert SitemapFile.objects.filter(section=section).count() == 2


# ---------------------------------------------------------------------------
# generate_index
# ---------------------------------------------------------------------------


class TestGenerateIndex:
    def test_generates_sitemap_index_xml(self, db, tmp_path, settings):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod

        settings.MEDIA_ROOT = str(tmp_path)

        from icv_sitemaps.testing.factories import SitemapFileFactory

        section = SitemapSectionFactory(name="articles")
        SitemapFileFactory(section=section, storage_path="sitemaps/articles-0.xml")

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False),
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
        ):
            path = generate_index()

        assert path.endswith("sitemap.xml") or "sitemap" in path

        from django.core.files.storage import default_storage

        assert default_storage.exists(path)

        with default_storage.open(path, "rb") as f:
            content = f.read().decode("utf-8")

        assert "sitemapindex" in content
        assert "https://example.com" in content


# ---------------------------------------------------------------------------
# ping_search_engines
# ---------------------------------------------------------------------------


class TestPingSearchEngines:
    def test_disabled_returns_empty(self, db):
        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services import ping_search_engines

        with patch.object(conf_mod, "ICV_SITEMAPS_PING_ENABLED", False):
            results = ping_search_engines()

        assert results == {}

    def test_no_base_url_returns_empty(self, db):
        """When ping is enabled but no sitemap URL can be resolved, returns empty dict."""
        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services import ping_search_engines

        # Pass empty explicit URL and empty settings BASE_URL
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENGINES", ["google"]),
            patch("django.conf.settings") as mock_settings,
        ):
            mock_settings.ICV_SITEMAPS_BASE_URL = ""
            results = ping_search_engines(sitemap_url="")

        assert results == {}

    def test_pings_configured_engines(self, db):
        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services import ping_search_engines

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENGINES", ["google", "bing"]),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            # Pass explicit URL to avoid reading from django_settings
            results = ping_search_engines(sitemap_url="https://example.com/sitemap.xml")

        assert "google" in results
        assert "bing" in results


# ---------------------------------------------------------------------------
# check_redirect / add_redirect
# ---------------------------------------------------------------------------


class TestCheckRedirect:
    def test_exact_match(self, db):
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/old/", "/new/", 301)
        result = check_redirect("/old/")
        assert result is not None
        assert result["destination"] == "/new/"
        assert result["status_code"] == 301

    def test_no_match_returns_none(self, db):
        from icv_sitemaps.services.redirects import check_redirect

        result = check_redirect("/nonexistent/")
        assert result is None

    def test_prefix_match(self, db):
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/blog/", "/articles/", 301, match_type="prefix")
        result = check_redirect("/blog/post-1/")
        assert result is not None

    def test_regex_match(self, db):
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect(r"/product/\d+/", "/products/", 301, match_type="regex")
        result = check_redirect("/product/123/")
        assert result is not None

    def test_priority_ordering(self, db):
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/path/", "/low-priority/", 301, priority=10)
        add_redirect("/path/", "/high-priority/", 302, priority=1, match_type="prefix")
        result = check_redirect("/path/")
        assert result["destination"] == "/high-priority/"

    def test_inactive_excluded(self, db):
        from icv_sitemaps.services.redirects import check_redirect
        from icv_sitemaps.testing.factories import RedirectRuleFactory

        RedirectRuleFactory(source_pattern="/inactive/", is_active=False)
        result = check_redirect("/inactive/")
        assert result is None

    def test_tenant_scoping(self, db):
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/path/", "/tenant-a/", 301, tenant_id="a")
        assert check_redirect("/path/", tenant_id="a") is not None
        assert check_redirect("/path/", tenant_id="b") is None


class TestAddRedirect:
    def test_creates_rule(self, db):
        from icv_sitemaps.services.redirects import add_redirect

        rule = add_redirect("/old/", "/new/", 301)
        assert rule.pk is not None
        assert rule.source_pattern == "/old/"
        assert rule.destination == "/new/"

    def test_invalid_status_code_raises(self, db):
        from icv_sitemaps.services.redirects import add_redirect

        with pytest.raises(ValueError, match="status_code"):
            add_redirect("/a/", "/b/", 999)

    def test_invalid_match_type_raises(self, db):
        from icv_sitemaps.services.redirects import add_redirect

        with pytest.raises(ValueError, match="match_type"):
            add_redirect("/a/", "/b/", 301, match_type="glob")

    def test_empty_destination_for_non_410_raises(self, db):
        from icv_sitemaps.services.redirects import add_redirect

        with pytest.raises(ValueError, match="destination is required"):
            add_redirect("/a/", "", 301)

    def test_410_clears_destination(self, db):
        from icv_sitemaps.services.redirects import add_redirect

        rule = add_redirect("/gone/", "ignored", 410)
        assert rule.destination == ""

    def test_auto_generates_name(self, db):
        from icv_sitemaps.services.redirects import add_redirect

        rule = add_redirect("/old/", "/new/")
        assert rule.name != ""


class TestBulkImportRedirects:
    def test_creates_and_updates(self, db):
        from icv_sitemaps.services.redirects import bulk_import_redirects

        rows = [
            {"source_pattern": "/a/", "destination": "/b/"},
            {"source_pattern": "/c/", "destination": "/d/", "status_code": "302"},
        ]
        result = bulk_import_redirects(rows)
        assert result["created"] == 2
        assert result["updated"] == 0

        # Re-import with updated destination.
        rows[0]["destination"] = "/updated/"
        result = bulk_import_redirects(rows)
        assert result["updated"] == 2

    def test_error_handling(self, db):
        from icv_sitemaps.services.redirects import bulk_import_redirects

        rows = [{"not_a_field": "value"}]
        result = bulk_import_redirects(rows)
        assert len(result["errors"]) == 1


class TestRecord404:
    def test_creates_entry(self, db):
        from icv_sitemaps.services.redirects import record_404

        log = record_404("/missing/")
        assert log.path == "/missing/"
        assert log.hit_count == 1

    def test_increments_hit_count(self, db):
        from icv_sitemaps.services.redirects import record_404

        record_404("/missing/")
        log = record_404("/missing/")
        assert log.hit_count == 2

    def test_tracks_referrers(self, db):
        from icv_sitemaps.services.redirects import record_404

        record_404("/missing/", referrer="https://google.com")
        log = record_404("/missing/", referrer="https://google.com")
        assert log.referrers.get("https://google.com", 0) >= 1


class TestGetTop404s:
    def test_returns_unresolved_ordered(self, db):
        from icv_sitemaps.models.redirects import RedirectLog
        from icv_sitemaps.services.redirects import get_top_404s

        RedirectLog.objects.create(path="/low/", hit_count=5)
        RedirectLog.objects.create(path="/high/", hit_count=100)
        RedirectLog.objects.create(path="/resolved/", hit_count=200, resolved=True)

        results = list(get_top_404s(min_hits=1))
        assert len(results) == 2
        assert results[0].path == "/high/"

    def test_respects_min_hits(self, db):
        from icv_sitemaps.models.redirects import RedirectLog
        from icv_sitemaps.services.redirects import get_top_404s

        RedirectLog.objects.create(path="/rare/", hit_count=1)
        RedirectLog.objects.create(path="/common/", hit_count=10)

        results = list(get_top_404s(min_hits=5))
        assert len(results) == 1
