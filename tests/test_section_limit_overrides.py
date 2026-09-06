"""Tests for per-section generation-limit overrides (issue #61 part 2).

``SitemapSection.settings`` may carry ``max_urls_per_file``,
``max_file_size_bytes`` and ``gzip`` keys that override the matching
``ICV_SITEMAPS_*`` conf value for that section only. Covers:

- overrides actually change sharding/gzip behaviour at generation time
- invalid overrides are rejected by ``SitemapSection.clean()`` (admin path)
  and by ``_section_limits()`` (generation path, recorded as a failed
  ``SitemapGenerationLog`` rather than raised)
- ``create_section()`` stores valid overrides in ``settings`` and rejects
  invalid ones with ``ValueError``
"""

from __future__ import annotations

import gzip
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage

from icv_sitemaps.exceptions import SitemapGenerationError
from icv_sitemaps.models import SitemapFile, SitemapGenerationLog
from icv_sitemaps.services import create_section, generate_section
from icv_sitemaps.services.generation import _section_limits
from icv_sitemaps.testing.factories import SitemapSectionFactory, StaticSitemapSectionFactory

# ---------------------------------------------------------------------------
# Helpers (mirrors tests/test_streaming_writer.py's _BASE_CONF / _apply)
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


def _read_xml(storage_path: str) -> bytes:
    with default_storage.open(storage_path, "rb") as fh:
        raw = fh.read()
    if storage_path.endswith(".gz"):
        raw = gzip.decompress(raw)
    return raw


def _make_articles(n: int):
    from sitemaps_testapp.models import Article

    for i in range(n):
        Article.objects.create(title=f"A{i}", slug=f"a-{i}")


def _make_captioned_images(n: int):
    from sitemaps_testapp.models import ProductImage

    caption = "x" * 2000
    for i in range(n):
        ProductImage.objects.create(
            title=f"Item {i}",
            slug=f"item-{i}",
            image_url=f"https://cdn.example.com/item-{i}.jpg",
            caption=caption,
        )


# ---------------------------------------------------------------------------
# (a) max_urls_per_file override forces extra shards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("streaming", [True, False])
def test_max_urls_per_file_override_forces_extra_shards(db, tmp_path, settings, streaming):
    settings.MEDIA_ROOT = str(tmp_path)
    _make_articles(5)

    section = SitemapSectionFactory(
        name="articles-max-urls-override",
        model_path="sitemaps_testapp.Article",
        sitemap_type="standard",
        is_stale=True,
        settings={"max_urls_per_file": 2},
    )

    with _apply({"ICV_SITEMAPS_MAX_URLS_PER_FILE": 50000, "ICV_SITEMAPS_STREAMING_WRITER": streaming}):
        url_count = generate_section(section)

    assert url_count == 5
    files = list(SitemapFile.objects.filter(section=section).order_by("sequence"))
    assert [f.url_count for f in files] == [2, 2, 1]


@pytest.mark.parametrize("streaming", [True, False])
def test_reverted_read_uses_conf_not_override_one_shard(db, tmp_path, settings, streaming):
    """Behavioural control: reading the conf value instead of the override
    produces one shard for the same 5 rows, proving (a) actually exercises
    the override rather than a coincidence of defaults."""
    settings.MEDIA_ROOT = str(tmp_path)
    _make_articles(5)

    section = SitemapSectionFactory(
        name="articles-max-urls-control",
        model_path="sitemaps_testapp.Article",
        sitemap_type="standard",
        is_stale=True,
        settings={},  # no override: conf value governs
    )

    with _apply({"ICV_SITEMAPS_MAX_URLS_PER_FILE": 50000, "ICV_SITEMAPS_STREAMING_WRITER": streaming}):
        url_count = generate_section(section)

    assert url_count == 5
    files = list(SitemapFile.objects.filter(section=section).order_by("sequence"))
    assert len(files) == 1
    assert files[0].url_count == 5


# ---------------------------------------------------------------------------
# (b) max_file_size_bytes override forces a split while conf stays default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("streaming", [True, False])
def test_max_file_size_bytes_override_forces_split(db, tmp_path, settings, streaming):
    settings.MEDIA_ROOT = str(tmp_path)
    _make_captioned_images(3)

    section = SitemapSectionFactory(
        name="images-max-bytes-override",
        model_path="sitemaps_testapp.ProductImage",
        sitemap_type="image",
        is_stale=True,
        settings={"max_file_size_bytes": 6000},
    )

    with _apply({"ICV_SITEMAPS_STREAMING_WRITER": streaming}):
        # Conf default (52428800) is left untouched; the section override
        # is what forces the split.
        url_count = generate_section(section)

    assert url_count == 3
    files = list(SitemapFile.objects.filter(section=section).order_by("sequence"))
    assert len(files) == 2
    assert [f.url_count for f in files] == [2, 1]
    for f in files:
        raw = _read_xml(f.storage_path)
        assert len(raw) <= 6000


# ---------------------------------------------------------------------------
# (c) gzip override, both directions, including the empty-section path
# ---------------------------------------------------------------------------


