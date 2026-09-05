"""Fail-closed tenant resolution at the view layer (#56).

A resolver that raises, or returns an unsafe value, must not serve the
single-tenant (``""``) bucket's content with a 200: it must 500, and it must
not populate the cache on the way there. Conf names are import-time
constants (see ``tests/test_storage_routing.py``), so
``ICV_SITEMAPS_TENANT_PREFIX_FUNC`` is patched on ``icv_sitemaps.conf``
directly rather than via ``settings``.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import Client

import icv_sitemaps.conf as conf_mod
from icv_sitemaps.cache import safe_get
from icv_sitemaps.testing.factories import RobotsRuleFactory


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    c = Client()
    c.raise_request_exception = False
    return c


@pytest.mark.parametrize("resolver_path", ["tests.tenant_resolvers.raises", "tests.tenant_resolvers.unsafe"])
class TestTenantResolutionFailsClosed:
    def test_robots_txt_500s_and_does_not_serve_default_tenant(self, client, db, resolver_path):
        """The default (``""``) tenant's RobotsRule content is never returned.

        Fails against pre-#56 code, which caught the resolver failure,
        fell back to ``tenant_id=""`` and served that tenant's rules with a
        200.
        """
        RobotsRuleFactory(tenant_id="", user_agent="*", directive="disallow", path="/default-tenant-secret/")

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", resolver_path),
            patch.object(conf_mod, "ICV_SITEMAPS_CACHE_TIMEOUT", 3600),
        ):
            response = client.get("/robots.txt")

        assert response.status_code == 500
        assert b"/default-tenant-secret/" not in response.content

    def test_robots_txt_cache_holds_nothing_for_the_default_tenant_key(self, client, db, resolver_path):
        """Nothing is cached on the failure path (issue #56 requirement)."""
        RobotsRuleFactory(tenant_id="", user_agent="*", directive="disallow", path="/default-tenant-secret/")

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", resolver_path),
            patch.object(conf_mod, "ICV_SITEMAPS_CACHE_TIMEOUT", 3600),
        ):
            client.get("/robots.txt")

        assert safe_get("icv_sitemaps:robots_txt:") is None

    def test_sitemap_xml_500s(self, client, db, resolver_path, tmp_path, settings):
        """The sitemap index view also fails closed rather than serving the
        default tenant's index."""
        settings.MEDIA_ROOT = str(tmp_path)

        with patch.object(conf_mod, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", resolver_path):
            response = client.get("/sitemap.xml")

        assert response.status_code == 500
