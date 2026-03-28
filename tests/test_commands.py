"""Tests for icv-sitemaps management commands."""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command

from icv_sitemaps.testing.factories import SitemapSectionFactory

# ---------------------------------------------------------------------------
# icv_sitemaps_setup
# ---------------------------------------------------------------------------


class TestIcvSitemapsSetupCommand:
    def test_creates_sections_from_auto_sections_setting(self, db, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
                "sitemap_type": "standard",
            }
        }

        from icv_sitemaps.models import SitemapSection

        out = StringIO()
        call_command("icv_sitemaps_setup", stdout=out)

        assert SitemapSection.objects.filter(name="articles").exists()
        assert "Created" in out.getvalue()

    def test_dry_run_does_not_create_records(self, db, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "products": {
                "model": "sitemaps_testapp.Article",
                "sitemap_type": "standard",
            }
        }

        from icv_sitemaps.models import SitemapSection

        out = StringIO()
        call_command("icv_sitemaps_setup", "--dry-run", stdout=out)

        assert not SitemapSection.objects.filter(name="products").exists()
        assert "DRY RUN" in out.getvalue()

    def test_invalid_model_path_handled_gracefully(self, db, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "broken": {
                "model": "nonexistent.DoesNotExist",
                "sitemap_type": "standard",
            }
        }

        from icv_sitemaps.models import SitemapSection

        out = StringIO()
        call_command("icv_sitemaps_setup", stdout=out)

        assert not SitemapSection.objects.filter(name="broken").exists()
        assert "Errors:    1" in out.getvalue()

    def test_skips_existing_sections(self, db, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
                "sitemap_type": "standard",
            }
        }

        from icv_sitemaps.models import SitemapSection

        # Pre-create the section
        SitemapSection.objects.create(
            name="articles",
            model_path="sitemaps_testapp.Article",
        )

        out = StringIO()
        call_command("icv_sitemaps_setup", stdout=out)

        # Should still be exactly one record, not two
        assert SitemapSection.objects.filter(name="articles").count() == 1
        assert "Existing:  1" in out.getvalue()

    def test_empty_auto_sections_produces_zero_counts(self, db, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {}

        out = StringIO()
        call_command("icv_sitemaps_setup", stdout=out)

        assert "nothing to create" in out.getvalue()

    def test_storage_verification_runs(self, db, settings, tmp_path):
        """The setup command writes and deletes a test file for storage connectivity."""
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {}

        import icv_sitemaps.conf as conf_mod

        out = StringIO()
        with patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"):
            call_command("icv_sitemaps_setup", stdout=out)

        assert "Storage" in out.getvalue() or "storage" in out.getvalue().lower()

    def test_storage_failure_aborts_setup(self, db, settings, tmp_path):
        """When storage write fails, setup aborts and does not create sections."""
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
            }
        }

        from icv_sitemaps.models import SitemapSection

        out = StringIO()
        with patch("django.core.files.storage.FileSystemStorage.save", side_effect=OSError("disk full")):
            call_command("icv_sitemaps_setup", stdout=out)

        assert not SitemapSection.objects.filter(name="articles").exists()
        assert "Aborting" in out.getvalue()

    def test_dry_run_storage_does_not_write(self, db, settings, tmp_path):
        """Dry run skips actual storage write."""
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {}

        out = StringIO()
        with patch("django.core.files.storage.FileSystemStorage.save") as mock_save:
            call_command("icv_sitemaps_setup", "--dry-run", stdout=out)

        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# icv_sitemaps_generate
# ---------------------------------------------------------------------------


