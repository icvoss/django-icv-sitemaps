"""factory-boy factories for icv-sitemaps models."""

import factory
import factory.django


class SitemapSectionFactory(factory.django.DjangoModelFactory):
    """Factory for SitemapSection."""

    name = factory.Sequence(lambda n: f"section-{n}")
    tenant_id = ""
    model_path = "icv_sitemaps.testing.helpers.DummySitemapModel"
    sitemap_type = "standard"
    changefreq = "daily"
    priority = "0.5"
    is_active = True
    is_stale = True
    url_count = 0
    file_count = 0
    settings = factory.LazyFunction(dict)

    class Meta:
        model = "icv_sitemaps.SitemapSection"


class SitemapFileFactory(factory.django.DjangoModelFactory):
    """Factory for SitemapFile."""

    section = factory.SubFactory(SitemapSectionFactory)
    sequence = factory.Sequence(lambda n: n)
    storage_path = factory.LazyAttribute(lambda o: f"sitemaps/{o.section.name}-{o.sequence}.xml")
    url_count = 0
    file_size_bytes = 0
    checksum = ""

    class Meta:
        model = "icv_sitemaps.SitemapFile"


class SitemapGenerationLogFactory(factory.django.DjangoModelFactory):
    """Factory for SitemapGenerationLog."""

    section = factory.SubFactory(SitemapSectionFactory)
    action = "generate_section"
    status = "success"
    url_count = 0
    file_count = 0
    duration_ms = 0
    detail = ""

    class Meta:
        model = "icv_sitemaps.SitemapGenerationLog"


class RobotsRuleFactory(factory.django.DjangoModelFactory):
    """Factory for RobotsRule."""

    tenant_id = ""
    user_agent = "*"
    directive = "disallow"
    path = "/admin/"
    order = factory.Sequence(lambda n: n)
    is_active = True
    comment = ""

    class Meta:
        model = "icv_sitemaps.RobotsRule"


class AdsEntryFactory(factory.django.DjangoModelFactory):
    """Factory for AdsEntry."""

    tenant_id = ""
    domain = factory.Sequence(lambda n: f"ad-network-{n}.com")
    publisher_id = factory.Sequence(lambda n: f"pub-{n:08d}")
    relationship = "DIRECT"
    certification_id = ""
    is_app_ads = False
    is_active = True
    comment = ""

    class Meta:
        model = "icv_sitemaps.AdsEntry"


class DiscoveryFileConfigFactory(factory.django.DjangoModelFactory):
    """Factory for DiscoveryFileConfig.

    ``DiscoveryFileConfig`` has a unique constraint on ``(file_type, tenant_id)``.
    The factory uses ``django_get_or_create`` so that tests which create the same
    combination do not raise ``IntegrityError`` when run in random order.
    """

    tenant_id = ""
    file_type = "llms_txt"
    content = "# llms.txt\n"
    is_active = True
    last_modified_by = None

    class Meta:
        model = "icv_sitemaps.DiscoveryFileConfig"
        django_get_or_create = ("file_type", "tenant_id")


class RedirectRuleFactory(factory.django.DjangoModelFactory):
    """Factory for RedirectRule."""

    name = factory.Sequence(lambda n: f"redirect-{n}")
    tenant_id = ""
    match_type = "exact"
    source_pattern = factory.Sequence(lambda n: f"/old-path-{n}/")
    destination = factory.Sequence(lambda n: f"/new-path-{n}/")
    status_code = 301
    preserve_query_string = True
    is_active = True
    priority = factory.Sequence(lambda n: n)
    source = "admin"
    notes = ""

    class Meta:
        model = "icv_sitemaps.RedirectRule"


class RedirectLogFactory(factory.django.DjangoModelFactory):
    """Factory for RedirectLog."""

    path = factory.Sequence(lambda n: f"/missing-{n}/")
    tenant_id = ""
    hit_count = 1
    referrers = factory.LazyFunction(dict)
    resolved = False

    class Meta:
        model = "icv_sitemaps.RedirectLog"
