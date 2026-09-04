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


class TestCleanupOrphanFiles:
    """cleanup_orphan_files deletes untracked sitemap files, never tracked ones."""

    def test_live_file_survives_orphan_deleted(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.tasks import cleanup_orphan_files
        from icv_sitemaps.testing.factories import SitemapFileFactory

        live_path = "sitemaps/section-a-0.xml"
        orphan_path = "sitemaps/section-a-orphan.xml"

        SitemapFileFactory(storage_path=live_path)
        default_storage.save(live_path, ContentFile(b"<urlset></urlset>"))
        default_storage.save(orphan_path, ContentFile(b"<urlset></urlset>"))

        deleted = cleanup_orphan_files()

        assert default_storage.exists(live_path), "LIVE SITEMAP WAS DELETED"
        assert not default_storage.exists(orphan_path), "ORPHAN FILE WAS NOT DELETED"
        assert deleted == 1, f"expected 1 orphan deleted, got {deleted}"

    def test_non_sitemap_file_is_ignored(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.tasks import cleanup_orphan_files

        other_path = "sitemaps/notes.txt"
        default_storage.save(other_path, ContentFile(b"not a sitemap"))

        deleted = cleanup_orphan_files()

        assert default_storage.exists(other_path), "NON-SITEMAP FILE WAS DELETED"
        assert deleted == 0, f"expected 0 files deleted, got {deleted}"

    def test_tenant_subdirectory_recursion_is_additive(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.tasks import cleanup_orphan_files
        from icv_sitemaps.testing.factories import SitemapFileFactory, SitemapSectionFactory

        top_live_path = "sitemaps/section-top-0.xml"
        top_orphan_path = "sitemaps/section-top-orphan.xml"
        tenant_live_path = "sitemaps/tenant-a/live.xml"
        tenant_orphan_path = "sitemaps/tenant-a/orphan.xml"

        SitemapFileFactory(storage_path=top_live_path)
        section_a = SitemapSectionFactory(tenant_id="tenant-a")
        SitemapFileFactory(section=section_a, storage_path=tenant_live_path)

        default_storage.save(top_live_path, ContentFile(b"<urlset></urlset>"))
        default_storage.save(top_orphan_path, ContentFile(b"<urlset></urlset>"))
        default_storage.save(tenant_live_path, ContentFile(b"<urlset></urlset>"))
        default_storage.save(tenant_orphan_path, ContentFile(b"<urlset></urlset>"))

        deleted = cleanup_orphan_files()

        assert default_storage.exists(top_live_path), "TOP-LEVEL LIVE SITEMAP WAS DELETED"
        assert default_storage.exists(tenant_live_path), "TENANT SUBDIRECTORY LIVE SITEMAP WAS DELETED"
        assert not default_storage.exists(top_orphan_path), "TOP-LEVEL ORPHAN WAS NOT DELETED"
        assert not default_storage.exists(tenant_orphan_path), "TENANT SUBDIRECTORY ORPHAN WAS NOT DELETED"
        assert deleted == 2, f"expected 2 orphans deleted (top level and tenant subdirectory), got {deleted}"

    def test_scoped_tenant_run_does_not_touch_other_tenants(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.tasks import cleanup_orphan_files

        tenant_a_orphan = "sitemaps/tenant-a/orphan.xml"
        tenant_b_orphan = "sitemaps/tenant-b/orphan.xml"
        top_level_orphan = "sitemaps/top-orphan.xml"

        default_storage.save(tenant_a_orphan, ContentFile(b"<urlset></urlset>"))
        default_storage.save(tenant_b_orphan, ContentFile(b"<urlset></urlset>"))
        default_storage.save(top_level_orphan, ContentFile(b"<urlset></urlset>"))

        deleted = cleanup_orphan_files(tenant_id="tenant-a")

        assert not default_storage.exists(tenant_a_orphan), "SCOPED TENANT ORPHAN WAS NOT DELETED"
        assert default_storage.exists(tenant_b_orphan), "FILE OUTSIDE THE TENANT PREFIX DELETED"
        assert default_storage.exists(top_level_orphan), "FILE OUTSIDE THE TENANT PREFIX DELETED"
        assert deleted == 1, f"expected 1 file deleted, got {deleted}"

    def test_storage_path_convention_pin_no_tenant(self, db, tmp_path, settings):
        """A file written via the real _storage_path helper must survive the scan.

        This pins the scan prefix in cleanup_orphan_files to the same
        convention the generation service actually writes to. If either side
        drifts, this test is where it breaks.
        """
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.services.generation import _storage_path
        from icv_sitemaps.tasks import cleanup_orphan_files
        from icv_sitemaps.testing.factories import SitemapFileFactory

        path = _storage_path("section-b-0.xml")
        SitemapFileFactory(storage_path=path)
        default_storage.save(path, ContentFile(b"<urlset></urlset>"))

        deleted = cleanup_orphan_files()

        assert default_storage.exists(path), "LIVE SITEMAP WAS DELETED (scan and writer paths disagree)"
        assert deleted == 0, f"expected 0 files deleted, got {deleted}"

    def test_storage_path_convention_pin_with_tenant(self, db, tmp_path, settings):
        """A tenant-scoped file written via the real _storage_path helper must survive both a full scan and a scoped tenant run."""
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.services.generation import _storage_path
        from icv_sitemaps.tasks import cleanup_orphan_files
        from icv_sitemaps.testing.factories import SitemapFileFactory, SitemapSectionFactory

        path = _storage_path("section-c-0.xml", tenant_id="tenant-a")
        section_a = SitemapSectionFactory(tenant_id="tenant-a")
        SitemapFileFactory(section=section_a, storage_path=path)
        default_storage.save(path, ContentFile(b"<urlset></urlset>"))

        deleted_no_tenant = cleanup_orphan_files()
        assert default_storage.exists(path), (
            "LIVE SITEMAP WAS DELETED by an unscoped run (scan and writer paths disagree)"
        )
        assert deleted_no_tenant == 0, f"expected 0 files deleted, got {deleted_no_tenant}"

        deleted_scoped = cleanup_orphan_files(tenant_id="tenant-a")
        assert default_storage.exists(path), (
            "LIVE SITEMAP WAS DELETED by a scoped tenant run (scan and writer paths disagree)"
        )
        assert deleted_scoped == 0, f"expected 0 files deleted, got {deleted_scoped}"

    def test_listdir_failure_returns_zero_without_raising(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.storage import default_storage

        from icv_sitemaps.tasks import cleanup_orphan_files

        with patch.object(default_storage, "listdir", side_effect=OSError("boom")):
            deleted = cleanup_orphan_files()

        assert deleted == 0, f"expected 0 on a listing failure, got {deleted}"

    def test_section_delete_orphans_its_file_until_cleanup_runs(self, db, tmp_path, settings):
        """Pins AC-OPS-002: deleting a section directly (not delete_section) orphans its storage file.

        Deleting a SitemapSection through the ORM cascades its SitemapFile
        row but leaves the storage file in place, this is the real-world
        origin of an orphan and the reason cleanup_orphan_files exists.
        """
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.models.sections import SitemapFile
        from icv_sitemaps.tasks import cleanup_orphan_files
        from icv_sitemaps.testing.factories import SitemapFileFactory, SitemapSectionFactory

        section = SitemapSectionFactory()
        sitemap_file = SitemapFileFactory(section=section, storage_path="sitemaps/section-doomed-0.xml")
        default_storage.save(sitemap_file.storage_path, ContentFile(b"<urlset></urlset>"))

        section.delete()

        assert not SitemapFile.objects.filter(pk=sitemap_file.pk).exists(), (
            "SITEMAPFILE ROW SURVIVED SECTION DELETE (cascade did not fire)"
        )
        assert default_storage.exists(sitemap_file.storage_path), (
            "STORAGE FILE WAS REMOVED BY SECTION DELETE (should only be removed by cleanup_orphan_files)"
        )

        deleted = cleanup_orphan_files()

        assert not default_storage.exists(sitemap_file.storage_path), "ORPHANED SITEMAP FILE WAS NOT CLEANED UP"
        assert deleted == 1, f"expected 1 orphan deleted, got {deleted}"


class TestCleanupRedirectLogs:
    """cleanup_redirect_logs deletes only resolved logs older than the cutoff."""

    def test_resolved_log_older_than_cutoff_is_deleted(self, db):
        from django.utils import timezone

        from icv_sitemaps.tasks import cleanup_redirect_logs
        from icv_sitemaps.testing.factories import RedirectLogFactory

        log = RedirectLogFactory(resolved=True)
        old_time = timezone.now() - timezone.timedelta(days=120)
        type(log).objects.filter(pk=log.pk).update(last_seen_at=old_time)

        deleted = cleanup_redirect_logs(days_older_than=90)

        from icv_sitemaps.models.redirects import RedirectLog

        assert not RedirectLog.objects.filter(pk=log.pk).exists(), "RESOLVED LOG PAST RETENTION WAS NOT DELETED"
        assert deleted == 1, f"expected 1 log deleted, got {deleted}"

    def test_unresolved_log_older_than_cutoff_survives(self, db):
        from django.utils import timezone

        from icv_sitemaps.tasks import cleanup_redirect_logs
        from icv_sitemaps.testing.factories import RedirectLogFactory

        log = RedirectLogFactory(resolved=False)
        old_time = timezone.now() - timezone.timedelta(days=120)
        type(log).objects.filter(pk=log.pk).update(last_seen_at=old_time)

        cleanup_redirect_logs(days_older_than=90)

        from icv_sitemaps.models.redirects import RedirectLog

        assert RedirectLog.objects.filter(pk=log.pk).exists(), "UNRESOLVED 404 EVIDENCE WAS DELETED"

    def test_resolved_log_newer_than_cutoff_survives(self, db):
        from icv_sitemaps.tasks import cleanup_redirect_logs
        from icv_sitemaps.testing.factories import RedirectLogFactory

        log = RedirectLogFactory(resolved=True)  # last_seen_at defaults to now

        cleanup_redirect_logs(days_older_than=90)

        from icv_sitemaps.models.redirects import RedirectLog

        assert RedirectLog.objects.filter(pk=log.pk).exists(), (
            "RECENT RESOLVED LOG WAS DELETED BEFORE RETENTION EXPIRED"
        )


class TestCleanupExpiredRedirects:
    """cleanup_expired_redirects deletes only rules with a past expires_at.

    The ``expires_at__isnull=False`` clause in the task is defensive
    redundancy: SQL ``NULL`` never satisfies a ``<`` comparison, so a
    permanent rule (``expires_at=None``) is already excluded by the
    ``expires_at__lt`` filter on its own. The permanent-rule test below is
    pinned by that ``__lt`` behaviour, not by the isnull clause, per fault
    injection recorded on the issue.
    """

    def test_rule_with_past_expiry_is_deleted(self, db):
        from django.utils import timezone

        from icv_sitemaps.tasks import cleanup_expired_redirects
        from icv_sitemaps.testing.factories import RedirectRuleFactory

        rule = RedirectRuleFactory(expires_at=timezone.now() - timezone.timedelta(days=1))

        deleted = cleanup_expired_redirects()

        from icv_sitemaps.models.redirects import RedirectRule

        assert not RedirectRule.objects.filter(pk=rule.pk).exists(), "EXPIRED REDIRECT RULE WAS NOT DELETED"
        assert deleted == 1, f"expected 1 rule deleted, got {deleted}"

    def test_rule_with_no_expiry_survives(self, db):
        from icv_sitemaps.tasks import cleanup_expired_redirects
        from icv_sitemaps.testing.factories import RedirectRuleFactory

        rule = RedirectRuleFactory(expires_at=None)

        cleanup_expired_redirects()

        from icv_sitemaps.models.redirects import RedirectRule

        assert RedirectRule.objects.filter(pk=rule.pk).exists(), "PERMANENT REDIRECT RULE WAS DELETED"

    def test_rule_with_future_expiry_survives(self, db):
        from django.utils import timezone

        from icv_sitemaps.tasks import cleanup_expired_redirects
        from icv_sitemaps.testing.factories import RedirectRuleFactory

        rule = RedirectRuleFactory(expires_at=timezone.now() + timezone.timedelta(days=30))

        cleanup_expired_redirects()

        from icv_sitemaps.models.redirects import RedirectRule

        assert RedirectRule.objects.filter(pk=rule.pk).exists(), "NOT-YET-EXPIRED REDIRECT RULE WAS DELETED"
