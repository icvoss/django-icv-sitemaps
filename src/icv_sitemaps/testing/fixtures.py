"""pytest fixtures for icv-sitemaps.

Import into your conftest.py::

    from icv_sitemaps.testing.fixtures import *  # noqa: F401, F403
"""

import pytest

from icv_sitemaps.testing.factories import (
    AdsEntryFactory,
    DiscoveryFileConfigFactory,
    RedirectLogFactory,
    RedirectRuleFactory,
    RobotsRuleFactory,
    SitemapFileFactory,
    SitemapGenerationLogFactory,
    SitemapSectionFactory,
)


@pytest.fixture
def sitemap_section(db):
    """A saved SitemapSection instance."""
    return SitemapSectionFactory()


@pytest.fixture
def sitemap_file(db):
    """A saved SitemapFile instance."""
    return SitemapFileFactory()


@pytest.fixture
def sitemap_generation_log(db):
    """A saved SitemapGenerationLog instance."""
    return SitemapGenerationLogFactory()


@pytest.fixture
def robots_rule(db):
    """A saved RobotsRule instance."""
    return RobotsRuleFactory()


@pytest.fixture
def ads_entry(db):
    """A saved AdsEntry instance."""
    return AdsEntryFactory()


@pytest.fixture
def discovery_file_config(db):
    """A saved DiscoveryFileConfig instance."""
    return DiscoveryFileConfigFactory()


@pytest.fixture
def redirect_rule(db):
    """A saved RedirectRule instance."""
    return RedirectRuleFactory()


@pytest.fixture
def redirect_log(db):
    """A saved RedirectLog instance."""
    return RedirectLogFactory()
