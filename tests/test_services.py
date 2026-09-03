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

    def test_longest_match_wins_over_author_order(self, db, settings):
        """RFC 9309 s2.2.2: the most specific path pattern MUST be used.

        Author ``order`` disagrees with longest match here: the broad
        Disallow is declared first (order=0) and the narrower, more specific
        Allow second (order=1). A conforming crawler resolves by path length,
        not declaration order, so the longer ``/admin/public/`` pattern must
        be emitted before the shorter ``/admin/`` pattern regardless of
        ``order``. This is the case current author-order emission gets wrong.
        """
        settings.ICV_SITEMAPS_BASE_URL = ""
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""

        RobotsRuleFactory(user_agent="*", directive="disallow", path="/admin/", order=0)
        RobotsRuleFactory(user_agent="*", directive="allow", path="/admin/public/", order=1)

        content = render_robots_txt()

        allow_index = content.index("Allow: /admin/public/")
        disallow_index = content.index("Disallow: /admin/")
        assert allow_index < disallow_index

    def test_equal_length_allow_beats_disallow(self, db, settings):
        """RFC 9309 s2.2.2: Allow wins an exact-length tie."""
        settings.ICV_SITEMAPS_BASE_URL = ""
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""

        RobotsRuleFactory(user_agent="*", directive="disallow", path="/secret/", order=0)
        RobotsRuleFactory(user_agent="*", directive="allow", path="/public/", order=1)

        content = render_robots_txt()

        allow_index = content.index("Allow: /public/")
        disallow_index = content.index("Disallow: /secret/")
        assert allow_index < disallow_index

    def test_equal_specificity_falls_back_to_order(self, db, settings):
        """Rules of equal specificity (same length, same directive) keep
        ``order`` as the tiebreaker, so it still does a real job."""
        settings.ICV_SITEMAPS_BASE_URL = ""
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""

        RobotsRuleFactory(user_agent="*", directive="disallow", path="/second/", order=1)
        RobotsRuleFactory(user_agent="*", directive="disallow", path="/first!/", order=0)

        content = render_robots_txt()

        first_index = content.index("Disallow: /first!/")
        second_index = content.index("Disallow: /second/")
        assert first_index < second_index

    def test_mixed_case_user_agents_merge_into_one_group(self, db, settings):
        """RFC 9309 s2.2.1: the product token is case-insensitive and
        multiple groups matching one user agent MUST combine into one."""
        settings.ICV_SITEMAPS_BASE_URL = ""
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""

        RobotsRuleFactory(user_agent="Googlebot", directive="disallow", path="/admin/", order=0)
        RobotsRuleFactory(user_agent="googlebot", directive="allow", path="/public/", order=1)

        content = render_robots_txt()

        assert content.count("User-agent:") == 1
        assert "User-agent: Googlebot" in content
        assert "Disallow: /admin/" in content
        assert "Allow: /public/" in content


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

    def test_empty_emits_iab_placeholder_record(self, db):
        """Issue #22: an empty file is deprecated (IAB ads.txt v1.1 s3.2.1)."""
        content = render_ads_txt()

        assert content == "placeholder.example.com, placeholder, DIRECT, placeholder"

    def test_empty_app_ads_also_emits_placeholder(self, db):
        content = render_ads_txt(app_ads=True)

        assert content == "placeholder.example.com, placeholder, DIRECT, placeholder"

    def test_placeholder_omitted_when_active_entries_exist(self, db):
        AdsEntryFactory(domain="google.com", publisher_id="pub-1", relationship="DIRECT")

        content = render_ads_txt()

        assert "placeholder.example.com" not in content

    def test_placeholder_can_be_disabled_via_setting(self, db):
        import icv_sitemaps.conf as conf_mod

        with patch.object(conf_mod, "ICV_SITEMAPS_ADS_TXT_EMPTY_PLACEHOLDER", False):
            content = render_ads_txt()

        assert content == ""

    def test_row_with_embedded_newline_is_skipped_not_rendered(self, db, caplog):
        """Issue #18: a row already in the database with a stored newline
        (written before this fix, or via objects.create()/bulk_create(),
        which bypass add_ads_entry's write-side check and the model's
        clean()) must not inject extra records into rendered output.
        """
        from icv_sitemaps.models.discovery import AdsEntry

        # Bypasses add_ads_entry and clean()/full_clean() entirely, exactly
        # like an admin edit or a pre-fix database row would.
        AdsEntry.objects.create(
            domain="google.com",
            publisher_id="pub-1",
            relationship="DIRECT",
            comment="fine\nevil.example.com, 1, DIRECT",
        )
        AdsEntryFactory(domain="clean.com", publisher_id="pub-2", relationship="DIRECT")

        with caplog.at_level("WARNING"):
            content = render_ads_txt()

        assert "evil.example.com" not in content
        assert "google.com" not in content  # the whole bad row is omitted, not just the comment
        assert "clean.com, pub-2, DIRECT" in content
        assert "skipping AdsEntry" in caplog.text

    def test_row_with_embedded_newline_in_domain_is_skipped(self, db):
        from icv_sitemaps.models.discovery import AdsEntry

        AdsEntry.objects.create(
            domain="google.com\nevil.example.com, 1, DIRECT",
            publisher_id="pub-1",
            relationship="DIRECT",
        )

        content = render_ads_txt()

        assert content == "placeholder.example.com, placeholder, DIRECT, placeholder"


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

    def test_newline_in_domain_raises(self, db):
        with pytest.raises(ValueError, match="must not contain newline"):
            add_ads_entry("google.com\nevil.com, pub-1, DIRECT", "pub-1", "DIRECT")

    def test_carriage_return_in_publisher_id_raises(self, db):
        with pytest.raises(ValueError, match="must not contain newline"):
            add_ads_entry("google.com", "pub-1\revil.com, pub-2, DIRECT", "DIRECT")

    def test_newline_in_certification_id_raises(self, db):
        with pytest.raises(ValueError, match="must not contain newline"):
            add_ads_entry("google.com", "pub-1", "DIRECT", certification_id="abc\ninjected")

    def test_newline_in_comment_raises(self, db):
        with pytest.raises(ValueError, match="must not contain newline"):
            add_ads_entry("google.com", "pub-1", "DIRECT", comment="fine\nevil.com, pub-9, DIRECT")

    def test_newline_via_kwargs_route_is_rejected(self, db):
        """Issue #18: comment is not a named parameter of add_ads_entry, so
        it only ever arrives via the documented **kwargs passthrough
        ("Additional field values passed to AdsEntry.objects.create").
        The generic kwargs check must reject it before any AdsEntry row is
        written, not just the four explicitly named parameters.
        """
        from icv_sitemaps.models.discovery import AdsEntry

        with pytest.raises(ValueError, match="comment must not contain newline"):
            add_ads_entry(
                "google.com",
                "pub-1",
                "DIRECT",
                **{"comment": "a\nevil.example.com, 1, DIRECT"},
            )

        assert not AdsEntry.objects.filter(domain="google.com").exists()


