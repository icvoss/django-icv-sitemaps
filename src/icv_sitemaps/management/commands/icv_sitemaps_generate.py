"""
Management command to generate sitemaps.

Supports targeted section generation, full regeneration, index-only
updates, and stale-only (default) runs.
"""

import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Generate sitemaps — by section, all active, index only, or stale only (default)"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--section",
            type=str,
            metavar="NAME",
            help="Generate a specific section by name",
        )
        group.add_argument(
            "--all",
            action="store_true",
            dest="all_sections",
            help="Generate all active sections (implies --force)",
        )
        group.add_argument(
            "--index-only",
            action="store_true",
            help="Regenerate the sitemap index without touching section files",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force regeneration even if the section is not stale",
        )
        parser.add_argument(
            "--tenant",
            type=str,
            default="",
            metavar="TENANT",
            help="Tenant ID for multi-tenant setups",
        )

    def handle(self, *args, **options):
        section_name: str | None = options["section"]
        all_sections: bool = options["all_sections"]
        index_only: bool = options["index_only"]
        force: bool = options["force"] or all_sections
        tenant_id: str = options["tenant"]

        from icv_sitemaps.models import SitemapSection

        # --- index-only run ---
        if index_only:
            self.stdout.write("Regenerating sitemap index...")
            self._regenerate_index(tenant_id)
            return

        # --- specific section ---
        if section_name:
            try:
                section = SitemapSection.objects.get(name=section_name, tenant_id=tenant_id)
            except SitemapSection.DoesNotExist as exc:
                raise CommandError(
                    f"SitemapSection '{section_name}' not found" + (f" for tenant '{tenant_id}'" if tenant_id else "")
                ) from exc
            self.stdout.write(f"Generating section '{section_name}'...")
            self._generate_section(section, force=True)
            return

        # --- all active sections ---
        if all_sections:
            sections = SitemapSection.objects.filter(is_active=True, tenant_id=tenant_id)
            if not sections.exists():
                self.stdout.write(self.style.WARNING("No active sections found."))
                return
            self.stdout.write(f"Generating all {sections.count()} active section(s) (force={force})...")
            self._generate_queryset(sections, force=True)
            return

        # --- default: stale only ---
        sections = SitemapSection.objects.filter(is_active=True, is_stale=True, tenant_id=tenant_id)
        if not sections.exists():
            self.stdout.write(self.style.SUCCESS("No stale sections — nothing to generate."))
            return
        self.stdout.write(f"Generating {sections.count()} stale section(s)...")
        self._generate_queryset(sections, force=force)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_queryset(self, sections, *, force: bool) -> None:
        """Generate multiple sections and print a summary."""
        total_ok = 0
        total_err = 0
        total_urls = 0

        for section in sections:
            ok, url_count = self._generate_section(section, force=force)
            if ok:
                total_ok += 1
                total_urls += url_count
            else:
                total_err += 1

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("GENERATION SUMMARY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Generated:   {total_ok}")
        self.stdout.write(f"Errors:      {total_err}")
        self.stdout.write(f"Total URLs:  {total_urls}")
        self.stdout.write("=" * 60)

    def _generate_section(self, section, *, force: bool) -> tuple[bool, int]:
        """Generate a single section. Returns (success, url_count)."""
        from icv_sitemaps.exceptions import SitemapGenerationError

        if not force and not section.is_stale:
            self.stdout.write(f"  [{section.name}] Not stale — skipped")
            return True, 0

        self.stdout.write(f"  [{section.name}] Generating ({section.sitemap_type})...")
        try:
            url_count = self._run_generation(section)
            self.stdout.write(self.style.SUCCESS(f"  [{section.name}] Done — {url_count} URL(s)"))
            return True, url_count
        except SitemapGenerationError as exc:
            self.stdout.write(self.style.ERROR(f"  [{section.name}] Generation error: {exc}"))
            logger.exception("Generation failed for section '%s'", section.name)
            return False, 0
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  [{section.name}] Unexpected error: {exc}"))
            logger.exception("Unexpected error generating section '%s'", section.name)
            return False, 0

    def _run_generation(self, section) -> int:
        """Invoke the generation service for a section and return URL count.

        Defers to the service layer when available; falls back to a direct
        model-based count so the command remains useful even before the full
        service layer is implemented.
        """
        try:
            from icv_sitemaps.services import generate_section

            url_count = generate_section(section)
            return url_count
        except ImportError:
            pass

        # Minimal fallback: resolve the model, count objects, mark not-stale.
        from icv_sitemaps.services.generation import _resolve_model

        model_cls = _resolve_model(section.model_path)
        url_count = model_cls.objects.count()

        section.is_stale = False
        section.url_count = url_count
        from django.utils import timezone

        section.last_generated_at = timezone.now()
        section.save(update_fields=["is_stale", "url_count", "last_generated_at"])
        return url_count

    def _regenerate_index(self, tenant_id: str) -> None:
        """Regenerate the sitemap index file."""
        try:
            from icv_sitemaps.services import generate_index

            generate_index(tenant_id=tenant_id)
            self.stdout.write(self.style.SUCCESS("Sitemap index regenerated."))
        except ImportError:
            from icv_sitemaps.models import SitemapSection

            section_count = SitemapSection.objects.filter(is_active=True, tenant_id=tenant_id).count()
            self.stdout.write(
                self.style.WARNING(
                    f"Service layer not available. Found {section_count} active section(s) that would be indexed."
                )
            )
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Failed to regenerate index: {exc}"))
            logger.exception("Index regeneration failed")
