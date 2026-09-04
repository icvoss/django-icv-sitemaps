"""Tests for delete_section() and its admin bulk action (issue #49).

Covers src/icv_sitemaps/services/sections.py:75-121 (delete_section) and
the delete_with_files admin action at src/icv_sitemaps/admin.py:74, both
previously untested despite delete_section being public API.
"""

from django.core.files.base import ContentFile


def _write_storage_file(storage_path: str) -> None:
    """Write a real file into default_storage at the given path."""
    from django.core.files.storage import default_storage

    default_storage.save(storage_path, ContentFile(b"<urlset/>"))


class TestDeleteSection:
    def test_deletes_own_rows_and_files_leaves_sibling_untouched(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.storage import default_storage

        from icv_sitemaps.models import SitemapFile, SitemapGenerationLog, SitemapSection
        from icv_sitemaps.services.sections import delete_section
        from icv_sitemaps.testing.factories import (
            SitemapFileFactory,
            SitemapGenerationLogFactory,
            SitemapSectionFactory,
        )

        doomed = SitemapSectionFactory(name="doomed-name")
        doomed_path = "sitemaps/doomed-0.xml"
        _write_storage_file(doomed_path)
        doomed_file = SitemapFileFactory(section=doomed, storage_path=doomed_path)
        doomed_log = SitemapGenerationLogFactory(section=doomed)

        sibling = SitemapSectionFactory(name="sibling-name")
        sibling_path = "sitemaps/sibling-0.xml"
        _write_storage_file(sibling_path)
        sibling_file = SitemapFileFactory(section=sibling, storage_path=sibling_path)
        sibling_log = SitemapGenerationLogFactory(section=sibling)

        delete_section("doomed-name")

        assert not SitemapSection.objects.filter(pk=doomed.pk).exists(), "DOOMED SECTION NOT DELETED"
        assert not SitemapFile.objects.filter(pk=doomed_file.pk).exists(), "DOOMED FILE ROW NOT DELETED"
        assert not SitemapGenerationLog.objects.filter(pk=doomed_log.pk).exists(), "DOOMED LOG ROW NOT DELETED"
        assert not default_storage.exists(doomed_path), "DOOMED STORAGE FILE NOT DELETED"

        assert SitemapSection.objects.filter(pk=sibling.pk).exists(), "SIBLING SECTION DELETED"
        assert SitemapFile.objects.filter(pk=sibling_file.pk).exists(), "SIBLING FILE ROW DELETED"
        assert SitemapGenerationLog.objects.filter(pk=sibling_log.pk).exists(), "SIBLING LOG ROW DELETED"
        assert default_storage.exists(sibling_path), "SIBLING STORAGE FILE DELETED"

    def test_accepts_section_instance_as_well_as_name(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.storage import default_storage

        from icv_sitemaps.models import SitemapFile, SitemapSection
        from icv_sitemaps.services.sections import delete_section
        from icv_sitemaps.testing.factories import SitemapFileFactory, SitemapSectionFactory

        section = SitemapSectionFactory(name="instance-target")
        storage_path = "sitemaps/instance-target-0.xml"
        _write_storage_file(storage_path)
        file_row = SitemapFileFactory(section=section, storage_path=storage_path)

        delete_section(section)

        assert not SitemapSection.objects.filter(pk=section.pk).exists(), "SECTION NOT DELETED VIA INSTANCE"
        assert not SitemapFile.objects.filter(pk=file_row.pk).exists(), "FILE ROW NOT DELETED VIA INSTANCE"
        assert not default_storage.exists(storage_path), "STORAGE FILE NOT DELETED VIA INSTANCE"

    def test_tenant_scoping_only_removes_named_tenants_section(self, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.storage import default_storage

        from icv_sitemaps.models import SitemapSection
        from icv_sitemaps.services.sections import delete_section
        from icv_sitemaps.testing.factories import SitemapFileFactory, SitemapSectionFactory

        tenant_a = SitemapSectionFactory(name="shared-name", tenant_id="tenant-a")
        tenant_a_path = "sitemaps/tenant-a-0.xml"
        _write_storage_file(tenant_a_path)
        SitemapFileFactory(section=tenant_a, storage_path=tenant_a_path)

        tenant_b = SitemapSectionFactory(name="shared-name", tenant_id="tenant-b")
        tenant_b_path = "sitemaps/tenant-b-0.xml"
        _write_storage_file(tenant_b_path)
        SitemapFileFactory(section=tenant_b, storage_path=tenant_b_path)

        delete_section("shared-name", tenant_id="tenant-a")

        assert not SitemapSection.objects.filter(pk=tenant_a.pk).exists(), "TENANT A SECTION NOT DELETED"
        assert not default_storage.exists(tenant_a_path), "TENANT A FILE NOT DELETED"

        assert SitemapSection.objects.filter(pk=tenant_b.pk).exists(), "OTHER TENANT'S SECTION DELETED"
        assert default_storage.exists(tenant_b_path), "OTHER TENANT'S FILE DELETED"

    def test_default_tenant_is_blank_and_does_not_match_other_tenant(self, db, caplog):
        from icv_sitemaps.models import SitemapSection
        from icv_sitemaps.services.sections import delete_section
        from icv_sitemaps.testing.factories import SitemapSectionFactory

        section = SitemapSectionFactory(name="its-name", tenant_id="tenant-a")

        with caplog.at_level("WARNING"):
            result = delete_section("its-name")

        assert result is None, "RETURN VALUE NOT NONE FOR TENANT MISMATCH"
        assert SitemapSection.objects.filter(pk=section.pk).exists(), "SECTION DELETED UNDER WRONG DEFAULT TENANT"
        assert any("its-name" in record.message for record in caplog.records), "NO WARNING LOGGED FOR TENANT MISMATCH"

    def test_not_found_returns_none_and_logs_warning(self, db, caplog):
        from icv_sitemaps.services.sections import delete_section

        with caplog.at_level("WARNING"):
            result = delete_section("no-such-section")

        assert result is None, "RETURN VALUE NOT NONE FOR NOT-FOUND SECTION"
        assert any("no-such-section" in record.message for record in caplog.records), (
            "NO WARNING LOGGED FOR NOT-FOUND SECTION"
        )

    def test_signal_fires_after_db_row_is_gone(self, db):
        from icv_sitemaps.models import SitemapSection
        from icv_sitemaps.services.sections import delete_section
        from icv_sitemaps.signals import sitemap_section_deleted
        from icv_sitemaps.testing.factories import SitemapSectionFactory

        section = SitemapSectionFactory(name="signal-target")
        section_pk = section.pk

        received = []

        def _receiver(sender, instance, **kwargs):
            received.append(
                (
                    instance.name,
                    SitemapSection.objects.filter(pk=section_pk).exists(),
                )
            )

        sitemap_section_deleted.connect(_receiver)
        try:
            delete_section("signal-target")
        finally:
            sitemap_section_deleted.disconnect(_receiver)

        assert len(received) == 1, "SIGNAL NOT FIRED EXACTLY ONCE"
        name, row_still_exists = received[0]
        assert name == "signal-target", "SIGNAL FIRED WITH WRONG SECTION NAME"
        assert row_still_exists is False, "SIGNAL FIRED BEFORE DB ROW WAS DELETED"

    def test_one_storage_failure_does_not_stop_the_others(self, db, tmp_path, settings):
        from unittest.mock import patch

        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.storage import default_storage

        from icv_sitemaps.models import SitemapFile, SitemapSection
        from icv_sitemaps.services.sections import delete_section
        from icv_sitemaps.testing.factories import SitemapFileFactory, SitemapSectionFactory

        section = SitemapSectionFactory(name="partial-failure")
        failing_path = "sitemaps/partial-failure-0.xml"
        ok_path = "sitemaps/partial-failure-1.xml"
        _write_storage_file(failing_path)
        _write_storage_file(ok_path)
        failing_file = SitemapFileFactory(section=section, sequence=0, storage_path=failing_path)
        ok_file = SitemapFileFactory(section=section, sequence=1, storage_path=ok_path)

        real_delete = default_storage.delete

        def _delete_side_effect(name, *args, **kwargs):
            if name == failing_path:
                raise OSError("simulated storage failure")
            return real_delete(name, *args, **kwargs)

        with patch.object(default_storage, "delete", side_effect=_delete_side_effect):
            result = delete_section("partial-failure")

        assert result is None, "FUNCTION DID NOT RETURN NORMALLY AFTER PARTIAL STORAGE FAILURE"
        assert not default_storage.exists(ok_path), "SECOND FILE NOT DELETED AFTER FIRST FILE'S DELETE FAILED"
        assert not SitemapSection.objects.filter(pk=section.pk).exists(), "SECTION ROW NOT DELETED"
        assert not SitemapFile.objects.filter(pk=failing_file.pk).exists(), "FAILING FILE ROW NOT DELETED"
        assert not SitemapFile.objects.filter(pk=ok_file.pk).exists(), "OK FILE ROW NOT DELETED"


class TestDeleteWithFilesAdminAction:
    """Exercises the delete_with_files admin bulk action (admin.py:74).

    Pattern follows TestCreateGoneFrom404Action in tests/test_admin.py:
    MagicMock() modeladmin and request, real queryset, call the action
    function directly.
    """

    def test_deletes_selected_section_and_files_leaves_other_untouched(self, db, tmp_path, settings):
        from unittest.mock import MagicMock

        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.storage import default_storage

        from icv_sitemaps.admin import delete_with_files
        from icv_sitemaps.models import SitemapSection
        from icv_sitemaps.testing.factories import SitemapFileFactory, SitemapSectionFactory

        selected = SitemapSectionFactory(name="selected-section")
        selected_path = "sitemaps/selected-0.xml"
        _write_storage_file(selected_path)
        SitemapFileFactory(section=selected, storage_path=selected_path)

        other = SitemapSectionFactory(name="other-section")
        other_path = "sitemaps/other-0.xml"
        _write_storage_file(other_path)
        SitemapFileFactory(section=other, storage_path=other_path)

        modeladmin = MagicMock()
        request = MagicMock()
        queryset = SitemapSection.objects.filter(pk=selected.pk)

        delete_with_files(modeladmin, request, queryset)

        assert not SitemapSection.objects.filter(pk=selected.pk).exists(), "SELECTED SECTION NOT DELETED"
        assert not default_storage.exists(selected_path), "SELECTED SECTION'S FILE NOT DELETED"

        assert SitemapSection.objects.filter(pk=other.pk).exists(), "UNSELECTED SECTION DELETED"
        assert default_storage.exists(other_path), "UNSELECTED SECTION'S FILE DELETED"

        modeladmin.message_user.assert_called_once()

    def test_passes_tenant_id_so_same_named_section_in_other_tenant_survives(self, db, tmp_path, settings):
        from unittest.mock import MagicMock

        settings.MEDIA_ROOT = str(tmp_path)

        from django.core.files.storage import default_storage

        from icv_sitemaps.admin import delete_with_files
        from icv_sitemaps.models import SitemapSection
        from icv_sitemaps.testing.factories import SitemapFileFactory, SitemapSectionFactory

        tenant_a = SitemapSectionFactory(name="shared-name", tenant_id="tenant-a")
        tenant_a_path = "sitemaps/admin-tenant-a-0.xml"
        _write_storage_file(tenant_a_path)
        SitemapFileFactory(section=tenant_a, storage_path=tenant_a_path)

        tenant_b = SitemapSectionFactory(name="shared-name", tenant_id="tenant-b")
        tenant_b_path = "sitemaps/admin-tenant-b-0.xml"
        _write_storage_file(tenant_b_path)
        SitemapFileFactory(section=tenant_b, storage_path=tenant_b_path)

        modeladmin = MagicMock()
        request = MagicMock()
        queryset = SitemapSection.objects.filter(pk=tenant_b.pk)

        delete_with_files(modeladmin, request, queryset)

        assert not SitemapSection.objects.filter(pk=tenant_b.pk).exists(), "TENANT B SECTION NOT DELETED"
        assert not default_storage.exists(tenant_b_path), "TENANT B FILE NOT DELETED"

        assert SitemapSection.objects.filter(pk=tenant_a.pk).exists(), "OTHER TENANT'S SECTION DELETED BY ADMIN ACTION"
        assert default_storage.exists(tenant_a_path), "OTHER TENANT'S FILE DELETED BY ADMIN ACTION"
