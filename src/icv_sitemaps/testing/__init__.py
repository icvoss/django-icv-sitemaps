"""
Testing utilities for icv-sitemaps.

Import factories and fixtures from this package in your test suite::

    from icv_sitemaps.testing.factories import SitemapSectionFactory
    from icv_sitemaps.testing.fixtures import sitemap_section  # pytest fixture

Factories are not imported at the module level here to avoid triggering
Django app registry access before ``django.setup()`` has been called.
"""

__all__ = [
    "SitemapSectionFactory",
    "SitemapFileFactory",
    "SitemapGenerationLogFactory",
    "RobotsRuleFactory",
    "AdsEntryFactory",
    "DiscoveryFileConfigFactory",
]
