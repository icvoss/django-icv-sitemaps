"""Tests for hreflang alternates (issue #35): the SitemapMixin contract,
static-section entries, rendering order, escaping and the sizing
interaction. Also covers a required key missing anywhere in the entry-dict
contract raising SitemapGenerationError instead of a bare KeyError (issue
#66): a missing alternate hreflang/href, a missing static-entry loc, and a
missing image loc, plus the message-truncation bound on each.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from icv_sitemaps.exceptions import SitemapGenerationError
from icv_sitemaps.mixins import SitemapMixin
from icv_sitemaps.models import SitemapFile, SitemapGenerationLog
from icv_sitemaps.services import generate_section
from icv_sitemaps.services.generation import (
    _ENTRY_REPR_LIMIT,
    _extract_entry,
    _normalise_alternates,
    _normalise_static_entry,
)
from icv_sitemaps.testing.factories import SitemapSectionFactory, StaticSitemapSectionFactory

# ---------------------------------------------------------------------------
# Shared conf-patching helper (same shape as test_generation_types.py)
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
# a. Default is empty, on the mixin and through _extract_entry
# ---------------------------------------------------------------------------


class TestDefaultIsEmpty:
    def test_mixin_default_alternates_is_empty(self):
        assert SitemapMixin().get_sitemap_alternates() == []

    def test_extract_entry_default_alternates_is_empty(self, db):
        from sitemaps_testapp.models import Article

        article = Article.objects.create(title="Plain", slug="plain")

        entry = _extract_entry(article, "standard", "https://example.com")

        assert entry["alternates"] == []


# ---------------------------------------------------------------------------
# b. Model-provided alternates render on a standard section
# ---------------------------------------------------------------------------


class TestModelProvidedAlternates:
    def test_standard_section_renders_alternates_after_priority(self, db, tmp_path, settings, monkeypatch):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import Article

        Article.objects.create(title="Bonjour", slug="bonjour")

        monkeypatch.setattr(
            Article,
            "get_sitemap_alternates",
            lambda self: [
                {"hreflang": "fr", "href": "/fr/bonjour/"},
                {"hreflang": "x-default", "href": "/bonjour/"},
            ],
            raising=False,
        )

        section = SitemapSectionFactory(
            name="articles-alternates",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert xml.count('<xhtml:link rel="alternate"') == 2
        assert 'hreflang="fr" href="https://example.com/fr/bonjour/"' in xml
        assert 'hreflang="x-default" href="https://example.com/bonjour/"' in xml
        assert xml.count('xmlns:xhtml="http://www.w3.org/1999/xhtml"') == 1

        # The alternates land after </priority> and before </url>.
        priority_end = xml.index("</priority>")
        url_end = xml.index("</url>")
        first_link = xml.index("<xhtml:link")
        assert priority_end < first_link < url_end


# ---------------------------------------------------------------------------
# c. Alternates before the image extension block, and on a static section
# ---------------------------------------------------------------------------


class TestAlternatesBeforeExtensionBlocks:
    def test_image_section_alternates_before_image_block(self, db, tmp_path, settings, monkeypatch):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import ProductImage

        ProductImage.objects.create(
            title="Widget",
            slug="widget",
            image_url="https://cdn.example.com/widget.jpg",
            caption="A widget",
        )

        monkeypatch.setattr(
            ProductImage,
            "get_sitemap_alternates",
            lambda self: [{"hreflang": "de", "href": "/de/widget/"}],
            raising=False,
        )

        section = SitemapSectionFactory(
            name="images-alternates",
            model_path="sitemaps_testapp.ProductImage",
            sitemap_type="image",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        link_pos = xml.index("<xhtml:link")
        image_pos = xml.index("<image:image>")
        assert link_pos < image_pos

    def test_static_section_entry_alternates_key(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="static-alternates",
            settings={
                "urls": [
                    {
                        "loc": "/pricing/",
                        "alternates": [{"hreflang": "de", "href": "/de/pricing/"}],
                    }
                ]
            },
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert xml.count('<xhtml:link rel="alternate"') == 1
        assert 'hreflang="de" href="https://example.com/de/pricing/"' in xml


# ---------------------------------------------------------------------------
# d. Escaping
# ---------------------------------------------------------------------------


class TestAlternatesEscaping:
    def test_href_with_quote_and_ampersand_is_escaped_and_parses(self, db, tmp_path, settings, monkeypatch):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import Article

        Article.objects.create(title="Escaped", slug="escaped")

        monkeypatch.setattr(
            Article,
            "get_sitemap_alternates",
            lambda self: [{"hreflang": "en", "href": '/search/?q="a"&b=1'}],
            raising=False,
        )

        section = SitemapSectionFactory(
            name="articles-escape",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert "&quot;" in xml
        assert "&amp;" in xml
        # Must parse: an unescaped '"' inside an attribute or a bare '&'
        # would break the document.
        ET.fromstring(xml)


# ---------------------------------------------------------------------------
# e. No alternates still declares the namespace once, emits no xhtml:link
# ---------------------------------------------------------------------------


class TestNoAlternatesStillDeclaresNamespace:
    def test_standard_section_no_alternates(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        from sitemaps_testapp.models import Article

        Article.objects.create(title="No Alts", slug="no-alts")

        section = SitemapSectionFactory(
            name="articles-no-alternates",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        with _apply_conf_patches():
            generate_section(section)

        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)

        assert xml.count('xmlns:xhtml="http://www.w3.org/1999/xhtml"') == 1
        assert "xhtml:link" not in xml


# ---------------------------------------------------------------------------
# f. A required key missing anywhere in the entry-dict contract raises
# SitemapGenerationError naming the section, sitemap_type and offending
# entry, instead of a bare KeyError (issue #66).
# ---------------------------------------------------------------------------


class TestNormaliseAlternatesMissingRequiredKey:
    def test_missing_href_raises_sitemap_generation_error(self):
        section = SitemapSectionFactory.build(name="alt-section")

        with pytest.raises(SitemapGenerationError) as exc_info:
            _normalise_alternates(
                [{"hreflang": "de"}],
                "https://example.com",
                section=section,
                sitemap_type="standard",
            )

        message = str(exc_info.value)
        assert "alt-section" in message
        assert "standard" in message
        assert "href" in message

    def test_missing_hreflang_raises_sitemap_generation_error(self):
        section = SitemapSectionFactory.build(name="alt-section")

        with pytest.raises(SitemapGenerationError) as exc_info:
            _normalise_alternates(
                [{"href": "/de/page/"}],
                "https://example.com",
                section=section,
                sitemap_type="standard",
            )

        message = str(exc_info.value)
        assert "alt-section" in message
        assert "standard" in message
        assert "hreflang" in message

    def test_valid_alternate_still_normalises(self):
        """Control: a valid alternate is unaffected by the validation above."""
        section = SitemapSectionFactory.build(name="alt-section")

        result = _normalise_alternates(
            [{"hreflang": "de", "href": "/de/page/"}],
            "https://example.com",
            section=section,
            sitemap_type="standard",
        )

        assert result == [{"hreflang": "de", "href": "https://example.com/de/page/"}]


class TestStaticEntryMissingLoc:
    def test_missing_loc_raises_sitemap_generation_error(self):
        section = SitemapSectionFactory.build(name="static-loc-section")

        with pytest.raises(SitemapGenerationError) as exc_info:
            _normalise_static_entry({"changefreq": "weekly"}, "standard", "https://example.com", section=section)

        message = str(exc_info.value)
        assert "static-loc-section" in message
        assert "standard" in message
        assert "loc" in message

    def test_generate_section_records_failure_for_missing_loc(self, db, tmp_path, settings):
        """End-to-end: generate_section() still fails the section via
        BR-OPS-001, and the recorded detail now names the section and key
        rather than being the bare string 'loc'.
        """
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="static-loc-missing",
            settings={"urls": [{"changefreq": "weekly"}]},
        )

        with _apply_conf_patches(), pytest.raises(SitemapGenerationError):
            generate_section(section)

        log = SitemapGenerationLog.objects.filter(section=section, action="generate_section").last()
        assert log is not None
        assert log.status == "failed"
        assert log.detail != "loc"
        assert "static-loc-missing" in log.detail
        assert "loc" in log.detail
        assert not SitemapFile.objects.filter(section=section).exists()

    def test_valid_static_entry_still_generates(self, db, tmp_path, settings):
        """Control: a valid static entry (with 'loc') still generates
        correctly, unaffected by the validation above.
        """
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="static-loc-valid",
            settings={"urls": [{"loc": "/pricing/"}]},
        )

        with _apply_conf_patches():
            url_count = generate_section(section)

        assert url_count == 1
        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)
        assert "<loc>https://example.com/pricing/</loc>" in xml


class TestImageMissingLoc:
    """An image dict inside a static entry's 'images' list is passed through
    unvalidated by _normalise_static_entry and only read at render time
    (_render_image_url), so the missing-key check has to live at the render
    call sites in _generate_streaming / _generate_buffered instead.
    """

    @pytest.mark.parametrize("streaming", [True, False])
    def test_missing_image_loc_raises_sitemap_generation_error(self, db, tmp_path, settings, streaming):
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="static-image-loc-missing",
            sitemap_type="image",
            settings={
                "urls": [
                    {
                        "loc": "/gallery/",
                        "images": [{"caption": "no loc here"}],
                    }
                ]
            },
        )

        with (
            _apply_conf_patches(),
            patch("icv_sitemaps.conf.ICV_SITEMAPS_STREAMING_WRITER", streaming),
            pytest.raises(SitemapGenerationError) as exc_info,
        ):
            generate_section(section)

        message = str(exc_info.value)
        assert "static-image-loc-missing" in message
        assert "image" in message
        assert "loc" in message

    @pytest.mark.parametrize("streaming", [True, False])
    def test_valid_image_entry_still_generates(self, db, tmp_path, settings, streaming):
        """Control: a valid image entry (with 'loc') still generates
        correctly on both the streaming and buffered writers.
        """
        settings.MEDIA_ROOT = str(tmp_path)

        section = StaticSitemapSectionFactory(
            name="static-image-loc-valid",
            sitemap_type="image",
            settings={
                "urls": [
                    {
                        "loc": "/gallery/",
                        "images": [{"loc": "https://cdn.example.com/gallery.jpg"}],
                    }
                ]
            },
        )

        with _apply_conf_patches(), patch("icv_sitemaps.conf.ICV_SITEMAPS_STREAMING_WRITER", streaming):
            url_count = generate_section(section)

        assert url_count == 1
        sitemap_file = SitemapFile.objects.get(section=section)
        xml = _read_storage_file(sitemap_file.storage_path)
        assert "<image:loc>https://cdn.example.com/gallery.jpg</image:loc>" in xml


# ---------------------------------------------------------------------------
# g. The offending entry embedded in the message is truncated, never
# interpolated unbounded (issue #66).
# ---------------------------------------------------------------------------


class TestEntryReprTruncation:
    def test_oversized_static_entry_message_is_bounded(self):
        section = SitemapSectionFactory.build(name="truncation-section")
        oversized = {"changefreq": "x" * 5000}

        with pytest.raises(SitemapGenerationError) as exc_info:
            _normalise_static_entry(oversized, "standard", "https://example.com", section=section)

        message = str(exc_info.value)
        # The message carries a short prefix plus the truncated repr; it
        # must stay well short of the 5000-character input regardless of
        # exactly how the prefix is worded.
        assert len(message) < _ENTRY_REPR_LIMIT + 300
        assert "...(truncated)" in message

    def test_oversized_alternate_message_is_bounded(self):
        section = SitemapSectionFactory.build(name="truncation-section")
        oversized = {"hreflang": "de", "href_typo": "x" * 5000}

        with pytest.raises(SitemapGenerationError) as exc_info:
            _normalise_alternates([oversized], "https://example.com", section=section, sitemap_type="standard")

        message = str(exc_info.value)
        assert len(message) < _ENTRY_REPR_LIMIT + 300
        assert "...(truncated)" in message
