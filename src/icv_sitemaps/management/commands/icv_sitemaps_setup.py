"""
Management command to set up sitemap sections from ICV_SITEMAPS_AUTO_SECTIONS
and verify storage connectivity.
"""

import logging

from django.apps import apps
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create SitemapSection records from ICV_SITEMAPS_AUTO_SECTIONS and verify storage connectivity"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE — no changes will be made"))

        self.stdout.write("Setting up icv-sitemaps...")

        # Verify storage connectivity first
        self.stdout.write("\nVerifying storage connectivity...")
        storage_ok = self._verify_storage(dry_run)
        if not storage_ok:
            self.stdout.write(self.style.ERROR("Storage verification failed. Aborting setup."))
            return

        # Create sections from AUTO_SECTIONS setting
        self.stdout.write("\nProcessing AUTO_SECTIONS...")
        created, existing, errors = self._create_sections(dry_run)

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("SETUP SUMMARY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Created:   {created}")
        self.stdout.write(f"Existing:  {existing}")
        self.stdout.write(f"Errors:    {errors}")
        self.stdout.write("=" * 60)

        if errors:
            self.stdout.write(self.style.WARNING(f"Setup completed with {errors} error(s). Check output above."))
        else:
            self.stdout.write(self.style.SUCCESS("Setup complete."))

    def _verify_storage(self, dry_run: bool) -> bool:
        """Test storage write/read/delete to verify connectivity."""
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from icv_sitemaps.conf import ICV_SITEMAPS_STORAGE_PATH

        test_path = f"{ICV_SITEMAPS_STORAGE_PATH}_setup_test.txt"

        if dry_run:
            self.stdout.write(f"  Would write test file to: {test_path}")
            return True

        try:
            # Write
            default_storage.save(test_path, ContentFile(b"icv-sitemaps-setup-test"))
            self.stdout.write(f"  Write OK: {test_path}")

            # Read
            with default_storage.open(test_path) as fh:
                content = fh.read()
            if content != b"icv-sitemaps-setup-test":
                raise RuntimeError("Storage read-back content mismatch during verification.")
            self.stdout.write("  Read OK")

            # Delete
            default_storage.delete(test_path)
            self.stdout.write("  Delete OK")

            self.stdout.write(self.style.SUCCESS("  Storage connectivity verified."))
            return True

        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Storage check failed: {exc}"))
            logger.exception("Storage verification failed during setup")
            return False

    def _create_sections(self, dry_run: bool) -> tuple[int, int, int]:
        """Create SitemapSection records for each entry in AUTO_SECTIONS."""
        from django.conf import settings

        from icv_sitemaps.models import SitemapSection

        auto_sections: dict = getattr(settings, "ICV_SITEMAPS_AUTO_SECTIONS", {})

        if not auto_sections:
            self.stdout.write("  ICV_SITEMAPS_AUTO_SECTIONS is empty — nothing to create.")
            return 0, 0, 0

        created = 0
        existing = 0
        errors = 0

        for name, config in auto_sections.items():
            model_path = config.get("model", config.get("model_path", ""))
            tenant_id = config.get("tenant_id", "")
            sitemap_type = config.get("sitemap_type", "standard")
            changefreq = config.get("changefreq", "daily")
            priority = config.get("priority", "0.5")
            section_settings = config.get("settings", {})

            # Resolve model class to validate the path
            try:
                app_label, model_name = model_path.rsplit(".", 1)
                apps.get_model(app_label, model_name)
            except (ValueError, LookupError) as exc:
                self.stdout.write(self.style.ERROR(f"  [{name}] Cannot resolve model '{model_path}': {exc}"))
                errors += 1
                continue

            # Check existence
            if SitemapSection.objects.filter(name=name, tenant_id=tenant_id).exists():
                self.stdout.write(f"  [{name}] Already exists — skipping")
                existing += 1
                continue

            if dry_run:
                self.stdout.write(f"  [{name}] Would create SitemapSection (model={model_path}, type={sitemap_type})")
                created += 1
                continue

            try:
                SitemapSection.objects.create(
                    name=name,
                    tenant_id=tenant_id,
                    model_path=model_path,
                    sitemap_type=sitemap_type,
                    changefreq=changefreq,
                    priority=priority,
                    settings=section_settings,
                )
                self.stdout.write(self.style.SUCCESS(f"  [{name}] Created (model={model_path}, type={sitemap_type})"))
                created += 1
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  [{name}] Failed to create: {exc}"))
                logger.exception("Failed to create SitemapSection '%s'", name)
                errors += 1

        return created, existing, errors