# ---------------------------------------------------------------------------
# AdsEntry model-level newline validation (issue #18)
#
# add_ads_entry defends its own callers with a ValueError (tested above),
# but admin saves, objects.create() and bulk_create() bypass that function
# entirely. The model's clean() and field validators are the backstop for
# those paths.
# ---------------------------------------------------------------------------


class TestAdsEntryModelNewlineValidation:
    def test_clean_rejects_newline_in_domain(self, db):
        from django.core.exceptions import ValidationError

        from icv_sitemaps.models import AdsEntry

        entry = AdsEntry(
            domain="google.com\nevil.com, pub-1, DIRECT",
            publisher_id="pub-1",
            relationship="DIRECT",
        )

        with pytest.raises(ValidationError):
            entry.full_clean()

    def test_clean_rejects_newline_in_comment(self, db):
        from django.core.exceptions import ValidationError

        from icv_sitemaps.models import AdsEntry

        entry = AdsEntry(
            domain="google.com",
            publisher_id="pub-1",
            relationship="DIRECT",
            comment="fine\nevil.com, pub-9, DIRECT",
        )

        with pytest.raises(ValidationError):
            entry.full_clean()

    def test_clean_accepts_well_formed_entry(self, db):
        from icv_sitemaps.models import AdsEntry

        entry = AdsEntry(
            domain="google.com",
            publisher_id="pub-1",
            relationship="DIRECT",
            certification_id="cert-1",
            comment="Primary partner",
        )

        entry.full_clean()  # Must not raise


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
        content = "Contact: security@example.com\nExpires: 2027-12-31T23:59:59Z"
        config = set_discovery_file_content("security_txt", content)

        assert config.pk is not None
        assert config.content == content
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

    def test_llms_txt_content_not_validated(self, db):
        """No standard mandates llms.txt shape: any content is accepted."""
        config = set_discovery_file_content("llms_txt", "anything goes here")

        assert config.content == "anything goes here"

    def test_humans_txt_content_not_validated(self, db):
        """No standard mandates humans.txt shape: any content is accepted."""
        config = set_discovery_file_content("humans_txt", "no particular structure required")

        assert config.content == "no particular structure required"


# ---------------------------------------------------------------------------
# security.txt RFC 9116 validation (issue #20)
# ---------------------------------------------------------------------------


class TestSecurityTxtValidation:
    def test_missing_contact_raises(self, db):
        with pytest.raises(ValueError, match="Contact"):
            set_discovery_file_content("security_txt", "Expires: 2027-12-31T23:59:59Z")

    def test_missing_expires_raises(self, db):
        with pytest.raises(ValueError, match="Expires"):
            set_discovery_file_content("security_txt", "Contact: mailto:security@example.com")

    def test_duplicate_expires_raises(self, db):
        content = "Contact: mailto:security@example.com\nExpires: 2027-12-31T23:59:59Z\nExpires: 2028-01-01T00:00:00Z"
        with pytest.raises(ValueError, match="exactly one"):
            set_discovery_file_content("security_txt", content)

    def test_malformed_expires_timestamp_raises(self, db):
        content = "Contact: mailto:security@example.com\nExpires: not-a-timestamp"
        with pytest.raises(ValueError, match="RFC 3339"):
            set_discovery_file_content("security_txt", content)

    def test_empty_content_raises(self, db):
        with pytest.raises(ValueError, match="Contact"):
            set_discovery_file_content("security_txt", "")

    def test_multiple_contact_lines_accepted(self, db):
        """RFC 9116 s2.5.3 only requires 'at least one' Contact field."""
        content = (
            "Contact: mailto:security@example.com\nContact: https://example.com/report\nExpires: 2027-12-31T23:59:59Z"
        )
        config = set_discovery_file_content("security_txt", content)

        assert config.content == content

    def test_valid_content_saves_successfully(self, db):
        content = "Contact: mailto:security@example.com\nExpires: 2027-06-30T00:00:00Z"
        config = set_discovery_file_content("security_txt", content)

        assert config.pk is not None
        assert config.content == content

    def test_expires_with_utc_offset_accepted(self, db):
        """RFC 3339 allows a numeric UTC offset, not only the 'Z' suffix."""
        content = "Contact: mailto:security@example.com\nExpires: 2027-12-31T23:59:59+00:00"

        config = set_discovery_file_content("security_txt", content)

        assert config.pk is not None


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


