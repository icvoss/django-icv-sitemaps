"""Tests for storage-alias routing through icv_sitemaps.storage.get_storage() (#52, ADR-037).

Every call site that touches storage (views, tasks, the setup and validate
management commands, generation) resolves the backend through
``get_storage()``, the single resolution point for the package. These tests
prove the alias actually changes which backend each of those call sites
reads and writes, not just that ``get_storage()`` in isolation returns the
right object.
"""

from contextlib import ExitStack
from io import StringIO
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import Storage, storages
from django.core.management import call_command

from icv_sitemaps.services import generate_section
from icv_sitemaps.storage import get_storage
from icv_sitemaps.tasks import cleanup_orphan_files
from icv_sitemaps.testing.factories import StaticSitemapSectionFactory


def _configure_two_aliases(settings, tmp_path):
    """Configure a "default" and a "sitemaps" STORAGES alias, each backed by its own tmp dir.

    Django resets the ``storages`` connection handler when ``STORAGES``
    changes, so setting it via the pytest-django ``settings`` fixture is
    sufficient; no explicit teardown is needed.
    """
    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path / "default")},
        },
        "sitemaps": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path / "alias")},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }


def _apply_alias():
    """Patch icv_sitemaps.conf.ICV_STORAGES_ALIAS to "sitemaps"; returns a context manager."""
    return patch("icv_sitemaps.conf.ICV_STORAGES_ALIAS", "sitemaps")


_GENERATION_CONF_PATCHES = {
    "ICV_SITEMAPS_GZIP": False,
    "ICV_SITEMAPS_STORAGE_PATH": "sitemaps/",
    "ICV_SITEMAPS_BASE_URL": "https://example.com",
    "ICV_SITEMAPS_MAX_URLS_PER_FILE": 50000,
    "ICV_SITEMAPS_MAX_FILE_SIZE_BYTES": 52428800,
    "ICV_SITEMAPS_BATCH_SIZE": 5000,
    "ICV_SITEMAPS_PING_ENABLED": False,
    "ICV_SITEMAPS_NEWS_MAX_AGE_DAYS": 2,
}


def _apply_generation_conf_patches():
    import icv_sitemaps.conf as conf_mod

    stack = ExitStack()
    for attr, value in _GENERATION_CONF_PATCHES.items():
        stack.enter_context(patch.object(conf_mod, attr, value))
    stack.enter_context(_apply_alias())
    return stack


class TestSitemapViewsFollowTheAlias:
    def test_shard_served_and_absent_from_default(self, db, tmp_path, settings, client):
        _configure_two_aliases(settings, tmp_path)

        section = StaticSitemapSectionFactory(
            name="alias-routed",
            settings={"urls": [{"loc": "/pricing/"}, {"loc": "/about/"}]},
        )

        with _apply_generation_conf_patches():
            generate_section(section)

        from icv_sitemaps.models import SitemapFile

        sitemap_file = SitemapFile.objects.get(section=section)

        assert storages["sitemaps"].exists(sitemap_file.storage_path), (
            "generation did not write the shard into the configured alias"
        )
        assert not storages["default"].exists(sitemap_file.storage_path), (
            "generation wrote the shard into the default storage instead of the alias"
        )

        filename = sitemap_file.storage_path.rsplit("/", 1)[-1]

        with _apply_alias():
            index_response = client.get("/sitemap.xml")
            shard_response = client.get(f"/sitemaps/{filename}")

        assert index_response.status_code == 200, "SITEMAP 404 BECAUSE VIEW READ THE WRONG STORAGE"
        assert shard_response.status_code == 200, "SITEMAP 404 BECAUSE VIEW READ THE WRONG STORAGE"


class TestPruneFollowsTheAlias:
    def test_cleanup_deletes_only_from_the_configured_alias(self, db, tmp_path, settings):
        _configure_two_aliases(settings, tmp_path)

        with _apply_alias():
            storages["sitemaps"].save("sitemaps/orphan.xml", ContentFile(b"<urlset></urlset>"))
        storages["default"].save("sitemaps/orphan.xml", ContentFile(b"<urlset></urlset>"))

        with patch("icv_sitemaps.conf.ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"), _apply_alias():
            deleted = cleanup_orphan_files()

        assert deleted == 1, "PRUNE RAN AGAINST THE WRONG STORAGE"
        assert not storages["sitemaps"].exists("sitemaps/orphan.xml"), "PRUNE RAN AGAINST THE WRONG STORAGE"
        assert storages["default"].exists("sitemaps/orphan.xml"), "PRUNE RAN AGAINST THE WRONG STORAGE"


class TestValidateCommandFollowsTheAlias:
    def test_generated_file_is_not_reported_missing(self, db, tmp_path, settings):
        _configure_two_aliases(settings, tmp_path)

        section = StaticSitemapSectionFactory(
            name="alias-validate",
            settings={"urls": [{"loc": "/pricing/"}]},
        )

        with _apply_generation_conf_patches():
            generate_section(section)

        out = StringIO()
        with _apply_alias():
            call_command("icv_sitemaps_validate", stdout=out)

        output = out.getvalue()
        assert "File not found in storage" not in output
        assert "PASS" in output


class TestSetupCommandFollowsTheAlias:
    def test_storage_check_writes_through_the_alias(self, db, tmp_path, settings):
        _configure_two_aliases(settings, tmp_path)

        out = StringIO()
        with _apply_alias():
            call_command("icv_sitemaps_setup", stdout=out)

        assert "Storage connectivity verified" in out.getvalue()
        # The round-trip test file is written and deleted before the command
        # returns, so its absence afterwards proves nothing either way; what
        # matters is that the default alias's directory was never created at
        # all, since the command never touched it.
        assert not (tmp_path / "default").exists(), "SETUP COMMAND WROTE THROUGH THE DEFAULT ALIAS, NOT THE OVERRIDE"


class TestDefaultIsStoragesDefaultAlias:
    def test_get_storage_is_storages_default_with_nothing_configured(self, db):
        assert get_storage() is storages["default"]
        assert isinstance(get_storage(), Storage)
