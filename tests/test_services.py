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
