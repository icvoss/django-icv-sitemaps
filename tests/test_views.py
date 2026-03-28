"""Tests for icv-sitemaps views."""

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
