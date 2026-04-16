"""
icv-sitemaps — Scalable sitemap generation and web discovery infrastructure for Django.
"""

__version__ = "0.5.0"

default_app_config = "icv_sitemaps.apps.IcvSitemapsConfig"

from icv_sitemaps.mixins import SitemapMixin  # noqa: E402

__all__ = [
    "SitemapMixin",
]
