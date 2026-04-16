"""Tests for the streaming XML writer and multi-file splitting.

These tests exercise the ``_StreamingSitemapWriter``-based generation path
(default) and the buffered fallback (``ICV_SITEMAPS_STREAMING_WRITER=False``),
asserting:

- generated XML is well-formed and parseable
- multi-file splitting fires correctly on URL-count limits
- gzip and non-gzip storage paths both work
- both code paths produce equivalent SitemapFile records

The ElementTree parse step catches regressions like the duplicate
``xmlns:image`` declaration that ElementTree's namespace registration
magic used to emit.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from django.core.files.storage import default_storage

from icv_sitemaps.models import SitemapFile
from icv_sitemaps.services import generate_section
from icv_sitemaps.testing.factories import SitemapSectionFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CONF = {
    "ICV_SITEMAPS_GZIP": False,
    "ICV_SITEMAPS_STORAGE_PATH": "sitemaps/",
    "ICV_SITEMAPS_BASE_URL": "https://example.com",
    "ICV_SITEMAPS_MAX_URLS_PER_FILE": 50000,
    "ICV_SITEMAPS_MAX_FILE_SIZE_BYTES": 52428800,
    "ICV_SITEMAPS_BATCH_SIZE": 5000,
    "ICV_SITEMAPS_PING_ENABLED": False,
    "ICV_SITEMAPS_NEWS_MAX_AGE_DAYS": 2,
    "ICV_SITEMAPS_STREAMING_WRITER": True,
}


def _apply(overrides: dict | None = None) -> ExitStack:
    """Apply conf-module patches for the duration of a test."""
    import icv_sitemaps.conf as conf_mod

    patches = {**_BASE_CONF, **(overrides or {})}
    stack = ExitStack()
    for attr, value in patches.items():
        stack.enter_context(patch.object(conf_mod, attr, value))
    return stack


def _read_bytes(storage_path: str) -> bytes:
    with default_storage.open(storage_path, "rb") as fh:
        return fh.read()


def _read_xml(storage_path: str) -> bytes:
    raw = _read_bytes(storage_path)
    if storage_path.endswith(".gz"):
        raw = gzip.decompress(raw)
    return raw


def _parse(storage_path: str) -> ET.Element:
    """Parse the generated file as XML. Raises ParseError on malformed output."""
    return ET.fromstring(_read_xml(storage_path))


# ---------------------------------------------------------------------------
# Well-formedness — every generated shard must parse as valid XML
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("streaming", [True, False])
class TestXmlWellFormedness:
    def test_standard_is_well_formed(self, db, tmp_path, settings, streaming):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import Article

        for i in range(3):
            Article.objects.create(title=f"A{i}", slug=f"a-{i}")

        section = SitemapSectionFactory(
            name="articles-wf",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with _apply({"ICV_SITEMAPS_STREAMING_WRITER": streaming}):
            generate_section(section)

        sf = SitemapFile.objects.get(section=section)
        root = _parse(sf.storage_path)
        assert root.tag.endswith("urlset")
        urls = list(root)
        assert len(urls) == 3

    def test_image_is_well_formed(self, db, tmp_path, settings, streaming):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import ProductImage

        ProductImage.objects.create(
            title="Widget",
            slug="widget",
            image_url="https://cdn.example.com/widget.jpg",
            caption="A widget",
        )

        section = SitemapSectionFactory(
            name="images-wf",
            model_path="sitemaps_testapp.ProductImage",
            sitemap_type="image",
            is_stale=True,
        )

        with _apply({"ICV_SITEMAPS_STREAMING_WRITER": streaming}):
            generate_section(section)

        sf = SitemapFile.objects.get(section=section)
        xml = _read_xml(sf.storage_path).decode("utf-8")
        # No duplicate xmlns:image declaration (the ElementTree-era bug).
        assert xml.count('xmlns:image="') == 1

        root = _parse(sf.storage_path)
        # Namespace must be declared exactly once on the root.
        assert "urlset" in root.tag

    def test_video_is_well_formed(self, db, tmp_path, settings, streaming):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import VideoItem

        VideoItem.objects.create(
            title="Demo",
            slug="demo",
            video_url="https://cdn.example.com/demo.mp4",
            thumbnail_url="https://cdn.example.com/demo.jpg",
            description="Demo video",
            duration_seconds=120,
        )

        section = SitemapSectionFactory(
            name="videos-wf",
            model_path="sitemaps_testapp.VideoItem",
            sitemap_type="video",
            is_stale=True,
        )

        with _apply({"ICV_SITEMAPS_STREAMING_WRITER": streaming}):
            generate_section(section)

        sf = SitemapFile.objects.get(section=section)
        xml = _read_xml(sf.storage_path).decode("utf-8")
        assert xml.count('xmlns:video="') == 1
        _parse(sf.storage_path)  # must not raise


# ---------------------------------------------------------------------------
# XML escaping — user strings containing XML metacharacters
# ---------------------------------------------------------------------------


class TestXmlEscaping:
    def test_ampersand_in_title_is_escaped(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import ProductImage

        ProductImage.objects.create(
            title="Tom & Jerry",
            slug="tom-and-jerry",
            image_url="https://cdn.example.com/p.jpg?a=1&b=2",
            caption="Crocodiles < alligators & other reptiles",
        )

        section = SitemapSectionFactory(
            name="images-escape",
            model_path="sitemaps_testapp.ProductImage",
            sitemap_type="image",
            is_stale=True,
        )

        with _apply():
            generate_section(section)

        sf = SitemapFile.objects.get(section=section)
        # Must parse — unescaped '&' would raise ParseError.
        _parse(sf.storage_path)


# ---------------------------------------------------------------------------
# Multi-file splitting — URL-count limit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("streaming", [True, False])
class TestMultiFileSplit:
    def test_splits_on_url_count_limit(self, db, tmp_path, settings, streaming):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import Article

        # Create 7 URLs, limit to 3 per file → expect 3 shards (3 + 3 + 1).
        for i in range(7):
            Article.objects.create(title=f"Article {i}", slug=f"article-{i}")

        section = SitemapSectionFactory(
            name="articles-split",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with _apply(
            {
                "ICV_SITEMAPS_MAX_URLS_PER_FILE": 3,
                "ICV_SITEMAPS_STREAMING_WRITER": streaming,
            }
        ):
            url_count = generate_section(section)

        assert url_count == 7

        files = list(SitemapFile.objects.filter(section=section).order_by("sequence"))
        assert len(files) == 3
        assert [f.url_count for f in files] == [3, 3, 1]
        assert [f.sequence for f in files] == [0, 1, 2]

        # Every shard must parse and contain the expected count.
        for f, expected in zip(files, [3, 3, 1], strict=True):
            root = _parse(f.storage_path)
            assert len(list(root)) == expected

    def test_empty_section_emits_single_empty_urlset(self, db, tmp_path, settings, streaming):
        settings.MEDIA_ROOT = str(tmp_path)

        section = SitemapSectionFactory(
            name="articles-empty",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with _apply({"ICV_SITEMAPS_STREAMING_WRITER": streaming}):
            url_count = generate_section(section)

        assert url_count == 0
        files = list(SitemapFile.objects.filter(section=section))
        assert len(files) == 1
        assert files[0].url_count == 0
        root = _parse(files[0].storage_path)
        assert len(list(root)) == 0


# ---------------------------------------------------------------------------
# Gzip handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("streaming", [True, False])
class TestGzip:
    def test_gzip_output_is_decompressable_and_parseable(self, db, tmp_path, settings, streaming):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import Article

        for i in range(5):
            Article.objects.create(title=f"A{i}", slug=f"a-{i}")

        section = SitemapSectionFactory(
            name="articles-gz",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with _apply(
            {
                "ICV_SITEMAPS_GZIP": True,
                "ICV_SITEMAPS_STREAMING_WRITER": streaming,
            }
        ):
            generate_section(section)

        sf = SitemapFile.objects.get(section=section)
        assert sf.storage_path.endswith(".xml.gz")
        root = _parse(sf.storage_path)
        assert len(list(root)) == 5


# ---------------------------------------------------------------------------
# Equivalence between streaming and buffered paths
# ---------------------------------------------------------------------------


class TestStreamingBufferedEquivalence:
    """Same input → same URL count, same file count, same parseable structure."""

    def _generate_with(self, streaming: bool, section_name: str, db_seed: int):
        section = SitemapSectionFactory(
            name=section_name,
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with _apply(
            {
                "ICV_SITEMAPS_MAX_URLS_PER_FILE": 4,
                "ICV_SITEMAPS_STREAMING_WRITER": streaming,
            }
        ):
            generate_section(section)

        return list(SitemapFile.objects.filter(section=section).order_by("sequence"))

    def test_streaming_and_buffered_produce_same_shape(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import Article

        for i in range(10):
            Article.objects.create(title=f"Article {i}", slug=f"a-{i}")

        streaming_files = self._generate_with(True, "articles-stream", 10)
        # Clear so the next run re-generates under the same slugs.
        Article.objects.all().delete()
        for i in range(10):
            Article.objects.create(title=f"Article {i}", slug=f"b-{i}")
        buffered_files = self._generate_with(False, "articles-buffered", 10)

        assert [f.url_count for f in streaming_files] == [f.url_count for f in buffered_files]
        assert [f.sequence for f in streaming_files] == [f.sequence for f in buffered_files]
        # Each pair of corresponding files must parse to the same number of <url>s.
        for s, b in zip(streaming_files, buffered_files, strict=True):
            assert len(list(_parse(s.storage_path))) == len(list(_parse(b.storage_path)))
