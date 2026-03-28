"""Tests for image, video, and news sitemap generation."""

from contextlib import ExitStack
from unittest.mock import patch

import pytest

from icv_sitemaps.models import SitemapFile
from icv_sitemaps.services import generate_section
from icv_sitemaps.testing.factories import SitemapSectionFactory

# ---------------------------------------------------------------------------
# Shared conf-patching helper
# ---------------------------------------------------------------------------

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
    """Return an ExitStack with all conf-module patches applied."""
    import icv_sitemaps.conf as conf_mod

    stack = ExitStack()
    for attr, value in _CONF_PATCHES.items():
        stack.enter_context(patch.object(conf_mod, attr, value))
    return stack


def _read_storage_file(storage_path: str) -> str:
    from django.core.files.storage import default_storage

    with default_storage.open(storage_path, "rb") as fh:
        return fh.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Image sitemaps
# ---------------------------------------------------------------------------


class TestImageSitemapGeneration:
    def test_generates_image_xml_tags(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import ProductImage

        ProductImage.objects.create(
            title="Blue Widget",
            slug="blue-widget",
            image_url="https://cdn.example.com/blue-widget.jpg",
            caption="A blue widget photograph",
        )

        section = SitemapSectionFactory(
            name="product-images-xml",
            model_path="sitemaps_testapp.ProductImage",
            sitemap_type="image",
            is_stale=True,
        )

        with _apply_conf_patches():
            url_count = generate_section(section)

        assert url_count == 1

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "image:image" in xml
        assert "image:loc" in xml
        assert "blue-widget.jpg" in xml

    def test_image_caption_in_xml(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import ProductImage

        ProductImage.objects.create(
            title="Red Widget",
            slug="red-widget",
            image_url="https://cdn.example.com/red.jpg",
            caption="A red widget photo",
        )

        section = SitemapSectionFactory(
            name="product-images-caption",
            model_path="sitemaps_testapp.ProductImage",
            sitemap_type="image",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "image:caption" in xml
        assert "A red widget photo" in xml

    def test_image_title_in_xml(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import ProductImage

        ProductImage.objects.create(
            title="Green Widget",
            slug="green-widget",
            image_url="https://cdn.example.com/green.jpg",
            caption="",
        )

        section = SitemapSectionFactory(
            name="product-images-title",
            model_path="sitemaps_testapp.ProductImage",
            sitemap_type="image",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "image:title" in xml
        assert "Green Widget" in xml

    def test_sitemap_file_record_created(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import ProductImage

        ProductImage.objects.create(
            title="Yellow Widget",
            slug="yellow-widget",
            image_url="https://cdn.example.com/yellow.jpg",
            caption="",
        )

        section = SitemapSectionFactory(
            name="product-images-record",
            model_path="sitemaps_testapp.ProductImage",
            sitemap_type="image",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        assert SitemapFile.objects.filter(section=section).count() == 1

    def test_image_urlset_namespace_declared(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import ProductImage

        ProductImage.objects.create(
            title="Purple Widget",
            slug="purple-widget",
            image_url="https://cdn.example.com/purple.jpg",
            caption="",
        )

        section = SitemapSectionFactory(
            name="product-images-ns",
            model_path="sitemaps_testapp.ProductImage",
            sitemap_type="image",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        # The image namespace must be declared on the urlset element
        assert "sitemap-image" in xml


# ---------------------------------------------------------------------------
# Video sitemaps
# ---------------------------------------------------------------------------


class TestVideoSitemapGeneration:
    def test_generates_video_xml_tags(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import VideoItem

        VideoItem.objects.create(
            title="Intro Video",
            slug="intro-video",
            video_url="https://cdn.example.com/intro.mp4",
            thumbnail_url="https://cdn.example.com/intro-thumb.jpg",
            description="An introduction video",
            duration_seconds=120,
        )

        section = SitemapSectionFactory(
            name="videos-xml",
            model_path="sitemaps_testapp.VideoItem",
            sitemap_type="video",
            is_stale=True,
        )

        with _apply_conf_patches():
            url_count = generate_section(section)

        assert url_count == 1

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "video:video" in xml

    def test_video_thumbnail_loc_in_xml(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import VideoItem

        VideoItem.objects.create(
            title="Promo Video",
            slug="promo-video",
            video_url="https://cdn.example.com/promo.mp4",
            thumbnail_url="https://cdn.example.com/promo-thumb.jpg",
            description="Promo",
            duration_seconds=60,
        )

        section = SitemapSectionFactory(
            name="videos-thumbnail",
            model_path="sitemaps_testapp.VideoItem",
            sitemap_type="video",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "video:thumbnail_loc" in xml
        assert "promo-thumb.jpg" in xml

    def test_video_title_in_xml(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import VideoItem

        VideoItem.objects.create(
            title="Tutorial Video",
            slug="tutorial-video",
            video_url="https://cdn.example.com/tutorial.mp4",
            thumbnail_url="https://cdn.example.com/tut-thumb.jpg",
            description="A tutorial",
            duration_seconds=300,
        )

        section = SitemapSectionFactory(
            name="videos-title",
            model_path="sitemaps_testapp.VideoItem",
            sitemap_type="video",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "video:title" in xml
        assert "Tutorial Video" in xml

    def test_video_description_in_xml(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import VideoItem

        VideoItem.objects.create(
            title="Demo Video",
            slug="demo-video",
            video_url="https://cdn.example.com/demo.mp4",
            thumbnail_url="https://cdn.example.com/demo-thumb.jpg",
            description="A demo of the product features",
            duration_seconds=180,
        )

        section = SitemapSectionFactory(
            name="videos-description",
            model_path="sitemaps_testapp.VideoItem",
            sitemap_type="video",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "video:description" in xml
        assert "A demo of the product features" in xml

    def test_video_content_loc_in_xml(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import VideoItem

        VideoItem.objects.create(
            title="Feature Video",
            slug="feature-video",
            video_url="https://cdn.example.com/feature.mp4",
            thumbnail_url="https://cdn.example.com/feat-thumb.jpg",
            description="Feature overview",
            duration_seconds=240,
        )

        section = SitemapSectionFactory(
            name="videos-content",
            model_path="sitemaps_testapp.VideoItem",
            sitemap_type="video",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "video:content_loc" in xml
        assert "feature.mp4" in xml

    def test_video_namespace_declared(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import VideoItem

        VideoItem.objects.create(
            title="NS Check Video",
            slug="ns-check-video",
            video_url="https://cdn.example.com/ns.mp4",
            thumbnail_url="https://cdn.example.com/ns-thumb.jpg",
            description="NS test",
            duration_seconds=10,
        )

        section = SitemapSectionFactory(
            name="videos-ns",
            model_path="sitemaps_testapp.VideoItem",
            sitemap_type="video",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "sitemap-video" in xml


# ---------------------------------------------------------------------------
# News sitemaps
# ---------------------------------------------------------------------------


class TestNewsSitemapGeneration:
    def test_generates_news_xml_tags(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.utils import timezone
        from sitemaps_testapp.models import NewsItem

        NewsItem.objects.create(
            title="Breaking News Story",
            slug="breaking-news",
            published_at=timezone.now(),
        )

        section = SitemapSectionFactory(
            name="news-xml",
            model_path="sitemaps_testapp.NewsItem",
            sitemap_type="news",
            is_stale=True,
        )

        with _apply_conf_patches():
            url_count = generate_section(section)

        assert url_count == 1

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "news:news" in xml

    def test_news_publication_block_in_xml(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.utils import timezone
        from sitemaps_testapp.models import NewsItem

        NewsItem.objects.create(
            title="Local Story",
            slug="local-story",
            published_at=timezone.now(),
        )

        section = SitemapSectionFactory(
            name="news-publication",
            model_path="sitemaps_testapp.NewsItem",
            sitemap_type="news",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "news:publication" in xml
        assert "news:name" in xml
        assert "Test Publication" in xml
        assert "news:language" in xml

    def test_news_publication_date_in_xml(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.utils import timezone
        from sitemaps_testapp.models import NewsItem

        NewsItem.objects.create(
            title="Dated Story",
            slug="dated-story",
            published_at=timezone.now(),
        )

        section = SitemapSectionFactory(
            name="news-pubdate",
            model_path="sitemaps_testapp.NewsItem",
            sitemap_type="news",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "news:publication_date" in xml

    def test_news_title_in_xml(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.utils import timezone
        from sitemaps_testapp.models import NewsItem

        NewsItem.objects.create(
            title="Unique Headline Here",
            slug="unique-headline",
            published_at=timezone.now(),
        )

        section = SitemapSectionFactory(
            name="news-title",
            model_path="sitemaps_testapp.NewsItem",
            sitemap_type="news",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "news:title" in xml
        assert "Unique Headline Here" in xml

    def test_news_max_age_cutoff_excludes_old_items(self, db, tmp_path, settings):
        """Items older than ICV_SITEMAPS_NEWS_MAX_AGE_DAYS must be excluded."""
        settings.MEDIA_ROOT = str(tmp_path)

        from django.utils import timezone
        from sitemaps_testapp.models import NewsItem

        NewsItem.objects.create(
            title="Recent News",
            slug="recent-news",
            published_at=timezone.now(),
        )
        NewsItem.objects.create(
            title="Old Stale News",
            slug="old-stale-news",
            # Published 10 days ago — well outside the 2-day cutoff
            published_at=timezone.now() - timezone.timedelta(days=10),
        )

        section = SitemapSectionFactory(
            name="news-maxage",
            model_path="sitemaps_testapp.NewsItem",
            sitemap_type="news",
            is_stale=True,
        )

        with _apply_conf_patches():
            # NEWS_MAX_AGE_DAYS=2 means only items within last 2 days
            url_count = generate_section(section)

        assert url_count == 1  # Only the recent item

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "Recent News" in xml
        assert "Old Stale News" not in xml

    def test_news_within_age_included(self, db, tmp_path, settings):
        """Items within the max-age window must be included."""
        settings.MEDIA_ROOT = str(tmp_path)

        from django.utils import timezone
        from sitemaps_testapp.models import NewsItem

        # Within 2-day window
        NewsItem.objects.create(
            title="Fresh Story",
            slug="fresh-story",
            published_at=timezone.now() - timezone.timedelta(hours=12),
        )

        section = SitemapSectionFactory(
            name="news-within-age",
            model_path="sitemaps_testapp.NewsItem",
            sitemap_type="news",
            is_stale=True,
        )

        with _apply_conf_patches():
            url_count = generate_section(section)

        assert url_count == 1

    def test_news_namespace_declared(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.utils import timezone
        from sitemaps_testapp.models import NewsItem

        NewsItem.objects.create(
            title="NS News",
            slug="ns-news",
            published_at=timezone.now(),
        )

        section = SitemapSectionFactory(
            name="news-ns",
            model_path="sitemaps_testapp.NewsItem",
            sitemap_type="news",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "sitemap-news" in xml


# ---------------------------------------------------------------------------
# Empty sections
# ---------------------------------------------------------------------------


class TestEmptySectionGeneration:
    def test_empty_section_writes_file(self, db, tmp_path, settings):
        """Generating a section with no records creates a valid empty urlset file."""
        settings.MEDIA_ROOT = str(tmp_path)

        # No articles created — queryset will be empty

        section = SitemapSectionFactory(
            name="empty-articles",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with _apply_conf_patches():
            url_count = generate_section(section)

        assert url_count == 0

        # An empty urlset file is still written (TS-012 behaviour)
        sitemap_file = SitemapFile.objects.filter(section=section).first()
        assert sitemap_file is not None

    def test_empty_section_xml_is_valid_urlset(self, db, tmp_path, settings):
        """The empty urlset file must be valid XML."""
        settings.MEDIA_ROOT = str(tmp_path)

        section = SitemapSectionFactory(
            name="empty-articles-valid",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.filter(section=section).first()
        if sitemap_file is None:
            pytest.skip("Implementation does not write a file for empty sections")

        xml = _read_storage_file(sitemap_file.storage_path)

        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml)
        assert root.tag is not None

    def test_empty_section_has_zero_url_count(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        section = SitemapSectionFactory(
            name="empty-articles-count",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        section.refresh_from_db()
        assert section.url_count == 0
        assert section.is_stale is False
