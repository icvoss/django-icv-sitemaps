"""Tests for icv-sitemaps models."""

import uuid

import pytest

from icv_sitemaps.models import (
    AdsEntry,
    DiscoveryFileConfig,
    RobotsRule,
    SitemapFile,
    SitemapGenerationLog,
    SitemapSection,
)


class TestSitemapSection:
    def test_create_section(self, db):
        section = SitemapSection.objects.create(
            name="products",
            model_path="myapp.models.Product",
            sitemap_type="standard",
            changefreq="weekly",
            priority="0.8",
        )
        assert section.pk is not None
        assert isinstance(section.pk, uuid.UUID)
        assert str(section) == "products (standard)"

    def test_default_fields(self, db):
        section = SitemapSection.objects.create(
            name="articles",
            model_path="myapp.models.Article",
        )
        assert section.is_active is True
        assert section.is_stale is True
        assert section.url_count == 0
        assert section.file_count == 0
        assert section.tenant_id == ""
        assert section.settings == {}

    def test_name_tenant_unique_constraint(self, db):
        from django.db import IntegrityError

        SitemapSection.objects.create(name="news", model_path="myapp.models.News")
        with pytest.raises(IntegrityError):
            SitemapSection.objects.create(name="news", model_path="myapp.models.News")

    def test_ordering(self, db):
        SitemapSection.objects.create(name="zzz", model_path="a.b.C")
        SitemapSection.objects.create(name="aaa", model_path="a.b.D")
        names = list(SitemapSection.objects.values_list("name", flat=True))
        assert names == ["aaa", "zzz"]


class TestSitemapFile:
    def test_create_file(self, sitemap_section, db):
        sf = SitemapFile.objects.create(
            section=sitemap_section,
            sequence=0,
            storage_path="sitemaps/products-0.xml",
            url_count=500,
        )
        assert str(sf) == f"{sitemap_section.name}-0"

    def test_section_sequence_unique_constraint(self, sitemap_section, db):
        from django.db import IntegrityError

        SitemapFile.objects.create(section=sitemap_section, sequence=0, storage_path="sitemaps/x-0.xml")
        with pytest.raises(IntegrityError):
            SitemapFile.objects.create(section=sitemap_section, sequence=0, storage_path="sitemaps/x-0b.xml")


class TestSitemapGenerationLog:
    def test_create_log(self, sitemap_section, db):
        log = SitemapGenerationLog.objects.create(
            section=sitemap_section,
            action="generate_section",
            status="success",
            url_count=1000,
            duration_ms=250,
        )
        assert "generate_section" in str(log)
        assert "success" in str(log)

    def test_section_null_for_full_run(self, db):
        log = SitemapGenerationLog.objects.create(
            action="generate_all",
            status="success",
        )
        assert log.section is None

    def test_ordering_newest_first(self, db):
        SitemapGenerationLog.objects.create(action="generate_all", status="success")
        log2 = SitemapGenerationLog.objects.create(action="generate_index", status="success")
        pks = list(SitemapGenerationLog.objects.values_list("pk", flat=True))
        assert pks[0] == log2.pk  # newest first


class TestRobotsRule:
    def test_create_rule(self, db):
        rule = RobotsRule.objects.create(
            user_agent="Googlebot",
            directive="disallow",
            path="/api/",
        )
        assert str(rule) == "Googlebot: disallow /api/"

    def test_default_user_agent(self, db):
        rule = RobotsRule.objects.create(directive="disallow", path="/admin/")
        assert rule.user_agent == "*"


class TestAdsEntry:
    def test_create_entry(self, db):
        entry = AdsEntry.objects.create(
            domain="google.com",
            publisher_id="pub-12345678",
            relationship="DIRECT",
        )
        assert str(entry) == "google.com, pub-12345678, DIRECT"

    def test_app_ads_flag(self, db):
        entry = AdsEntry.objects.create(
            domain="criteo.com",
            publisher_id="12345",
            relationship="RESELLER",
            is_app_ads=True,
        )
        assert entry.is_app_ads is True


class TestDiscoveryFileConfig:
    def test_create_config(self, db):
        config = DiscoveryFileConfig.objects.create(
            file_type="llms_txt",
            content="# LLMs\n",
        )
        assert str(config) == "llms.txt (default)"

    def test_file_type_tenant_unique_constraint(self, db):
        from django.db import IntegrityError

        DiscoveryFileConfig.objects.create(file_type="security_txt", content="Contact: ...")
        with pytest.raises(IntegrityError):
            DiscoveryFileConfig.objects.create(file_type="security_txt", content="Contact: ...")

    def test_tenant_scoped_config(self, db):
        DiscoveryFileConfig.objects.create(file_type="humans_txt", tenant_id="tenant-a", content="team a")
        DiscoveryFileConfig.objects.create(file_type="humans_txt", tenant_id="tenant-b", content="team b")
        assert DiscoveryFileConfig.objects.count() == 2