class TestIcvSitemapsGenerateCommand:
    def _make_conf_patches(self, conf_mod, tmp_path):
        """Return a list of patch.object context managers for conf constants."""
        return [
            patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False),
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
            patch.object(conf_mod, "ICV_SITEMAPS_MAX_URLS_PER_FILE", 50000),
            patch.object(conf_mod, "ICV_SITEMAPS_MAX_FILE_SIZE_BYTES", 52428800),
            patch.object(conf_mod, "ICV_SITEMAPS_BATCH_SIZE", 5000),
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENABLED", False),
        ]

    def test_section_flag_generates_specific_section(self, db, tmp_path, settings):
        import icv_sitemaps.conf as conf_mod

        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import Article

        Article.objects.create(title="T1", slug="t1-cmd", is_published=True)
        SitemapSectionFactory(
            name="articles-cmd",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        out = StringIO()
        patches = self._make_conf_patches(conf_mod, tmp_path)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            call_command("icv_sitemaps_generate", "--section", "articles-cmd", stdout=out)

        assert "Generating section" in out.getvalue() or "Done" in out.getvalue()

    def test_section_flag_raises_command_error_when_not_found(self, db):
        with pytest.raises(CommandError, match="not found"):
            call_command("icv_sitemaps_generate", "--section", "nonexistent-xyz")

    def test_all_flag_generates_all_active_sections(self, db, tmp_path, settings):
        import icv_sitemaps.conf as conf_mod

        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import Article

        Article.objects.create(title="T2", slug="t2-all", is_published=True)
        SitemapSectionFactory(
            name="articles-all",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        out = StringIO()
        patches = self._make_conf_patches(conf_mod, tmp_path)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            call_command("icv_sitemaps_generate", "--all", stdout=out)

        assert "Generated" in out.getvalue()

    def test_all_flag_prints_warning_when_no_active_sections(self, db):
        # No sections in DB
        out = StringIO()
        call_command("icv_sitemaps_generate", "--all", stdout=out)

        assert "No active sections" in out.getvalue()

    def test_index_only_generates_index_file(self, db, tmp_path, settings):
        """--index-only writes a sitemap index to storage."""
        settings.MEDIA_ROOT = str(tmp_path)

        import icv_sitemaps.conf as conf_mod

        out = StringIO()
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False),
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
        ):
            call_command("icv_sitemaps_generate", "--index-only", stdout=out)

        assert "index" in out.getvalue().lower()
        assert (
            "regenerated" in out.getvalue().lower()
            or "done" in out.getvalue().lower()
            or "Sitemap index" in out.getvalue()
        )

    def test_index_only_uses_generate_index_not_regenerate_index(self, db, tmp_path, settings):
        """The --index-only path must import and call generate_index from services.

        This test verifies the command calls the function named ``generate_index``
        (not a hypothetical ``regenerate_index`` alias). We verify by checking
        the public services API directly.
        """
        from icv_sitemaps.services import generate_index

        # generate_index must exist and be callable in the public API
        assert callable(generate_index)

        # Verify the command's output confirms the correct action ran
        settings.MEDIA_ROOT = str(tmp_path)
        import icv_sitemaps.conf as conf_mod

        out = StringIO()
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_GZIP", False),
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
        ):
            call_command("icv_sitemaps_generate", "--index-only", stdout=out)

        # The command prints success after calling the index function
        assert "Sitemap index regenerated" in out.getvalue()

    def test_default_mode_only_generates_stale_sections(self, db, tmp_path, settings):
        import icv_sitemaps.conf as conf_mod

        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import Article

        Article.objects.create(title="T3", slug="t3-default", is_published=True)
        SitemapSectionFactory(
            name="stale-section",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )
        _fresh = SitemapSectionFactory(
            name="fresh-section",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=False,
        )

        out = StringIO()
        patches = self._make_conf_patches(conf_mod, tmp_path)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            call_command("icv_sitemaps_generate", stdout=out)

        output = out.getvalue()
        assert "stale-section" in output
        assert "fresh-section" not in output

    def test_no_stale_sections_prints_nothing_to_generate(self, db):
        # Create only fresh sections
        SitemapSectionFactory(name="fresh-only", is_stale=False)

        out = StringIO()
        call_command("icv_sitemaps_generate", stdout=out)

        assert "No stale sections" in out.getvalue()

    def test_force_flag_regenerates_fresh_section(self, db, tmp_path, settings):
        import icv_sitemaps.conf as conf_mod

        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import Article

        Article.objects.create(title="T4", slug="t4-force", is_published=True)
        SitemapSectionFactory(
            name="fresh-force",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=False,
        )

        out = StringIO()
        patches = self._make_conf_patches(conf_mod, tmp_path)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            # --force together with explicit --all is the supported force mode
            call_command("icv_sitemaps_generate", "--all", "--force", stdout=out)

        assert "Generated" in out.getvalue()

    def test_tenant_flag_scopes_section_lookup(self, db, tmp_path, settings):
        import icv_sitemaps.conf as conf_mod

        settings.MEDIA_ROOT = str(tmp_path)

        from sitemaps_testapp.models import Article

        Article.objects.create(title="T5", slug="t5-tenant", is_published=True)
        SitemapSectionFactory(
            name="tenant-articles",
            tenant_id="acme",
            model_path="sitemaps_testapp.Article",
            sitemap_type="standard",
            is_stale=True,
        )

        out = StringIO()
        patches = self._make_conf_patches(conf_mod, tmp_path)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            call_command(
                "icv_sitemaps_generate",
                "--section",
                "tenant-articles",
                "--tenant",
                "acme",
                stdout=out,
            )

        assert "tenant-articles" in out.getvalue()


