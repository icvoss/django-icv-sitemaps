"""Tests for section_type="static" sitemap sections (issue #2).

A static section's URLs come from a declared list or a callable rather than
a Django model queryset. These tests mirror the model-backed generation
tests in test_generation_types.py but source entries statically.
"""

from contextlib import ExitStack
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from icv_sitemaps.auto_sections import _connected_signals, connect_auto_section_signals, disconnect_auto_section_signals
from icv_sitemaps.models import SitemapFile, SitemapSection
from icv_sitemaps.services import create_section, generate_index, generate_section
from icv_sitemaps.testing.factories import StaticSitemapSectionFactory

_CONF_PATCHES = {
    "ICV_SITEMAPS_GZIP": False,
    "ICV_SITEMAPS_STORAGE_PATH": "sitemaps/",
    "ICV_SITEMAPS_BASE_URL": "https://example.com",
    "ICV_SITEMAPS_MAX_URLS_PER_FILE": 50000,
    "ICV_SITEMAPS_MAX_FILE_SIZE_BYTES": 52428800,
    "ICV_SITEMAPS_BATCH_SIZE": 5000,
    "ICV_SITEMAPS_PING_ENABLED": False,
    "ICV_SITEMAPS_NEWS_MAX_AGE_DAYS": 2,
}


def _apply_conf_patches():
    import icv_sitemaps.conf as conf_mod

    stack = ExitStack()
    for attr, value in _CONF_PATCHES.items():
        stack.enter_context(patch.object(conf_mod, attr, value))
    return stack


def _read_storage_file(storage_path: str) -> str:
    from django.core.files.storage import default_storage

    with default_storage.open(storage_path, "rb") as fh:
        return fh.read().decode("utf-8")


def marketing_urls():
    """Dummy url_provider callable used by tests below."""
    return [
        {"loc": "/pricing/", "changefreq": "weekly", "priority": 0.8},
        {"loc": "/about/"},
    ]


def marketing_urls_single():
    return [{"loc": "/callable-page/"}]


# ---------------------------------------------------------------------------
# 1. Inline urls list generates matching <loc>s
# ---------------------------------------------------------------------------


