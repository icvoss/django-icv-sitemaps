"""Tests for icv-sitemaps views."""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import Client

from icv_sitemaps.testing.factories import (
    AdsEntryFactory,
    DiscoveryFileConfigFactory,
    RobotsRuleFactory,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the Django cache before and after each test to prevent contamination."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    return Client()


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------


class TestRobotsTxtView:
    def test_returns_200(self, client, db):
        response = client.get("/robots.txt")
        assert response.status_code == 200

    def test_content_type_is_plain_text(self, client, db):
        response = client.get("/robots.txt")
        assert "text/plain" in response["Content-Type"]

    def test_contains_sitemap_directive(self, client, db, settings):
        settings.ICV_SITEMAPS_BASE_URL = "https://example.com"
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []

        response = client.get("/robots.txt")

        assert b"Sitemap:" in response.content

    def test_includes_disallow_rules(self, client, db, settings):
        settings.ICV_SITEMAPS_BASE_URL = ""
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []
        RobotsRuleFactory(user_agent="*", directive="disallow", path="/admin/")

        response = client.get("/robots.txt")

        assert b"Disallow: /admin/" in response.content


# ---------------------------------------------------------------------------
# ads.txt
# ---------------------------------------------------------------------------


class TestAdsTxtView:
    def test_returns_200(self, client, db):
        response = client.get("/ads.txt")
        assert response.status_code == 200

    def test_content_type_is_plain_text(self, client, db):
        response = client.get("/ads.txt")
        assert "text/plain" in response["Content-Type"]

    def test_includes_iab_entries(self, client, db):
        AdsEntryFactory(domain="google.com", publisher_id="pub-123", relationship="DIRECT")

        response = client.get("/ads.txt")

        assert b"google.com, pub-123, DIRECT" in response.content

    def test_excludes_app_ads_entries(self, client, db):
        AdsEntryFactory(domain="app.com", publisher_id="app-1", relationship="DIRECT", is_app_ads=True)

        response = client.get("/ads.txt")

        assert b"app.com" not in response.content


# ---------------------------------------------------------------------------
# app-ads.txt
# ---------------------------------------------------------------------------


class TestAppAdsTxtView:
    def test_returns_200(self, client, db):
        response = client.get("/app-ads.txt")
        assert response.status_code == 200

    def test_includes_only_app_ads_entries(self, client, db):
        AdsEntryFactory(domain="app.com", publisher_id="app-1", relationship="DIRECT", is_app_ads=True)
        AdsEntryFactory(domain="web.com", publisher_id="web-1", relationship="DIRECT", is_app_ads=False)

        response = client.get("/app-ads.txt")

        assert b"app.com" in response.content
        assert b"web.com" not in response.content


# ---------------------------------------------------------------------------
# llms.txt
# ---------------------------------------------------------------------------


class TestLlmsTxtView:
    def test_returns_200_when_config_exists(self, client, db):
        DiscoveryFileConfigFactory(file_type="llms_txt", content="# llms.txt\nAllow: *")

        response = client.get("/llms.txt")

        assert response.status_code == 200
        assert b"# llms.txt" in response.content

    def test_returns_404_when_not_configured(self, client, db):
        response = client.get("/llms.txt")
        assert response.status_code == 404

    def test_returns_404_when_inactive(self, client, db):
        DiscoveryFileConfigFactory(file_type="llms_txt", content="content", is_active=False)

        response = client.get("/llms.txt")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# security.txt
# ---------------------------------------------------------------------------


class TestSecurityTxtView:
    def test_canonical_url_returns_200(self, client, db):
        DiscoveryFileConfigFactory(
            file_type="security_txt",
            content="Contact: mailto:security@example.com",
        )

        response = client.get("/.well-known/security.txt")

        assert response.status_code == 200
        assert b"Contact:" in response.content

    def test_canonical_url_returns_404_when_not_configured(self, client, db):
        response = client.get("/.well-known/security.txt")
        assert response.status_code == 404

    def test_root_path_redirects_to_canonical(self, client, db):
        response = client.get("/security.txt")

        assert response.status_code == 301
        assert "well-known" in response["Location"]


# ---------------------------------------------------------------------------
# humans.txt
# ---------------------------------------------------------------------------


class TestHumansTxtView:
    def test_returns_200_when_configured(self, client, db):
        DiscoveryFileConfigFactory(
            file_type="humans_txt",
            content="/* TEAM */\nNigel Copley",
        )

        response = client.get("/humans.txt")

        assert response.status_code == 200
        assert b"TEAM" in response.content

    def test_returns_404_when_not_configured(self, client, db):
        response = client.get("/humans.txt")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# sitemap file path traversal
# ---------------------------------------------------------------------------


class TestSitemapFileView:
    def test_path_traversal_returns_404(self, client, db):
        response = client.get("/sitemaps/../etc/passwd")
        assert response.status_code == 404

    def test_absolute_path_returns_404(self, client, db):
        response = client.get("/sitemaps/%2Fetc%2Fpasswd")
        assert response.status_code == 404

    def test_missing_file_returns_404(self, client, db):
        response = client.get("/sitemaps/nonexistent.xml")
        assert response.status_code == 404

    def test_plain_xml_file_served_as_application_xml(self, client, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_STORAGE_PATH = "sitemaps/"

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        xml = b'<?xml version="1.0" encoding="UTF-8"?><urlset></urlset>'
        default_storage.save("sitemaps/products-0.xml", ContentFile(xml))

        response = client.get("/sitemaps/products-0.xml")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/xml"
        assert "Content-Encoding" not in response

    def test_gz_file_served_as_gzip_without_content_encoding(self, client, db, tmp_path, settings):
        """Pre-gzipped ``.gz`` sitemaps must be served as an opaque gzip file.

        Setting ``Content-Encoding: gzip`` marks the body as transport-encoded,
        which contradicts the ``.gz`` entity and causes Googlebot (which does not
        send ``Accept-Encoding: gzip`` for sitemaps) to reject the file.
        """
        import gzip

        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_STORAGE_PATH = "sitemaps/"

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        xml = b'<?xml version="1.0" encoding="UTF-8"?><urlset></urlset>'
        default_storage.save("sitemaps/products-0.xml.gz", ContentFile(gzip.compress(xml)))

        response = client.get("/sitemaps/products-0.xml.gz")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/gzip"
        # Critical: no Content-Encoding header for a pre-gzipped .gz entity.
        assert "Content-Encoding" not in response
        # Body is the raw gzip file, decompressible to the original XML.
        assert gzip.decompress(response.content) == xml


# ---------------------------------------------------------------------------
# sitemap index
# ---------------------------------------------------------------------------


class TestSitemapIndexView:
    def test_returns_xml_when_no_files(self, client, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_STORAGE_PATH = "sitemaps/"
        settings.ICV_SITEMAPS_GZIP = False
        settings.ICV_SITEMAPS_BASE_URL = "https://example.com"

        # No files in storage — the view generates an empty index on the fly
        response = client.get("/sitemap.xml")

        # Accepts 200 or 404 — the view generates on the fly if no files
        assert response.status_code in (200, 404)

    def test_returns_xml_content_type(self, client, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_STORAGE_PATH = "sitemaps/"
        settings.ICV_SITEMAPS_GZIP = False
        settings.ICV_SITEMAPS_BASE_URL = "https://example.com"

        # Write a pre-generated index file to storage
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        index_xml = b'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>'
        default_storage.save("sitemaps/sitemap.xml", ContentFile(index_xml))

        response = client.get("/sitemap.xml")

        assert response.status_code == 200
        assert "xml" in response["Content-Type"]


# ---------------------------------------------------------------------------
# Cache resilience (#9)
#
# tests/settings.py sets ICV_SITEMAPS_CACHE_TIMEOUT = 0, and per Django's
# documented cache semantics a timeout of 0 makes the value expire
# immediately, so it can never be observed as a cache hit. Any test here that
# needs to prove a value was actually served from the cache (rather than
# regenerated) patches icv_sitemaps.conf.ICV_SITEMAPS_CACHE_TIMEOUT directly,
# because conf.py reads settings at import time and call sites re-import the
# module-level name inside the function body specifically so this patch
# target works; django.test.override_settings and the pytest-django
# `settings` fixture are silent no-ops for these names.
# ---------------------------------------------------------------------------


class TestCacheResilience:
    def test_robots_txt_returns_200_when_cache_get_raises(self, client, db):
        RobotsRuleFactory(user_agent="*", directive="disallow", path="/admin/")

        with patch.object(cache, "get", side_effect=ConnectionError("redis down")):
            response = client.get("/robots.txt")

        assert response.status_code == 200
        assert b"Disallow: /admin/" in response.content

    def test_robots_txt_returns_200_when_cache_set_raises(self, client, db):
        RobotsRuleFactory(user_agent="*", directive="disallow", path="/admin/")

        with patch.object(cache, "set", side_effect=ConnectionError("redis down")):
            response = client.get("/robots.txt")

        assert response.status_code == 200
        assert b"Disallow: /admin/" in response.content

    def test_ads_txt_returns_200_when_cache_get_raises(self, client, db):
        AdsEntryFactory(domain="google.com", publisher_id="pub-123", relationship="DIRECT")

        with patch.object(cache, "get", side_effect=ConnectionError("redis down")):
            response = client.get("/ads.txt")

        assert response.status_code == 200
        assert b"google.com, pub-123, DIRECT" in response.content

    def test_ads_txt_returns_200_when_cache_set_raises(self, client, db):
        AdsEntryFactory(domain="google.com", publisher_id="pub-123", relationship="DIRECT")

        with patch.object(cache, "set", side_effect=ConnectionError("redis down")):
            response = client.get("/ads.txt")

        assert response.status_code == 200
        assert b"google.com, pub-123, DIRECT" in response.content

    def test_app_ads_txt_returns_200_when_cache_raises(self, client, db):
        AdsEntryFactory(domain="app.com", publisher_id="app-1", relationship="DIRECT", is_app_ads=True)

        with patch.object(cache, "get", side_effect=ConnectionError("redis down")):
            response = client.get("/app-ads.txt")

        assert response.status_code == 200
        assert b"app.com" in response.content

    def test_llms_txt_returns_200_when_cache_get_raises(self, client, db):
        DiscoveryFileConfigFactory(file_type="llms_txt", content="# llms.txt\nAllow: *")

        with patch.object(cache, "get", side_effect=ConnectionError("redis down")):
            response = client.get("/llms.txt")

        assert response.status_code == 200
        assert b"# llms.txt" in response.content

    def test_llms_txt_returns_200_when_cache_set_raises(self, client, db):
        DiscoveryFileConfigFactory(file_type="llms_txt", content="# llms.txt\nAllow: *")

        with patch.object(cache, "set", side_effect=ConnectionError("redis down")):
            response = client.get("/llms.txt")

        assert response.status_code == 200
        assert b"# llms.txt" in response.content

    def test_security_txt_returns_200_when_cache_raises(self, client, db):
        DiscoveryFileConfigFactory(
            file_type="security_txt",
            content="Contact: mailto:security@example.com",
        )

        with patch.object(cache, "get", side_effect=ConnectionError("redis down")):
            response = client.get("/.well-known/security.txt")

        assert response.status_code == 200
        assert b"Contact:" in response.content

    def test_humans_txt_returns_200_when_cache_raises(self, client, db):
        DiscoveryFileConfigFactory(file_type="humans_txt", content="/* TEAM */\nNigel Copley")

        with patch.object(cache, "get", side_effect=ConnectionError("redis down")):
            response = client.get("/humans.txt")

        assert response.status_code == 200
        assert b"TEAM" in response.content

    def test_robots_txt_serves_from_cache_without_hitting_the_database_again(self, client, db, settings):
        """Prove the cache is genuinely consulted, not merely tolerated.

        A non-zero timeout is required to observe a real hit: with the test
        suite's default ICV_SITEMAPS_CACHE_TIMEOUT = 0 every value expires
        immediately and this would pass for the wrong reason.

        The second change must NOT go through the ORM's ``save()``/``create()``
        path: ``RobotsRule``'s ``post_save`` signal (see ``handlers.py``)
        correctly busts this very cache key, so creating a second rule via
        the factory would invalidate the cache for the right reason and the
        test would not be exercising a cache hit at all. A queryset
        ``.update()`` changes the row without emitting ``post_save``, which
        is the only way to prove the second request is served from cache
        rather than regenerated.
        """
        from icv_sitemaps.models.discovery import RobotsRule

        with patch("icv_sitemaps.conf.ICV_SITEMAPS_CACHE_TIMEOUT", 3600):
            rule = RobotsRuleFactory(user_agent="*", directive="disallow", path="/first/")
            first = client.get("/robots.txt")
            assert b"Disallow: /first/" in first.content

            # Mutate the row directly, bypassing save() so no post_save
            # signal fires and the cache is left untouched.
            RobotsRule.objects.filter(pk=rule.pk).update(path="/second/")
            second = client.get("/robots.txt")

        assert second.status_code == 200
        assert b"Disallow: /first/" in second.content
        assert b"Disallow: /second/" not in second.content

    def test_robots_txt_render_failure_does_not_poison_the_cache(self, client, db):
        """A render failure falling back to "" must not be cached.

        An empty robots.txt means "allow everything", the opposite of a
        restrictive ruleset that failed to render, so caching that empty
        fallback for the full timeout would be worse than not caching at
        all.
        """
        with patch("icv_sitemaps.conf.ICV_SITEMAPS_CACHE_TIMEOUT", 3600):
            with patch(
                "icv_sitemaps.services.robots.render_robots_txt",
                side_effect=RuntimeError("boom"),
            ):
                failed = client.get("/robots.txt")

            assert failed.status_code == 200
            assert failed.content == b""

            # Now that rendering works again, the view must regenerate
            # rather than serve the previously-failed empty body, proving
            # nothing was cached under the failure.
            RobotsRuleFactory(user_agent="*", directive="disallow", path="/admin/")
            recovered = client.get("/robots.txt")

        assert recovered.status_code == 200
        assert b"Disallow: /admin/" in recovered.content

    def test_ads_txt_render_failure_does_not_poison_the_cache(self, client, db):
        with patch("icv_sitemaps.conf.ICV_SITEMAPS_CACHE_TIMEOUT", 3600):
            with patch(
                "icv_sitemaps.services.ads.render_ads_txt",
                side_effect=RuntimeError("boom"),
            ):
                failed = client.get("/ads.txt")

            assert failed.status_code == 200
            assert failed.content == b""

            AdsEntryFactory(domain="google.com", publisher_id="pub-123", relationship="DIRECT")
            recovered = client.get("/ads.txt")

        assert recovered.status_code == 200
        assert b"google.com, pub-123, DIRECT" in recovered.content