class TestGenerateSectionLastmod:
    """Issue #19: SitemapFile.generated_at reflects content changes, not runs."""

    def _make_section_with_articles(self, settings, tmp_path, titles):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import Article

        Article.objects.all().delete()
        for title in titles:
            Article.objects.create(title=title, slug=title.lower().replace(" ", "-"), is_published=True)

        return SitemapSectionFactory(
            name="articles",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

    def _patch_conf(self, conf_mod, *, max_urls=50000):
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False))
        stack.enter_context(patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"))
        stack.enter_context(patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"))
        stack.enter_context(patch.object(conf_mod, "ICV_SITEMAPS_MAX_URLS_PER_FILE", max_urls))
        stack.enter_context(patch.object(conf_mod, "ICV_SITEMAPS_MAX_FILE_SIZE_BYTES", 52428800))
        stack.enter_context(patch.object(conf_mod, "ICV_SITEMAPS_BATCH_SIZE", 5000))
        return stack

    def test_unchanged_content_preserves_generated_at(self, db, tmp_path, settings):
        import icv_sitemaps.conf as conf_mod

        section = self._make_section_with_articles(settings, tmp_path, ["Article 1", "Article 2"])

        with self._patch_conf(conf_mod):
            generate_section(section)

        first = SitemapFile.objects.get(section=section, sequence=0)
        first_generated_at = first.generated_at
        first_checksum = first.checksum
        assert first_checksum  # sanity: a real checksum was computed

        section.is_stale = True
        section.save(update_fields=["is_stale"])

        with self._patch_conf(conf_mod):
            generate_section(section, force=True)

        second = SitemapFile.objects.get(section=section, sequence=0)
        assert second.checksum == first_checksum
        assert second.generated_at == first_generated_at

    def test_changed_content_advances_generated_at(self, db, tmp_path, settings):
        import icv_sitemaps.conf as conf_mod

        section = self._make_section_with_articles(settings, tmp_path, ["Article 1", "Article 2"])

        with self._patch_conf(conf_mod):
            generate_section(section)

        first = SitemapFile.objects.get(section=section, sequence=0)
        first_generated_at = first.generated_at
        first_checksum = first.checksum

        # Change the underlying content: add a third article so the shard's
        # bytes, and therefore its checksum, differ.
        from sitemaps_testapp.models import Article

        Article.objects.create(title="Article 3", slug="article-3", is_published=True)
        section.is_stale = True
        section.save(update_fields=["is_stale"])

        with self._patch_conf(conf_mod):
            generate_section(section, force=True)

        second = SitemapFile.objects.get(section=section, sequence=0)
        assert second.checksum != first_checksum
        assert second.generated_at != first_generated_at

    def test_index_lastmod_unchanged_when_content_unchanged(self, db, tmp_path, settings):
        """The index's <lastmod> for a shard must not move when its content did not."""
        import icv_sitemaps.conf as conf_mod

        section = self._make_section_with_articles(settings, tmp_path, ["Article 1"])

        with self._patch_conf(conf_mod):
            generate_section(section)
            first_path = generate_index()
            from django.core.files.storage import default_storage

            with default_storage.open(first_path, "rb") as fh:
                first_index_content = fh.read().decode("utf-8")

            section.is_stale = True
            section.save(update_fields=["is_stale"])
            generate_section(section, force=True)
            second_path = generate_index()

            with default_storage.open(second_path, "rb") as fh:
                second_index_content = fh.read().decode("utf-8")

        assert first_index_content == second_index_content

    def test_shard_count_shrinking_does_not_carry_stale_timestamp(self, db, tmp_path, settings):
        """A sequence reused by genuinely different content must not inherit
        the old timestamp just because the sequence number matches."""
        import icv_sitemaps.conf as conf_mod

        section = self._make_section_with_articles(settings, tmp_path, ["Article 1", "Article 2", "Article 3"])

        # Force 3 shards, one URL each.
        with self._patch_conf(conf_mod, max_urls=1):
            generate_section(section)

        assert SitemapFile.objects.filter(section=section).count() == 3
        shard_0 = SitemapFile.objects.get(section=section, sequence=0)
        shard_0_generated_at = shard_0.generated_at
        shard_0_checksum = shard_0.checksum

        # Shrink to a single article, keeping the *last* one by pk so the
        # sole remaining shard (sequence 0) holds a different article's URL
        # than the first run's sequence-0 shard did (which held "Article 1",
        # the first by pk, under one-URL-per-shard ordering).
        from sitemaps_testapp.models import Article

        Article.objects.exclude(pk=Article.objects.order_by("pk").last().pk).delete()
        section.is_stale = True
        section.save(update_fields=["is_stale"])

        with self._patch_conf(conf_mod, max_urls=1):
            generate_section(section, force=True)

        assert SitemapFile.objects.filter(section=section).count() == 1
        remaining = SitemapFile.objects.get(section=section, sequence=0)
        # Content differs (different article), so the checksum differs and
        # the timestamp must not have been carried forward from the old
        # sequence-0 row, even though the sequence number is reused.
        if remaining.checksum == shard_0_checksum:
            pytest.fail("test setup produced identical content; cannot assert timestamp behaviour")
        assert remaining.generated_at != shard_0_generated_at


class TestGenerateSectionFailure:
    """Generation failures (e.g. storage upload errors) are recorded, not masked."""

    def _make_section(self, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import Article

        Article.objects.create(title="Article 1", slug="article-1", is_published=True)
        Article.objects.create(title="Article 2", slug="article-2", is_published=True)
        return SitemapSectionFactory(
            name="articles",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

    def test_upload_failure_marks_log_failed_and_reraises(self, db, tmp_path, settings):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.signals import sitemap_section_generation_failed

        section = self._make_section(settings, tmp_path)

        received = []

        def _handler(sender, instance, error, detail, **kwargs):
            received.append((instance, error, detail))

        sitemap_section_generation_failed.connect(_handler, dispatch_uid="test_gen_failed")
        try:
            with (
                patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False),
                patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
                patch(
                    "icv_sitemaps.services.generation._publish_shard",
                    side_effect=OSError("disk full"),
                ),
                pytest.raises(OSError, match="disk full"),
            ):
                generate_section(section)
        finally:
            sitemap_section_generation_failed.disconnect(dispatch_uid="test_gen_failed")

        # Log must be recorded as failed, not left 'running' or marked 'success'.
        log = SitemapGenerationLog.objects.filter(section=section, action="generate_section").last()
        assert log is not None
        assert log.status == "failed"
        assert "disk full" in log.detail

        # Failure signal fired with the error.
        assert len(received) == 1
        assert "disk full" in received[0][2]

        # Section is not falsely marked fresh.
        section.refresh_from_db()
        assert section.is_stale is True


# ---------------------------------------------------------------------------
# Atomic publish (issue #5)
# ---------------------------------------------------------------------------


class TestReplaceInStorage:
    """Regression for #5: a failed publish must retain the previous sitemap.

    The pre-fix code (``_upload_temp_to_storage``) already staged to
    ``dest_path + ".tmp"`` before touching ``dest_path``, but never verified
    that staged copy: it deleted ``dest_path`` and re-saved from the local
    temp file unconditionally, so a staged upload that landed truncated or
    corrupt (the reported hazard, "the replacement upload fails") was
    promoted anyway, destroying the previous file for no working
    replacement. ``_replace_in_storage()`` verifies the staged copy's size
    before ever deleting ``dest_path``
    (``test_staged_upload_size_mismatch_leaves_previous_file_intact`` is the
    test that actually distinguishes the fix from the old behaviour). The
    ``.tmp``-write failure test below is included as a locked-in guarantee:
    it already held pre-fix and must keep holding.
    """

    def test_failed_staged_upload_leaves_previous_file_intact(self, tmp_path):
        """A failure while writing the staged .tmp copy must not touch the
        previously published file at dest_path. Already true pre-fix (the
        .tmp write happens before dest_path is touched either way); kept as
        a locked-in guarantee alongside the size-mismatch test below, which
        is the scenario the pre-fix code actually got wrong."""
        from django.core.files.base import ContentFile
        from django.core.files.storage import FileSystemStorage

        from icv_sitemaps.services.generation import _replace_in_storage

        storage = FileSystemStorage(location=str(tmp_path))
        dest_path = "sitemaps/articles-0.xml"
        previous_content = b"<?xml version='1.0'?><urlset><url><loc>old</loc></url></urlset>"
        storage.save(dest_path, ContentFile(previous_content))

        new_temp = tmp_path / "new-content.xml"
        new_temp.write_bytes(b"<?xml version='1.0'?><urlset><url><loc>new</loc></url></urlset>")

        original_save = storage.save
        call_count = {"n": 0}

        def _flaky_save(name, content, *args, **kwargs):
            call_count["n"] += 1
            if name.endswith(".tmp"):
                raise OSError("simulated network failure during staged upload")
            return original_save(name, content, *args, **kwargs)

        with (
            patch.object(storage, "save", side_effect=_flaky_save),
            pytest.raises(OSError, match="simulated network failure"),
        ):
            _replace_in_storage(storage, str(new_temp), dest_path)

        # The previous file must be exactly as it was: never deleted, never
        # partially overwritten.
        assert storage.exists(dest_path)
        with storage.open(dest_path, "rb") as fh:
            assert fh.read() == previous_content

    def test_staged_upload_size_mismatch_leaves_previous_file_intact(self, tmp_path):
        """A staged upload that silently lands truncated (verified by size,
        not just existence) must not be promoted over the previous file."""
        from django.core.files.base import ContentFile
        from django.core.files.storage import FileSystemStorage

        from icv_sitemaps.exceptions import StorageError
        from icv_sitemaps.services.generation import _replace_in_storage

        storage = FileSystemStorage(location=str(tmp_path))
        dest_path = "sitemaps/articles-0.xml"
        previous_content = b"<?xml version='1.0'?><urlset><url><loc>old</loc></url></urlset>"
        storage.save(dest_path, ContentFile(previous_content))

        new_temp = tmp_path / "new-content.xml"
        new_temp.write_bytes(b"<?xml version='1.0'?><urlset><url><loc>new</loc></url></urlset>")

        original_save = storage.save

        def _truncating_save(name, content, *args, **kwargs):
            if name.endswith(".tmp"):
                # Simulate a backend that "succeeds" but writes short content.
                return original_save(name, ContentFile(b"short"), *args, **kwargs)
            return original_save(name, content, *args, **kwargs)

        with (
            patch.object(storage, "save", side_effect=_truncating_save),
            pytest.raises(StorageError, match="did not land as expected"),
        ):
            _replace_in_storage(storage, str(new_temp), dest_path)

        assert storage.exists(dest_path)
        with storage.open(dest_path, "rb") as fh:
            assert fh.read() == previous_content

    def test_upload_temp_to_storage_public_name_verifies_staged_size(self, tmp_path):
        """Same scenario exercised through the pre-existing public entry
        point, ``_upload_temp_to_storage`` (still the function
        ``_publish_shard`` calls), which is unchanged in name and signature
        across the fix, so this proves the fix through the real call site
        rather than only through the new ``_replace_in_storage`` name."""
        from django.core.files.base import ContentFile
        from django.core.files.storage import FileSystemStorage

        from icv_sitemaps.exceptions import StorageError
        from icv_sitemaps.services.generation import _upload_temp_to_storage

        storage = FileSystemStorage(location=str(tmp_path))
        dest_path = "sitemaps/articles-0.xml"
        previous_content = b"<?xml version='1.0'?><urlset><url><loc>old</loc></url></urlset>"
        storage.save(dest_path, ContentFile(previous_content))

        new_temp = tmp_path / "new-content.xml"
        new_temp.write_bytes(b"<?xml version='1.0'?><urlset><url><loc>new</loc></url></urlset>")

        original_save = storage.save

        def _truncating_save(name, content, *args, **kwargs):
            if name.endswith(".tmp"):
                return original_save(name, ContentFile(b"short"), *args, **kwargs)
            return original_save(name, content, *args, **kwargs)

        with (
            patch.object(storage, "save", side_effect=_truncating_save),
            pytest.raises(StorageError, match="did not land as expected"),
        ):
            _upload_temp_to_storage(storage, str(new_temp), dest_path)

        assert storage.exists(dest_path)
        with storage.open(dest_path, "rb") as fh:
            assert fh.read() == previous_content

    def test_successful_replace_publishes_new_content(self, tmp_path):
        """The happy path still replaces dest_path with the new content."""
        from django.core.files.base import ContentFile
        from django.core.files.storage import FileSystemStorage

        from icv_sitemaps.services.generation import _replace_in_storage

        storage = FileSystemStorage(location=str(tmp_path))
        dest_path = "sitemaps/articles-0.xml"
        storage.save(dest_path, ContentFile(b"old"))

        new_temp = tmp_path / "new-content.xml"
        new_content = b"<?xml version='1.0'?><urlset><url><loc>new</loc></url></urlset>"
        new_temp.write_bytes(new_content)

        final_path, size = _replace_in_storage(storage, str(new_temp), dest_path)

        assert final_path == dest_path
        assert size == len(new_content)
        with storage.open(dest_path, "rb") as fh:
            assert fh.read() == new_content
        # The staging file must not be left behind.
        assert not storage.exists(dest_path + ".tmp")

    def test_overwrite_capable_storage_skips_staging_entirely(self, tmp_path):
        """When the storage backend overwrites in place, _replace_in_storage
        writes dest_path directly: no .tmp file, no delete-then-save window."""
        from django.core.files.base import ContentFile
        from django.core.files.storage import FileSystemStorage

        from icv_sitemaps.services.generation import _replace_in_storage

        storage = FileSystemStorage(location=str(tmp_path), allow_overwrite=True)
        dest_path = "sitemaps/articles-0.xml"
        storage.save(dest_path, ContentFile(b"old"))

        new_temp = tmp_path / "new-content.xml"
        new_content = b"<?xml version='1.0'?><urlset><url><loc>new</loc></url></urlset>"
        new_temp.write_bytes(new_content)

        save_calls = []
        original_save = storage.save

        def _tracking_save(name, content, *args, **kwargs):
            save_calls.append(name)
            return original_save(name, content, *args, **kwargs)

        with patch.object(storage, "save", side_effect=_tracking_save):
            final_path, size = _replace_in_storage(storage, str(new_temp), dest_path)

        assert final_path == dest_path
        assert save_calls == [dest_path]  # exactly one save, no .tmp involved
        with storage.open(dest_path, "rb") as fh:
            assert fh.read() == new_content


class TestWriteBufferedToStorageAtomicity:
    """Same #5 regression coverage for the buffered/index write path.

    ``_write_buffered_to_storage()`` already staged to ``path + ".tmp"``
    before the fix, so a failure mid-staging-upload (this first test) did
    not regress: it is included as a locked-in guarantee. The scenario that
    the pre-fix code actually got wrong is
    ``test_staged_upload_size_mismatch_leaves_previous_index_intact``: the
    old code never verified the staged copy before deleting and replacing
    the previous file.
    """

    def test_failed_staged_upload_leaves_previous_index_intact(self, tmp_path):
        from django.core.files.base import ContentFile
        from django.core.files.storage import FileSystemStorage

        from icv_sitemaps.services.generation import _write_buffered_to_storage

        storage = FileSystemStorage(location=str(tmp_path))
        path = "sitemaps/sitemap.xml"
        previous_content = b"<?xml version='1.0'?><sitemapindex></sitemapindex>"
        storage.save(path, ContentFile(previous_content))

        original_save = storage.save

        def _flaky_save(name, content, *args, **kwargs):
            if name.endswith(".tmp"):
                raise OSError("simulated network failure")
            return original_save(name, content, *args, **kwargs)

        with (
            patch.object(storage, "save", side_effect=_flaky_save),
            pytest.raises(OSError, match="simulated network failure"),
        ):
            _write_buffered_to_storage(storage, path, b"<new index content>")

        assert storage.exists(path)
        with storage.open(path, "rb") as fh:
            assert fh.read() == previous_content

    def test_staged_upload_size_mismatch_leaves_previous_index_intact(self, tmp_path):
        """The staged .tmp write must be verified by size before it is
        promoted; a backend that "succeeds" but writes short content must not
        destroy the previous index. This is the scenario that distinguishes
        the fix from the pre-fix code: both write .tmp first, but only the
        fix verifies the staged copy before deleting the previous file."""
        from django.core.files.base import ContentFile
        from django.core.files.storage import FileSystemStorage

        from icv_sitemaps.exceptions import StorageError
        from icv_sitemaps.services.generation import _write_buffered_to_storage

        storage = FileSystemStorage(location=str(tmp_path))
        path = "sitemaps/sitemap.xml"
        previous_content = b"<?xml version='1.0'?><sitemapindex></sitemapindex>"
        storage.save(path, ContentFile(previous_content))

        original_save = storage.save

        def _truncating_save(name, content, *args, **kwargs):
            if name.endswith(".tmp"):
                return original_save(name, ContentFile(b"short"), *args, **kwargs)
            return original_save(name, content, *args, **kwargs)

        with (
            patch.object(storage, "save", side_effect=_truncating_save),
            pytest.raises(StorageError, match="did not land as expected"),
        ):
            _write_buffered_to_storage(storage, path, b"<new index content, much longer than 'short'>")

        assert storage.exists(path)
        with storage.open(path, "rb") as fh:
            assert fh.read() == previous_content

    def test_successful_write_publishes_new_content(self, tmp_path):
        from django.core.files.base import ContentFile
        from django.core.files.storage import FileSystemStorage

        from icv_sitemaps.services.generation import _write_buffered_to_storage

        storage = FileSystemStorage(location=str(tmp_path))
        path = "sitemaps/sitemap.xml"
        storage.save(path, ContentFile(b"old"))

        new_data = b"<?xml version='1.0'?><sitemapindex><new/></sitemapindex>"
        final_path, size = _write_buffered_to_storage(storage, path, new_data)

        assert final_path == path
        assert size == len(new_data)
        with storage.open(path, "rb") as fh:
            assert fh.read() == new_data
        assert not storage.exists(path + ".tmp")


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

    def test_within_caps_succeeds(self, db, tmp_path, settings):
        """A handful of entries, well under both caps, generates normally."""
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        import icv_sitemaps.services.generation as generation_mod

        settings.MEDIA_ROOT = str(tmp_path)

        from icv_sitemaps.testing.factories import SitemapFileFactory

        section = SitemapSectionFactory(name="articles")
        for i in range(3):
            SitemapFileFactory(section=section, storage_path=f"sitemaps/articles-{i}.xml")

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False),
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
            patch.object(generation_mod, "_INDEX_MAX_ENTRIES", 10),
            patch.object(generation_mod, "_INDEX_MAX_BYTES", 52_428_800),
        ):
            path = generate_index()

        from django.core.files.storage import default_storage

        assert default_storage.exists(path)

    def test_exceeds_entry_count_raises(self, db, tmp_path, settings):
        """More SitemapFile rows than the cap raises SitemapGenerationError
        naming the entry-count cap, without ever writing an index file."""
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        import icv_sitemaps.services.generation as generation_mod
        from icv_sitemaps.exceptions import SitemapGenerationError

        settings.MEDIA_ROOT = str(tmp_path)

        from icv_sitemaps.testing.factories import SitemapFileFactory

        section = SitemapSectionFactory(name="articles")
        for i in range(4):
            SitemapFileFactory(section=section, storage_path=f"sitemaps/articles-{i}.xml")

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False),
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
            patch.object(generation_mod, "_INDEX_MAX_ENTRIES", 3),
            patch.object(generation_mod, "_INDEX_MAX_BYTES", 52_428_800),
            pytest.raises(SitemapGenerationError, match="entries"),
        ):
            generate_index()

        from django.core.files.storage import default_storage

        assert not default_storage.exists("sitemaps/sitemap.xml")

    def test_exceeds_byte_size_raises(self, db, tmp_path, settings):
        """More serialised bytes than the cap raises SitemapGenerationError
        naming the byte-size cap, measured against the real serialised XML."""
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        import icv_sitemaps.services.generation as generation_mod
        from icv_sitemaps.exceptions import SitemapGenerationError

        settings.MEDIA_ROOT = str(tmp_path)

        from icv_sitemaps.testing.factories import SitemapFileFactory

        section = SitemapSectionFactory(name="articles")
        for i in range(3):
            SitemapFileFactory(section=section, storage_path=f"sitemaps/articles-{i}.xml")

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False),
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
            patch.object(generation_mod, "_INDEX_MAX_ENTRIES", 50_000),
            patch.object(generation_mod, "_INDEX_MAX_BYTES", 10),
            pytest.raises(SitemapGenerationError, match="bytes"),
        ):
            generate_index()

        from django.core.files.storage import default_storage

        assert not default_storage.exists("sitemaps/sitemap.xml")


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

    def test_priority_ordering_within_match_type(self, db):
        """Priority only orders rules within the same match type.

        Both rules here are ``prefix``, so match-type ranking does not
        apply and priority is the deciding factor.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/blog/", "/low-priority/", 301, priority=10, match_type="prefix")
        add_redirect("/blog/", "/high-priority/", 302, priority=1, match_type="prefix")
        result = check_redirect("/blog/post-1/")
        assert result["destination"] == "/high-priority/"

    def test_exact_beats_prefix_regardless_of_priority(self, db):
        """An exact rule always wins over an overlapping prefix rule, even
        when the prefix rule has a numerically lower (better) priority.

        This is the documented contract in check_redirect's docstring and
        the fix for #24: match type is the primary sort key, priority only
        orders within a match type. Fails against the pre-#24 code, which
        ordered purely by ("priority", "pk") and let the prefix rule win.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/path/", "/prefix-wins-old-behaviour/", 301, priority=0, match_type="prefix")
        add_redirect("/path/", "/exact-wins-documented-behaviour/", 302, priority=10, match_type="exact")

        result = check_redirect("/path/")
        assert result["destination"] == "/exact-wins-documented-behaviour/"

    def test_prefix_beats_regex_regardless_of_priority(self, db):
        """A prefix rule always wins over an overlapping regex rule, even
        when the regex rule has a numerically lower (better) priority.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect(r"/prod/\d+/", "/regex-destination/", 301, priority=0, match_type="regex")
        add_redirect("/prod/", "/prefix-destination/", 302, priority=10, match_type="prefix")

        result = check_redirect("/prod/123/")
        assert result["destination"] == "/prefix-destination/"

    def test_exact_beats_regex_regardless_of_priority(self, db):
        """An exact rule always wins over an overlapping regex rule, even
        when the regex rule has a numerically lower (better) priority.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect(r"/item/\d+/", "/regex-destination/", 301, priority=0, match_type="regex")
        add_redirect("/item/42/", "/exact-destination/", 302, priority=10, match_type="exact")

        result = check_redirect("/item/42/")
        assert result["destination"] == "/exact-destination/"

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

    def test_saving_a_higher_precedence_rule_invalidates_the_cache_check_reads(self, db, settings):
        """Invalidation must target the exact key ``get_cached_redirect_rules`` reads.

        Populates the redirect cache via ``check_redirect`` (a prefix rule),
        then saves a new higher-precedence exact rule for the same path via
        the model layer directly (exercising the ``on_redirect_rule_save``
        signal handler in ``handlers.py``, not ``add_redirect``, which
        already invalidates on its own). If the handler rebuilt a cache key
        from a literal instead of calling ``invalidate_redirect_cache``, it
        would delete a stale (or wrongly-versioned) key that
        ``get_cached_redirect_rules`` never reads, and this test would
        observe the first, cached (prefix) result forever.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect
        from icv_sitemaps.testing.factories import RedirectRuleFactory

        with patch("icv_sitemaps.conf.ICV_SITEMAPS_REDIRECT_CACHE_TIMEOUT", 3600):
            add_redirect("/path/", "/prefix-destination/", 301, match_type="prefix")

            # Populate the cache.
            first = check_redirect("/path/")
            assert first["destination"] == "/prefix-destination/"

            # Save a new higher-precedence (exact) rule via the model layer,
            # exercising on_redirect_rule_save rather than add_redirect.
            RedirectRuleFactory(
                source_pattern="/path/",
                destination="/exact-destination/",
                match_type="exact",
                status_code=302,
            )

            second = check_redirect("/path/")

        assert second is not None
        assert second["destination"] == "/exact-destination/"

    def test_status_codes_none_considers_every_rule(self, db):
        """The default (``status_codes=None``) is the pre-existing, unfiltered
        behaviour: a bare ``check_redirect(path)`` call must keep matching
        across every status code, for external callers relying on today's
        public signature.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/deleted-product/", "", 410)
        result = check_redirect("/deleted-product/")
        assert result is not None
        assert result["status_code"] == 410

    def test_status_codes_filters_out_excluded_rules(self, db):
        """A rule whose status_code is not in the given set is skipped
        entirely, not just its result discarded after matching.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/deleted-product/", "", 410)
        result = check_redirect("/deleted-product/", status_codes=frozenset({301, 302, 307, 308}))
        assert result is None

    def test_status_codes_filter_applies_before_matching_not_after(self, db):
        """A higher-precedence rule outside the filter must not suppress a
        lower-precedence rule that IS in the filter.

        An exact 410 rule and an overlapping prefix 302 rule both match
        ``/deleted-product/1/``. Filtering after matching (i.e. matching
        first, then discarding the result if its status_code is excluded)
        would return ``None`` here, because the exact rule is the first
        match and gets discarded. Filtering before matching removes the
        410 rule from consideration entirely, so the prefix rule is found.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/deleted-product/1/", "", 410, match_type="exact")
        add_redirect("/deleted-product/", "/products/", 302, match_type="prefix")

        result = check_redirect("/deleted-product/1/", status_codes=frozenset({301, 302, 307, 308}))
        assert result is not None
        assert result["status_code"] == 302
        assert result["destination"] == "/products/"

    def test_exact_match_resolved_by_direct_query_not_cached_scan(self, db, django_assert_num_queries):
        """An exact match is resolved by a single direct query.

        Regression test for #16: previously, every lookup loaded the full
        cached rule list and scanned it in Python. A large number of
        unrelated prefix rules must not add queries or scan cost to an
        exact-match hit: the exact lookup is a single indexed query, found
        before the cached list is ever built or read.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect
        from icv_sitemaps.testing.factories import RedirectRuleFactory

        for i in range(50):
            RedirectRuleFactory(
                source_pattern=f"/prefix-{i}/",
                match_type="prefix",
                destination=f"/dest-{i}/",
            )

        add_redirect("/exact-target/", "/new/", 301, match_type="exact")

        with django_assert_num_queries(1):
            result = check_redirect("/exact-target/")

        assert result is not None
        assert result["destination"] == "/new/"

    def test_exact_beats_overlapping_prefix_via_direct_query(self, db):
        """An exact rule wins over an overlapping prefix rule.

        Same documented precedence as test_exact_beats_prefix_regardless_of_priority,
        but exercised through the direct exact-match query path rather than
        the cached list.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/path/", "/prefix-destination/", 301, match_type="prefix")
        add_redirect("/path/", "/exact-destination/", 302, match_type="exact")

        result = check_redirect("/path/")
        assert result["destination"] == "/exact-destination/"

    def test_exact_gone_rule_excluded_by_live_status_codes(self, db):
        """An exact 410 rule must not be returned when status_codes excludes it.

        This is the correctness requirement behind #16's fix: the direct
        exact-match query must apply the same status_codes restriction as
        the cached-list path, in the database query itself. Without that,
        an exact-match 410 rule would short-circuit and return before the
        middleware's pre-response call (which passes only the live-redirect
        status codes) ever consulted status_codes at all, silently
        reverting the #17 split between live redirects and gone rules.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/deleted-product/", "", 410, match_type="exact")

        live_result = check_redirect("/deleted-product/", status_codes=frozenset({301, 302, 307, 308}))
        assert live_result is None

        gone_result = check_redirect("/deleted-product/", status_codes=frozenset({410}))
        assert gone_result is not None
        assert gone_result["status_code"] == 410

    def test_cached_list_excludes_exact_rules(self, db):
        """Exact rules are never included in the cached prefix/regex list.

        They are resolved by a direct query in :func:`check_redirect`
        instead, so including them in the cache would be dead weight that
        scales with the number of machine-generated exact rules.
        """
        from icv_sitemaps.services.redirects import add_redirect, get_cached_redirect_rules

        add_redirect("/exact/", "/exact-dest/", 301, match_type="exact")
        add_redirect("/blog/", "/articles/", 301, match_type="prefix")
        add_redirect(r"/product/\d+/", "/products/", 301, match_type="regex")

        rules = get_cached_redirect_rules()
        match_types = {rule["match_type"] for rule in rules}
        assert "exact" not in match_types
        assert match_types == {"prefix", "regex"}

    def test_cached_list_still_orders_prefix_before_regex(self, db):
        """Prefix still beats regex regardless of priority, in the exact-free cache.

        Uses a reversed priority (regex numerically lower) so a fallback to
        pk ordering could not accidentally produce the right answer.
        """
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect(r"/prod/\d+/", "/regex-destination/", 301, priority=0, match_type="regex")
        add_redirect("/prod/", "/prefix-destination/", 302, priority=10, match_type="prefix")

        result = check_redirect("/prod/123/")
        assert result["destination"] == "/prefix-destination/"

    def test_exact_lookup_respects_tenant_scoping(self, db):
        """The direct exact-match query is still scoped by tenant_id."""
        from icv_sitemaps.services.redirects import add_redirect, check_redirect

        add_redirect("/path/", "/tenant-a/", 301, match_type="exact", tenant_id="a")
        assert check_redirect("/path/", tenant_id="a") is not None
        assert check_redirect("/path/", tenant_id="b") is None

    def test_get_cached_redirect_rules_uses_v3_cache_key(self, db):
        """The cached list is stored under the v3 cache key.

        The cached list's contents changed (exact rules excluded), so the
        cache key must be versioned to v3: a v2 entry from a process
        running the pre-fix code would hold exact rules and be served
        forever under the new code's assumption that it does not.
        """
        from icv_sitemaps.cache import safe_get
        from icv_sitemaps.services.redirects import add_redirect, get_cached_redirect_rules

        add_redirect("/blog/", "/articles/", 301, match_type="prefix")
        get_cached_redirect_rules()

        assert safe_get("icv_sitemaps:redirects:v3:") is not None
        assert safe_get("icv_sitemaps:redirects:v2:") is None


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


class TestBulkCreateRedirects:
    """Regression coverage for #29: bulk_create leaves the cache stale.

    Scope note: #16 fixed the exact-match half of the original report.
    check_redirect now resolves exact rules with a direct query, never
    from the cache, so only prefix/regex rows still depend on the
    post_save-driven cache invalidation that bulk_create never fires.
    Every regression case below therefore uses a prefix or regex row.
    """

    def test_writes_the_rows(self, db):
        from icv_sitemaps.models.redirects import RedirectRule
        from icv_sitemaps.services.redirects import bulk_create_redirects

        rows = [
            {"source_pattern": "/blog/", "destination": "/articles/", "match_type": "prefix"},
            {"source_pattern": r"/p/\d+/", "destination": "/products/", "match_type": "regex"},
        ]
        result = bulk_create_redirects(rows)

        assert result["created"] == 2
        assert result["errors"] == []
        assert RedirectRule.objects.filter(source_pattern="/blog/").exists()
        assert RedirectRule.objects.filter(source_pattern=r"/p/\d+/").exists()

    def test_invalidates_cache_exactly_once(self, db):
        from icv_sitemaps.services import redirects as redirects_module
        from icv_sitemaps.services.redirects import bulk_create_redirects

        rows = [
            {"source_pattern": "/blog/", "destination": "/articles/", "match_type": "prefix"},
            {"source_pattern": "/shop/", "destination": "/store/", "match_type": "prefix"},
            {"source_pattern": "/help/", "destination": "/support/", "match_type": "prefix"},
        ]
        with patch.object(
            redirects_module, "invalidate_redirect_cache", wraps=redirects_module.invalidate_redirect_cache
        ) as spy:
            bulk_create_redirects(rows)

        spy.assert_called_once_with(tenant_id="")

    def test_new_prefix_rule_is_immediately_visible_to_check_redirect(self, db):
        """The actual regression: this fails if the invalidation call is removed.

        get_cached_redirect_rules() populates the cache on the first call
        (a miss), which would otherwise mask a subsequent stale-cache bug
        for the rest of the test. Priming it first, then bulk-creating,
        proves the cache is actually invalidated rather than merely never
        having been read yet.
        """
        from icv_sitemaps.services.redirects import bulk_create_redirects, check_redirect

        assert check_redirect("/blog/2024/post/") is None

        bulk_create_redirects([{"source_pattern": "/blog/", "destination": "/articles/", "match_type": "prefix"}])

        rule = check_redirect("/blog/2024/post/")
        assert rule is not None
        assert rule["destination"] == "/articles/"

    def test_invalid_rows_land_in_errors_without_aborting_batch(self, db):
        from icv_sitemaps.services.redirects import bulk_create_redirects

        rows = [
            {"source_pattern": "/ok/", "destination": "/fine/", "match_type": "prefix"},
            {"source_pattern": "/bad/", "destination": "/x/", "status_code": 999, "match_type": "prefix"},
            {"source_pattern": "/also-ok/", "destination": "/also-fine/", "match_type": "prefix"},
        ]
        result = bulk_create_redirects(rows)

        assert result["created"] == 2
        assert len(result["errors"]) == 1
        assert result["errors"][0]["row"] == 1

    def test_scopes_to_tenant(self, db):
        from icv_sitemaps.models.redirects import RedirectRule
        from icv_sitemaps.services.redirects import bulk_create_redirects

        bulk_create_redirects(
            [{"source_pattern": "/blog/", "destination": "/articles/", "match_type": "prefix"}],
            tenant_id="acme",
        )

        assert RedirectRule.objects.filter(tenant_id="acme", source_pattern="/blog/").exists()
        assert not RedirectRule.objects.filter(tenant_id="", source_pattern="/blog/").exists()

    def test_conflicting_exact_row_is_skipped_not_raised(self, db):
        from icv_sitemaps.services.redirects import add_redirect, bulk_create_redirects

        add_redirect("/dup/", "/first/", 301, match_type="exact")

        result = bulk_create_redirects([{"source_pattern": "/dup/", "destination": "/second/", "match_type": "exact"}])

        # ignore_conflicts=True: the colliding row is silently skipped, not
        # raised and not counted as created.
        assert result["created"] == 0
        assert result["errors"] == []

    def test_created_count_is_partial_when_some_rows_conflict(self, db):
        """created reflects only the rows that actually landed, not len(rows).

        Mixes one pre-existing exact rule (conflicts, ignore_conflicts=True
        silently drops it) with two brand-new exact rows in the same batch.
        If created were computed as len(validated_rows) instead of the
        before/after row-count delta, this would wrongly report 3 instead
        of 2.
        """
        from icv_sitemaps.models.redirects import RedirectRule
        from icv_sitemaps.services.redirects import add_redirect, bulk_create_redirects

        add_redirect("/dup/", "/first/", 301, match_type="exact")

        result = bulk_create_redirects(
            [
                {"source_pattern": "/dup/", "destination": "/second/", "match_type": "exact"},
                {"source_pattern": "/new-one/", "destination": "/target-one/", "match_type": "exact"},
                {"source_pattern": "/new-two/", "destination": "/target-two/", "match_type": "exact"},
            ]
        )

        assert result["created"] == 2
        assert result["errors"] == []
        assert RedirectRule.objects.filter(source_pattern="/new-one/").exists()
        assert RedirectRule.objects.filter(source_pattern="/new-two/").exists()
        # The pre-existing row is untouched, not overwritten.
        assert RedirectRule.objects.get(source_pattern="/dup/").destination == "/first/"


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


# ---------------------------------------------------------------------------
# Cache resilience (#9)
#
# The write-path service functions below invalidate a cache key after
# mutating the database. Before this fix, an unreachable cache backend made
# the write itself raise: add_robots_rule, add_ads_entry,
# set_discovery_file_content and add_redirect (via invalidate_redirect_cache)
# all called cache.delete() unguarded. A failed delete is deliberately not
# swallowed silently: it is logged at WARNING because it leaves stale
# content cached for up to the timeout, but the write itself must still
# succeed.
# ---------------------------------------------------------------------------


class TestServiceWritesSurviveCacheDeleteFailure:
    def test_add_robots_rule_succeeds_when_cache_delete_raises(self, db):
        from django.core.cache import cache

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            rule = add_robots_rule("*", "disallow", "/admin/")

        assert rule.pk is not None

    def test_add_ads_entry_succeeds_when_cache_delete_raises(self, db):
        from django.core.cache import cache

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            entry = add_ads_entry("google.com", "pub-1", "DIRECT")

        assert entry.pk is not None

    def test_set_discovery_file_content_succeeds_when_cache_delete_raises(self, db):
        from django.core.cache import cache

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            config = set_discovery_file_content("llms_txt", "content")

        assert config.pk is not None
        assert config.content == "content"

    def test_add_redirect_succeeds_when_cache_delete_raises(self, db):
        from django.core.cache import cache

        from icv_sitemaps.services.redirects import add_redirect

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            rule = add_redirect("/old/", "/new/", 301)

        assert rule.pk is not None

    def test_invalidate_redirect_cache_does_not_raise(self, db):
        from django.core.cache import cache

        from icv_sitemaps.services.redirects import invalidate_redirect_cache

        with patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
            invalidate_redirect_cache()  # must not raise


class TestGetCachedRedirectRulesSurvivesCacheFailure:
    def test_returns_rules_when_cache_get_raises(self, db):
        from django.core.cache import cache

        from icv_sitemaps.services.redirects import add_redirect, get_cached_redirect_rules

        # get_cached_redirect_rules deliberately excludes match_type="exact"
        # rules (#16); use a prefix rule so it is actually present in the
        # list this function builds and caches.
        add_redirect("/old/", "/new/", 301, match_type="prefix")

        with patch.object(cache, "get", side_effect=ConnectionError("redis down")):
            rules = get_cached_redirect_rules()

        assert len(rules) == 1
        assert rules[0]["destination"] == "/new/"

    def test_returns_rules_when_cache_set_raises(self, db):
        from django.core.cache import cache

        from icv_sitemaps.services.redirects import add_redirect, get_cached_redirect_rules

        # get_cached_redirect_rules deliberately excludes match_type="exact"
        # rules (#16); use a prefix rule so it is actually present in the
        # list this function builds and caches.
        add_redirect("/old/", "/new/", 301, match_type="prefix")

        with patch.object(cache, "set", side_effect=ConnectionError("redis down")):
            rules = get_cached_redirect_rules()

        assert len(rules) == 1
        assert rules[0]["destination"] == "/new/"