def test_gzip_false_override_beats_conf_true(db, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    _make_articles(2)

    section = SitemapSectionFactory(
        name="articles-gzip-off",
        model_path="sitemaps_testapp.Article",
        sitemap_type="standard",
        is_stale=True,
        settings={"gzip": False},
    )

    with _apply({"ICV_SITEMAPS_GZIP": True}):
        generate_section(section)

    sf = SitemapFile.objects.get(section=section)
    assert sf.storage_path.endswith(".xml")
    assert not sf.storage_path.endswith(".xml.gz")


def test_gzip_true_override_beats_conf_false(db, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    _make_articles(2)

    section = SitemapSectionFactory(
        name="articles-gzip-on",
        model_path="sitemaps_testapp.Article",
        sitemap_type="standard",
        is_stale=True,
        settings={"gzip": True},
    )

    with _apply({"ICV_SITEMAPS_GZIP": False}):
        generate_section(section)

    sf = SitemapFile.objects.get(section=section)
    assert sf.storage_path.endswith(".xml.gz")


def test_gzip_override_applies_to_empty_section_shard(db, tmp_path, settings):
    """A section with zero rows still writes an empty shard (TS-012); the
    override must govern that write path too."""
    settings.MEDIA_ROOT = str(tmp_path)

    section = SitemapSectionFactory(
        name="articles-gzip-empty",
        model_path="sitemaps_testapp.Article",
        sitemap_type="standard",
        is_stale=True,
        settings={"gzip": False},
    )

    with _apply({"ICV_SITEMAPS_GZIP": True}):
        url_count = generate_section(section)

    assert url_count == 0
    sf = SitemapFile.objects.get(section=section)
    assert sf.url_count == 0
    assert sf.storage_path.endswith(".xml")
    assert not sf.storage_path.endswith(".xml.gz")


# ---------------------------------------------------------------------------
# (d) invalid values: clean(), _section_limits(), generate_section()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,value",
    [
        ("max_urls_per_file", 0),
        ("max_urls_per_file", 50001),
        ("max_urls_per_file", "2"),
        ("max_urls_per_file", True),
        ("max_file_size_bytes", 0),
        ("max_file_size_bytes", 52428801),
        ("gzip", "yes"),
    ],
)
def test_clean_rejects_invalid_override(db, key, value):
    section = SitemapSectionFactory.build(
        name="invalid-clean",
        model_path="sitemaps_testapp.Article",
        settings={key: value},
    )
    with pytest.raises(ValidationError) as exc_info:
        section.clean()
    assert "settings" in exc_info.value.message_dict


@pytest.mark.parametrize(
    "key,value",
    [
        ("max_urls_per_file", 0),
        ("max_urls_per_file", 50001),
        ("max_urls_per_file", "2"),
        ("max_urls_per_file", True),
        ("max_file_size_bytes", 0),
        ("max_file_size_bytes", 52428801),
        ("gzip", "yes"),
    ],
)
def test_section_limits_rejects_invalid_override(db, key, value):
    section = SitemapSectionFactory(
        name="invalid-section-limits",
        model_path="sitemaps_testapp.Article",
        settings={key: value},
    )
    with pytest.raises(SitemapGenerationError):
        _section_limits(section)


def test_generate_section_records_failure_for_invalid_override(db, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    _make_articles(1)

    section = SitemapSectionFactory(
        name="invalid-generate",
        model_path="sitemaps_testapp.Article",
        sitemap_type="standard",
        is_stale=True,
        settings={"max_urls_per_file": 0},
    )

    with _apply():
        url_count = generate_section(section)

    assert url_count == 0
    log = SitemapGenerationLog.objects.filter(section=section, action="generate_section").last()
    assert log is not None
    assert log.status == "failed"
    assert "max_urls_per_file" in log.detail
    # No shard should have been written for an invalid-override section.
    assert not SitemapFile.objects.filter(section=section).exists()


# ---------------------------------------------------------------------------
# (e) create_section() stores overrides / rejects out-of-bounds kwargs
# ---------------------------------------------------------------------------


def test_create_section_model_section_stores_limit_overrides(db):
    from sitemaps_testapp.models import Article

    section = create_section(
        "articles-created",
        model_class=Article,
        max_urls_per_file=2,
        gzip=False,
    )

    assert section.settings["max_urls_per_file"] == 2
    assert section.settings["gzip"] is False


def test_create_section_static_section_keeps_urls_and_overrides(db):
    section = create_section(
        "static-created",
        urls=[{"loc": "/a/"}, {"loc": "/b/"}],
        max_urls_per_file=1,
        max_file_size_bytes=1000,
    )

    assert section.settings["urls"] == [{"loc": "/a/"}, {"loc": "/b/"}]
    assert section.settings["max_urls_per_file"] == 1
    assert section.settings["max_file_size_bytes"] == 1000


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_urls_per_file": 0},
        {"max_urls_per_file": 50001},
        {"max_file_size_bytes": 0},
        {"max_file_size_bytes": 52428801},
        {"gzip": "yes"},
    ],
)
def test_create_section_rejects_out_of_bounds_kwarg(db, kwargs):
    from sitemaps_testapp.models import Article

    with pytest.raises(ValueError):
        create_section("articles-invalid-kwarg", model_class=Article, **kwargs)


def test_create_section_without_overrides_leaves_settings_unset(db):
    """No regression: omitting the new kwargs entirely must not add the
    keys to settings (they must be genuinely absent so the fallback path
    in _section_limits actually reads the conf value)."""
    from sitemaps_testapp.models import Article

    section = create_section("articles-no-overrides", model_class=Article)

    assert "max_urls_per_file" not in section.settings
    assert "max_file_size_bytes" not in section.settings
    assert "gzip" not in section.settings


def test_static_section_factory_smoke(db):
    """Confirms the StaticSitemapSectionFactory import used above resolves
    to a real, usable factory (not a stale reference)."""
    section = StaticSitemapSectionFactory()
    assert section.section_type == "static"
