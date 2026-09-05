"""Tests for hreflang alternates (issue #35): the SitemapMixin contract,
static-section entries, rendering order, escaping and the sizing
interaction.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from icv_sitemaps.mixins import SitemapMixin
from icv_sitemaps.models import SitemapFile
from icv_sitemaps.services import generate_section
from icv_sitemaps.services.generation import _extract_entry, _normalise_alternates
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
# f. Missing href raises KeyError
# ---------------------------------------------------------------------------


class TestNormaliseAlternatesMissingHref:
    def test_missing_href_raises_key_error(self):
        with pytest.raises(KeyError):
            _normalise_alternates([{"hreflang": "de"}], "https://example.com")

    def test_missing_hreflang_raises_key_error(self):
        with pytest.raises(KeyError):
            _normalise_alternates([{"href": "/de/page/"}], "https://example.com")