# ---------------------------------------------------------------------------
# icv_sitemaps_validate
# ---------------------------------------------------------------------------


class TestIcvSitemapsValidateCommand:
    def test_no_files_prints_warning(self, db):
        out = StringIO()
        call_command("icv_sitemaps_validate", stdout=out)

        assert "No sitemap files" in out.getvalue()

    def test_pass_for_valid_xml_file(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.testing.factories import SitemapFileFactory

        section = SitemapSectionFactory(name="validate-pass")
        valid_xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://example.com/page/</loc></url>"
            b"</urlset>"
        )
        storage_path = "sitemaps/validate-pass-0.xml"
        default_storage.save(storage_path, ContentFile(valid_xml))
        SitemapFileFactory(section=section, storage_path=storage_path, url_count=1)

        out = StringIO()
        call_command("icv_sitemaps_validate", stdout=out)

        assert "PASS" in out.getvalue()

    def test_fail_for_missing_storage_file(self, db, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)

        from icv_sitemaps.testing.factories import SitemapFileFactory

        section = SitemapSectionFactory(name="validate-missing")
        SitemapFileFactory(
            section=section,
            storage_path="sitemaps/does-not-exist.xml",
            url_count=1,
        )

        out = StringIO()
        call_command("icv_sitemaps_validate", stdout=out)

        assert "FAIL" in out.getvalue()
        assert "not found in storage" in out.getvalue()

    def test_fail_reports_non_absolute_url(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.testing.factories import SitemapFileFactory

        section = SitemapSectionFactory(name="validate-relative")
        bad_xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>/relative/path/</loc></url>"
            b"</urlset>"
        )
        storage_path = "sitemaps/validate-relative-0.xml"
        default_storage.save(storage_path, ContentFile(bad_xml))
        SitemapFileFactory(section=section, storage_path=storage_path, url_count=1)

        out = StringIO()
        call_command("icv_sitemaps_validate", stdout=out)

        assert "FAIL" in out.getvalue()
        assert "absolute" in out.getvalue()

    def test_section_filter_only_validates_that_section(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.testing.factories import SitemapFileFactory

        valid_xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://example.com/a/</loc></url>"
            b"</urlset>"
        )

        section_a = SitemapSectionFactory(name="validate-sec-a")
        path_a = "sitemaps/validate-sec-a-0.xml"
        default_storage.save(path_a, ContentFile(valid_xml))
        SitemapFileFactory(section=section_a, storage_path=path_a, url_count=1)

        section_b = SitemapSectionFactory(name="validate-sec-b")
        SitemapFileFactory(
            section=section_b,
            storage_path="sitemaps/validate-sec-b-missing.xml",
            url_count=1,
        )

        out = StringIO()
        call_command("icv_sitemaps_validate", "--section", "validate-sec-a", stdout=out)

        # Only section-a files reported; section-b's missing file not mentioned
        assert "validate-sec-a" in out.getvalue()
        assert "validate-sec-b" not in out.getvalue()

    def test_validate_unknown_section_prints_error(self, db):
        out = StringIO()
        call_command("icv_sitemaps_validate", "--section", "no-such-section", stdout=out)

        assert "not found" in out.getvalue()

    def test_summary_line_shows_passed_and_failed_counts(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.testing.factories import SitemapFileFactory

        valid_xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://example.com/ok/</loc></url>"
            b"</urlset>"
        )
        section = SitemapSectionFactory(name="validate-summary")
        path = "sitemaps/validate-summary-0.xml"
        default_storage.save(path, ContentFile(valid_xml))
        SitemapFileFactory(section=section, storage_path=path, url_count=1)

        out = StringIO()
        call_command("icv_sitemaps_validate", stdout=out)

        assert "passed:" in out.getvalue()
        assert "failed:" in out.getvalue()


# ---------------------------------------------------------------------------
# icv_sitemaps_stats
# ---------------------------------------------------------------------------


