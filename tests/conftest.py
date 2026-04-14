"""Shared pytest fixtures for icv-sitemaps tests."""

import pytest


def pytest_configure(config):
    """Ensure sitemaps_testapp is in INSTALLED_APPS when running from the project root."""
    from django.conf import settings

    if not settings.configured:
        return
    if "sitemaps_testapp" not in settings.INSTALLED_APPS:
        settings.INSTALLED_APPS = [*settings.INSTALLED_APPS, "sitemaps_testapp"]
    if not hasattr(settings, "MIGRATION_MODULES"):
        settings.MIGRATION_MODULES = {}
    settings.MIGRATION_MODULES.setdefault("sitemaps_testapp", None)


@pytest.fixture
def sitemap_section(db):
    """A saved SitemapSection instance."""
    from icv_sitemaps.testing.factories import SitemapSectionFactory

    return SitemapSectionFactory()


@pytest.fixture
def sitemap_file(db):
    """A saved SitemapFile instance."""
    from icv_sitemaps.testing.factories import SitemapFileFactory

    return SitemapFileFactory()


@pytest.fixture
def sitemap_generation_log(db):
    """A saved SitemapGenerationLog instance."""
    from icv_sitemaps.testing.factories import SitemapGenerationLogFactory

    return SitemapGenerationLogFactory()


@pytest.fixture
def robots_rule(db):
    """A saved RobotsRule instance."""
    from icv_sitemaps.testing.factories import RobotsRuleFactory

    return RobotsRuleFactory()


@pytest.fixture
def ads_entry(db):
    """A saved AdsEntry instance."""
    from icv_sitemaps.testing.factories import AdsEntryFactory

    return AdsEntryFactory()


@pytest.fixture
def discovery_file_config(db):
    """A saved DiscoveryFileConfig instance."""
    from icv_sitemaps.testing.factories import DiscoveryFileConfigFactory

    return DiscoveryFileConfigFactory()


@pytest.fixture
def redirect_rule(db):
    """A saved RedirectRule instance."""
    from icv_sitemaps.testing.factories import RedirectRuleFactory

    return RedirectRuleFactory()


@pytest.fixture
def redirect_log(db):
    """A saved RedirectLog instance."""
    from icv_sitemaps.testing.factories import RedirectLogFactory

    return RedirectLogFactory()
