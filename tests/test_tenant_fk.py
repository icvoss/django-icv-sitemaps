"""Tests for the tenant_ref FK on the six tenant-keyed models (issue #50).

Conf names are import-time constants (``icv_sitemaps.conf``), and
``ICV_TENANT_MODEL`` is additionally baked into swappable migration
metadata and each model's FK target at class-definition time (ADR-019
section 2 fall-through-floor pattern, mirroring ``tests/test_models.py``'s
``ICV_AUTH_USER_MODEL`` coverage). A subprocess run is required wherever the
test needs the FK to actually target a different model, because the target
is resolved once at import time and cannot be patched into an
already-loaded model class in this process.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import override_settings

from icv_sitemaps.models import (
    AdsEntry,
    DiscoveryFileConfig,
    RedirectLog,
    RedirectRule,
    RobotsRule,
    SitemapSection,
)
from icv_sitemaps.testing.factories import RedirectRuleFactory, SitemapSectionFactory

TENANT_KEYED_MODELS = [SitemapSection, RobotsRule, AdsEntry, DiscoveryFileConfig, RedirectRule, RedirectLog]

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestDefaultTenantModelIsAuthGroupFloor:
    """Under default settings, every tenant_ref FK targets the auth.Group floor."""

    @pytest.mark.parametrize("model", TENANT_KEYED_MODELS)
    def test_tenant_ref_targets_auth_group(self, model):
        field = model._meta.get_field("tenant_ref")
        assert field.remote_field.model._meta.label == "auth.Group"


class TestTenantModelOverride:
    """Subprocess coverage: the FK follows ICV_TENANT_MODEL, not a hardcoded floor."""

    def _run_field_target_probe(self, model_import: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import django; django.setup(); "
                f"from icv_sitemaps.models import {model_import}; "
                f"print({model_import}._meta.get_field('tenant_ref').remote_field.model._meta.label)",
            ],
            env={
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "settings",
                "PYTHONPATH": "src:tests",
                "ICV_SITEMAPS_TEST_TENANT_OVERRIDE": "sitemaps_testapp.Tenant",
            },
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

    def test_tenant_ref_follows_the_override(self):
        result = self._run_field_target_probe("SitemapSection")
        assert result.stdout.strip() == "sitemaps_testapp.Tenant", (
            f"TENANT_REF FK IGNORES ICV_TENANT_MODEL: stderr={result.stderr!r}"
        )

    def test_makemigrations_check_is_clean_under_the_override(self):
        """0009_tenant_ref's swappable_dependency resolves consistently with the override.

        Runs makemigrations --check --dry-run in the same subprocess as the
        override, inside override_settings(MIGRATION_MODULES={}) so the
        loader sees icv_sitemaps' own shipped migrations for this one check
        (mirrors tests/test_models.py's equivalent default-settings check).
        """
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import django; django.setup(); "
                "from django.test import override_settings; "
                "from django.core.management import call_command; "
                "from django.core.management.base import CommandError; "
                "cm = override_settings(MIGRATION_MODULES={}); "
                "cm.enable(); "
                "call_command('makemigrations', 'icv_sitemaps', '--check', '--dry-run', verbosity=0); "
                "cm.disable(); "
                "print('CLEAN')",
            ],
            env={
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "settings",
                "PYTHONPATH": "src:tests",
                "ICV_SITEMAPS_TEST_TENANT_OVERRIDE": "sitemaps_testapp.Tenant",
            },
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        assert result.stdout.strip().endswith("CLEAN"), (
            f"makemigrations --check reported drift under the override: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


class TestMakemigrationsCheckIsCleanWithTheFloorUnset:
    """0009_tenant_ref stays byte-stable under the default auth.Group floor."""

    def test_makemigrations_check_is_clean(self, db):
        with override_settings(MIGRATION_MODULES={}):
            try:
                call_command("makemigrations", "icv_sitemaps", "--check", "--dry-run", verbosity=0)
            except (SystemExit, CommandError) as exc:
                pytest.fail(f"makemigrations --check reported drift against the shipped migrations: {exc!r}")


class TestTenantIdConsistency:
    """sync_tenant_key: derive tenant_id from tenant_ref, never silently overwrite a mismatch."""

    def test_save_derives_blank_tenant_id_from_tenant_ref(self, db):
        from django.contrib.auth.models import Group

        group = Group.objects.create(name="acme")
        section = SitemapSection(
            name="products",
            model_path="myapp.models.Product",
            tenant_ref=group,
        )
        section.save()

        assert section.tenant_id == str(group.pk)

    def test_save_raises_on_mismatched_tenant_id(self, db):
        from django.contrib.auth.models import Group

        group = Group.objects.create(name="acme")
        section = SitemapSection(
            name="products",
            model_path="myapp.models.Product",
            tenant_id="other",
            tenant_ref=group,
        )

        with pytest.raises(ValidationError):
            section.save()

    def test_clean_derives_blank_tenant_id_from_tenant_ref(self, db):
        from django.contrib.auth.models import Group

        group = Group.objects.create(name="acme")
        rule = RedirectRuleFactory.build(tenant_id="", tenant_ref=group)

        rule.clean()

        assert rule.tenant_id == str(group.pk)

    def test_clean_raises_on_mismatched_tenant_id(self, db):
        from django.contrib.auth.models import Group

        group = Group.objects.create(name="acme")
        rule = RedirectRuleFactory.build(tenant_id="mismatch", tenant_ref=group)

        with pytest.raises(ValidationError):
            rule.clean()

    def test_string_only_tenant_id_saves_unchanged_without_a_tenant_ref(self, db):
        section = SitemapSectionFactory(name="legacy", tenant_id="acme", tenant_ref=None)

        section.refresh_from_db()

        assert section.tenant_id == "acme"
        assert section.tenant_ref_id is None


class TestTenantRefCascade:
    def test_deleting_the_tenant_deletes_referencing_rows_and_spares_string_only_rows(self, db):
        from django.contrib.auth.models import Group

        group = Group.objects.create(name="acme")
        fk_section = SitemapSection.objects.create(
            name="fk-scoped",
            model_path="myapp.models.Product",
            tenant_ref=group,
        )
        string_section = SitemapSectionFactory(name="string-scoped", tenant_id="other-tenant", tenant_ref=None)

        group.delete()

        assert not SitemapSection.objects.filter(pk=fk_section.pk).exists()
        assert SitemapSection.objects.filter(pk=string_section.pk).exists()


class TestMigrationProvenance:
    """0009_tenant_ref declares a swappable dependency and matching AddField targets."""

    def test_migration_declares_swappable_dependency_and_field_targets(self):
        import importlib

        from django.db import migrations

        from icv_sitemaps import conf

        migration_module = importlib.import_module("icv_sitemaps.migrations.0009_tenant_ref")
        migration = migration_module.Migration

        expected_dependency = migrations.swappable_dependency(conf.ICV_TENANT_MODEL)
        assert expected_dependency in migration.dependencies, (
            "0009_tenant_ref does not declare swappable_dependency(ICV_TENANT_MODEL)"
        )

        add_field_ops = [op for op in migration.operations if isinstance(op, migrations.AddField)]
        assert len(add_field_ops) == 6, f"expected 6 AddField operations, found {len(add_field_ops)}"

        expected_target = conf.ICV_TENANT_MODEL.lower()
        for op in add_field_ops:
            assert op.name == "tenant_ref"
            field_target = op.field.remote_field.model
            resolved_target = field_target if isinstance(field_target, str) else field_target._meta.label
            assert resolved_target.lower() == expected_target, (
                f"{op.model_name}.tenant_ref targets {resolved_target!r}, expected {expected_target!r}"
            )
