"""Test helper utilities for icv-sitemaps."""

from __future__ import annotations

from datetime import UTC, datetime


class DummySitemapModel:
    """Minimal in-memory model-like object implementing SitemapMixin protocol.

    Use in tests that need a sitemap-compatible instance without a real DB model.

    Example::

        from icv_sitemaps.testing.helpers import DummySitemapModel

        instance = DummySitemapModel(url="/products/widget/", priority=0.8)
        assert instance.get_sitemap_url() == "/products/widget/"
    """

    sitemap_section_name: str = "test"
    sitemap_type: str = "standard"
    sitemap_changefreq: str = "daily"
    sitemap_priority: float = 0.5

    def __init__(
        self,
        url: str = "/test/",
        lastmod: datetime | None = None,
        priority: float = 0.5,
        changefreq: str = "daily",
    ):
        self._url = url
        self._lastmod = lastmod or datetime(2026, 1, 1, tzinfo=UTC)
        self.sitemap_priority = priority
        self.sitemap_changefreq = changefreq

    def get_absolute_url(self) -> str:
        return self._url

    def get_sitemap_url(self) -> str:
        return self._url

    def get_sitemap_lastmod(self) -> datetime | None:
        return self._lastmod

    def get_sitemap_changefreq(self) -> str:
        return self.sitemap_changefreq

    def get_sitemap_priority(self) -> float:
        return self.sitemap_priority

    def get_sitemap_images(self) -> list[dict]:
        return []

    def get_sitemap_video(self) -> dict | None:
        return None

    def get_sitemap_news(self) -> dict | None:
        return None