class TestStaticSectionInlineUrls:
    def test_generates_locs_from_inline_list(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="marketing-inline",
            settings={"urls": [{"loc": "/pricing/"}, {"loc": "/about/"}]},
        )

        with _apply_conf_patches():
            url_count = generate_section(section)

        assert url_count == 2

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "https://example.com/pricing/" in xml
        assert "https://example.com/about/" in xml

    def test_absolute_urls_pass_through_unchanged(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="marketing-abs",
            settings={"urls": [{"loc": "https://other.example.com/landing/"}]},
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "https://other.example.com/landing/" in xml

    def test_optional_fields_rendered(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="marketing-optional",
            settings={
                "urls": [
                    {"loc": "/pricing/", "changefreq": "weekly", "priority": 0.9},
                ]
            },
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "<changefreq>weekly</changefreq>" in xml
        assert "<priority>0.9</priority>" in xml


# ---------------------------------------------------------------------------
# 2. url_provider callable
# ---------------------------------------------------------------------------


class TestStaticSectionUrlProvider:
    def test_generates_from_callable(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="marketing-callable",
            settings={"url_provider": "tests.test_static_sections.marketing_urls"},
        )

        with _apply_conf_patches():
            url_count = generate_section(section)

        assert url_count == 2

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "https://example.com/pricing/" in xml
        assert "https://example.com/about/" in xml
        assert "<changefreq>weekly</changefreq>" in xml

    def test_url_provider_called_once(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="marketing-callable-once",
            settings={"url_provider": "tests.test_static_sections.marketing_urls_single"},
        )

        with (
            _apply_conf_patches(),
            patch(
                "tests.test_static_sections.marketing_urls_single",
                wraps=marketing_urls_single,
            ) as mock_provider,
        ):
            generate_section(section)

        mock_provider.assert_called_once_with()


# ---------------------------------------------------------------------------
# 3. url_provider takes precedence over urls
# ---------------------------------------------------------------------------


class TestStaticSectionPrecedence:
    def test_url_provider_wins_over_inline_urls(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="marketing-precedence",
            settings={
                "url_provider": "tests.test_static_sections.marketing_urls_single",
                "urls": [{"loc": "/should-not-appear/"}],
            },
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "callable-page" in xml
        assert "should-not-appear" not in xml


# ---------------------------------------------------------------------------
# 4. Static section's file appears in the index
# ---------------------------------------------------------------------------


class TestStaticSectionIndex:
    def test_static_section_file_listed_in_index(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="marketing-index",
            settings={"urls": [{"loc": "/pricing/"}]},
        )

        with _apply_conf_patches():
            generate_section(section)
            index_path = generate_index()

        index_xml = _read_storage_file(index_path)
        sitemap_file = SitemapFile.objects.get(section=section)

        assert sitemap_file.storage_path in index_xml


# ---------------------------------------------------------------------------
# 5. Sharding reuses the writer for a large static list
# ---------------------------------------------------------------------------


class TestStaticSectionSharding:
    def test_large_static_list_splits_into_multiple_files(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        urls = [{"loc": f"/page-{i}/"} for i in range(5)]
        section = StaticSitemapSectionFactory(
            name="marketing-shard",
            settings={"urls": urls},
        )

        with _apply_conf_patches(), patch("icv_sitemaps.conf.ICV_SITEMAPS_MAX_URLS_PER_FILE", 2):
            url_count = generate_section(section)

        assert url_count == 5
        assert SitemapFile.objects.filter(section=section).count() == 3  # 2 + 2 + 1


# ---------------------------------------------------------------------------
# 6. Validation: section_type/model_path combination
# ---------------------------------------------------------------------------


class TestSectionTypeValidation:
    def test_static_with_model_path_fails_validation(self, db):
        section = SitemapSection(
            name="bad-static",
            section_type="static",
            model_path="sitemaps_testapp.Article",
        )
        with pytest.raises(ValidationError):
            section.full_clean()

    def test_model_without_model_path_fails_validation(self, db):
        section = SitemapSection(
            name="bad-model",
            section_type="model",
            model_path="",
        )
        with pytest.raises(ValidationError):
            section.full_clean()

    def test_static_without_model_path_is_valid(self, db):
        section = SitemapSection(
            name="good-static",
            section_type="static",
            model_path="",
            settings={"urls": [{"loc": "/ok/"}]},
        )
        section.full_clean()  # must not raise

    def test_model_with_model_path_is_valid(self, db):
        section = SitemapSection(
            name="good-model",
            section_type="model",
            model_path="sitemaps_testapp.Article",
        )
        section.full_clean()  # must not raise


# ---------------------------------------------------------------------------
# 7. icv_sitemaps_setup creates static sections without requiring apps.get_model
# ---------------------------------------------------------------------------


class TestSetupCommandStaticSections:
    def test_setup_creates_static_section_without_model(self, db, settings, tmp_path):
        from io import StringIO

        from django.core.management import call_command

        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "marketing-pages": {
                "section_type": "static",
                "sitemap_type": "standard",
                "settings": {"urls": [{"loc": "/pricing/"}]},
            }
        }

        out = StringIO()
        call_command("icv_sitemaps_setup", stdout=out)

        section = SitemapSection.objects.get(name="marketing-pages")
        assert section.section_type == "static"
        assert section.model_path == ""
        assert "Errors:    0" in out.getvalue()


# ---------------------------------------------------------------------------
# 8. connect_auto_section_signals skips static sections silently
# ---------------------------------------------------------------------------


class TestAutoSectionsSkipsStatic:
    def teardown_method(self, method):
        disconnect_auto_section_signals()
        _connected_signals.clear()

    def test_static_section_produces_no_warning_and_no_signal(self, settings, caplog):
        import logging

        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "marketing-pages": {
                "section_type": "static",
                "settings": {"urls": [{"loc": "/pricing/"}]},
            }
        }

        with caplog.at_level(logging.WARNING, logger="icv_sitemaps.auto_sections"):
            connect_auto_section_signals()

        assert "missing 'model' key" not in caplog.text
        assert "icv_sitemaps_auto_save_marketing-pages" not in _connected_signals
        assert "icv_sitemaps_auto_delete_marketing-pages" not in _connected_signals


# ---------------------------------------------------------------------------
# 9. Image/video/news entry dicts render from static sections
# ---------------------------------------------------------------------------


class TestStaticSectionNonStandardTypes:
    def test_static_image_section_renders_image_tags(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="marketing-images",
            sitemap_type="image",
            settings={
                "urls": [
                    {
                        "loc": "/gallery/",
                        "images": [{"loc": "https://cdn.example.com/hero.jpg", "caption": "Hero image"}],
                    }
                ]
            },
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "image:image" in xml
        assert "hero.jpg" in xml
        assert "Hero image" in xml

    def test_static_video_section_renders_video_tags(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="marketing-videos",
            sitemap_type="video",
            settings={
                "urls": [
                    {
                        "loc": "/watch/",
                        "video": {
                            "thumbnail_loc": "https://cdn.example.com/thumb.jpg",
                            "title": "Launch video",
                            "description": "Product launch",
                            "content_loc": "https://cdn.example.com/launch.mp4",
                        },
                    }
                ]
            },
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "video:video" in xml
        assert "Launch video" in xml

    def test_static_news_section_renders_news_tags(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.utils import timezone

        section = StaticSitemapSectionFactory(
            name="marketing-news",
            sitemap_type="news",
            settings={
                "urls": [
                    {
                        "loc": "/press-release/",
                        "news": {
                            "publication_name": "Example Press",
                            "language": "en",
                            "publication_date": timezone.now(),
                            "title": "Big Announcement",
                        },
                    }
                ]
            },
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "news:news" in xml
        assert "Big Announcement" in xml


# ---------------------------------------------------------------------------
# create_section() service helper
# ---------------------------------------------------------------------------


class TestCreateSectionStatic:
    def test_create_section_with_urls_produces_static_section(self, db):
        section = create_section(
            "marketing-pages",
            urls=[{"loc": "/pricing/"}],
        )

        assert section.section_type == "static"
        assert section.model_path == ""
        assert section.settings["urls"] == [{"loc": "/pricing/"}]

    def test_create_section_with_url_provider_produces_static_section(self, db):
        section = create_section(
            "marketing-pages",
            url_provider="tests.test_static_sections.marketing_urls",
        )

        assert section.section_type == "static"
        assert section.settings["url_provider"] == "tests.test_static_sections.marketing_urls"

    def test_create_section_rejects_model_and_urls_together(self, db):
        from sitemaps_testapp.models import Article

        with pytest.raises(ValueError):
            create_section(
                "conflict",
                model_class=Article,
                urls=[{"loc": "/pricing/"}],
            )

    def test_create_section_with_model_still_produces_model_section(self, db):
        from sitemaps_testapp.models import Article

        section = create_section("articles", model_class=Article)

        assert section.section_type == "model"
        assert section.model_path == "sitemaps_testapp.Article"
