"""Tests for icv-sitemaps Celery tasks."""

import importlib
import sys
from unittest.mock import patch


class TestRegenerateStaleTask:
    """regenerate_stale_sitemaps calls generate_all_sections with force=False."""

    def test_calls_generate_all_sections(self, db):
        from icv_sitemaps.tasks import regenerate_stale_sitemaps

        # Lazy import inside the task — patch at source
        with patch("icv_sitemaps.services.generation.generate_all_sections") as mock_generate:
            mock_generate.return_value = {"articles": 100}

            result = regenerate_stale_sitemaps()

        mock_generate.assert_called_once_with(tenant_id="", force=False)
        assert "articles" in result

    def test_passes_tenant_id(self, db):
        from icv_sitemaps.tasks import regenerate_stale_sitemaps

        with patch("icv_sitemaps.services.generation.generate_all_sections") as mock_generate:
            mock_generate.return_value = {}

            regenerate_stale_sitemaps(tenant_id="tenant-a")

        mock_generate.assert_called_once_with(tenant_id="tenant-a", force=False)


class TestRegenerateAllTask:
    """regenerate_all_sitemaps calls generate_all_sections with force=True."""

    def test_calls_generate_all_sections_with_force(self, db):
        from icv_sitemaps.tasks import regenerate_all_sitemaps

        with patch("icv_sitemaps.services.generation.generate_all_sections") as mock_generate:
            mock_generate.return_value = {"products": 50}

            result = regenerate_all_sitemaps()

        mock_generate.assert_called_once_with(tenant_id="", force=True)
        assert "products" in result

    def test_passes_tenant_id(self, db):
        from icv_sitemaps.tasks import regenerate_all_sitemaps

        with patch("icv_sitemaps.services.generation.generate_all_sections") as mock_generate:
            mock_generate.return_value = {}

            regenerate_all_sitemaps(tenant_id="tenant-b")

        mock_generate.assert_called_once_with(tenant_id="tenant-b", force=True)


class TestPingEnginesTask:
    """ping_engines_task delegates to the ping service."""

    def test_calls_ping_service(self, db):
        from icv_sitemaps.tasks import ping_engines_task

        # Lazy import inside the task — patch at source
        with patch("icv_sitemaps.services.ping.ping_search_engines") as mock_ping:
            mock_ping.return_value = {"google": 200, "bing": 200}

            result = ping_engines_task(sitemap_url="https://example.com/sitemap.xml")

        mock_ping.assert_called_once_with(sitemap_url="https://example.com/sitemap.xml", tenant_id="")
        assert "google" in result

    def test_passes_tenant_id(self, db):
        from icv_sitemaps.tasks import ping_engines_task

        with patch("icv_sitemaps.services.ping.ping_search_engines") as mock_ping:
            mock_ping.return_value = {}

            ping_engines_task(tenant_id="tenant-x")

        mock_ping.assert_called_once_with(sitemap_url="", tenant_id="tenant-x")


class TestCleanupLogsTask:
    """cleanup_generation_logs deletes old log records."""

    def test_deletes_old_logs(self, db):
        from icv_sitemaps.tasks import cleanup_generation_logs
        from icv_sitemaps.testing.factories import SitemapGenerationLogFactory

        # Create a log and backdate it beyond the retention window
        log = SitemapGenerationLogFactory()
        from django.utils import timezone

        old_time = timezone.now() - timezone.timedelta(days=60)
        type(log).objects.filter(pk=log.pk).update(created_at=old_time)

        cleanup_generation_logs(days_older_than=30)

        from icv_sitemaps.models import SitemapGenerationLog

        assert not SitemapGenerationLog.objects.filter(pk=log.pk).exists()

    def test_keeps_recent_logs(self, db):
        from icv_sitemaps.tasks import cleanup_generation_logs
        from icv_sitemaps.testing.factories import SitemapGenerationLogFactory

        log = SitemapGenerationLogFactory()  # Recent — created now

        cleanup_generation_logs(days_older_than=30)

        from icv_sitemaps.models import SitemapGenerationLog

        assert SitemapGenerationLog.objects.filter(pk=log.pk).exists()


class TestTasksImportableWithoutCelery:
    """The tasks module must be importable when Celery is not installed."""

    def test_module_importable_without_celery(self):
        celery_modules = {k: v for k, v in sys.modules.items() if "celery" in k}
        for k in celery_modules:
            sys.modules.pop(k, None)

        try:
            if "icv_sitemaps.tasks" in sys.modules:
                del sys.modules["icv_sitemaps.tasks"]
            importlib.import_module("icv_sitemaps.tasks")
        finally:
            sys.modules.update(celery_modules)
            if "icv_sitemaps.tasks" in sys.modules:
                del sys.modules["icv_sitemaps.tasks"]