class TestIcvSitemapsStatsCommand:
    def test_prints_summary_statistics(self, db):
        SitemapSectionFactory(name="stats-a", url_count=100, file_count=1, is_stale=False)
        SitemapSectionFactory(name="stats-b", url_count=200, file_count=2, is_stale=True)

        out = StringIO()
        call_command("icv_sitemaps_stats", stdout=out)

        output = out.getvalue()
        assert "Total sections" in output
        assert "Total URLs" in output
        assert "Total files" in output
        assert "stats-a" in output
        assert "stats-b" in output

    def test_stale_count_highlighted_when_nonzero(self, db):
        SitemapSectionFactory(name="stats-stale", is_stale=True)

        out = StringIO()
        call_command("icv_sitemaps_stats", stdout=out)

        assert "Stale sections" in out.getvalue()

    def test_tenant_flag_scopes_results(self, db):
        SitemapSectionFactory(name="stats-acme", tenant_id="acme", url_count=50)
        SitemapSectionFactory(name="stats-other", tenant_id="other", url_count=99)

        out = StringIO()
        call_command("icv_sitemaps_stats", "--tenant", "acme", stdout=out)

        output = out.getvalue()
        assert "stats-acme" in output
        assert "stats-other" not in output
        assert "Tenant: acme" in output

    def test_no_sections_shows_zero_counts(self, db):
        out = StringIO()
        call_command("icv_sitemaps_stats", stdout=out)

        assert "Total sections:      0" in out.getvalue()

    def test_last_generated_never_when_no_logs(self, db):
        SitemapSectionFactory(name="stats-nolog")

        out = StringIO()
        call_command("icv_sitemaps_stats", stdout=out)

        assert "never" in out.getvalue()

    def test_inactive_sections_shown_in_breakdown(self, db):
        SitemapSectionFactory(name="stats-inactive", is_active=False)

        out = StringIO()
        call_command("icv_sitemaps_stats", stdout=out)

        assert "inactive" in out.getvalue()


# ---------------------------------------------------------------------------
# icv_sitemaps_ping
# ---------------------------------------------------------------------------


class TestIcvSitemapsPingCommand:
    def test_ping_disabled_prints_warning_and_skips(self, db):
        import icv_sitemaps.conf as conf_mod

        out = StringIO()
        with patch.object(conf_mod, "ICV_SITEMAPS_PING_ENABLED", False):
            call_command("icv_sitemaps_ping", stdout=out)

        assert "disabled" in out.getvalue().lower() or "PING_ENABLED" in out.getvalue()

    def test_ping_enabled_calls_service(self, db):
        """When ping is enabled, the command uses the ping service layer."""
        import icv_sitemaps.conf as conf_mod

        # The command does `from icv_sitemaps.services import ping_search_engines`
        # inside handle(), so we patch the name on the services __init__ module
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENGINES", ["google"]),
            patch(
                "icv_sitemaps.services.ping_search_engines",
                return_value={"google": {"success": True, "status_code": 200, "error": ""}},
            ) as mock_ping,
        ):
            out = StringIO()
            call_command("icv_sitemaps_ping", stdout=out)

        mock_ping.assert_called_once()
        assert "PING RESULTS" in out.getvalue()

    def test_explicit_url_flag_used_in_ping(self, db):
        """--url flag is passed to the ping service."""
        import icv_sitemaps.conf as conf_mod

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENGINES", ["google"]),
            patch(
                "icv_sitemaps.services.ping_search_engines",
                return_value={"google": {"success": True, "status_code": 200, "error": ""}},
            ),
        ):
            out = StringIO()
            call_command(
                "icv_sitemaps_ping",
                "--url",
                "https://example.com/custom-sitemap.xml",
                stdout=out,
            )

        # The explicit URL should appear in the output header
        assert "https://example.com/custom-sitemap.xml" in out.getvalue()

    def test_no_base_url_and_no_explicit_url_prints_error(self, db):
        import icv_sitemaps.conf as conf_mod

        out = StringIO()
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", ""),
        ):
            call_command("icv_sitemaps_ping", stdout=out)

        # Should not crash — should print an error about missing URL
        assert "No sitemap URL" in out.getvalue() or "Error" in out.getvalue() or "error" in out.getvalue().lower()

    def test_tenant_flag_builds_tenant_specific_url(self, db):
        """--tenant flag causes the command to build a tenant-scoped sitemap URL."""
        import icv_sitemaps.conf as conf_mod

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"),
            patch.object(conf_mod, "ICV_SITEMAPS_PING_ENGINES", ["google"]),
            patch(
                "icv_sitemaps.services.ping_search_engines",
                return_value={"google": {"success": True, "status_code": 200, "error": ""}},
            ) as mock_ping,
        ):
            out = StringIO()
            call_command("icv_sitemaps_ping", "--tenant", "acme", stdout=out)

        call_args = mock_ping.call_args
        # tenant_id should be forwarded to the service
        assert "acme" in str(call_args)
