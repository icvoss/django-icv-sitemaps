"""
Management command to display sitemap generation statistics.
"""

import logging

from django.core.management.base import BaseCommand
from django.db.models import Sum

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Display sitemap generation statistics (sections, URLs, files, size, last run)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            type=str,
            default="",
            metavar="TENANT",
            help="Tenant ID for multi-tenant setups",
        )

    def handle(self, *args, **options):
        tenant_id: str = options["tenant"]

        from icv_sitemaps.models import SitemapFile, SitemapGenerationLog, SitemapSection

        # Build base queryset scoped by tenant
        sections_qs = SitemapSection.objects.filter(tenant_id=tenant_id)
        files_qs = SitemapFile.objects.filter(section__tenant_id=tenant_id)

        total_sections = sections_qs.count()
        active_sections = sections_qs.filter(is_active=True).count()
        stale_sections = sections_qs.filter(is_active=True, is_stale=True).count()

        url_totals = sections_qs.aggregate(total=Sum("url_count"))
        total_urls = url_totals["total"] or 0

        # file_count comes from the SitemapSection aggregate, not SitemapFile
        section_file_totals = sections_qs.aggregate(total_files=Sum("file_count"))
        total_files = section_file_totals["total_files"] or 0

        total_size_bytes = files_qs.aggregate(total=Sum("file_size_bytes"))["total"] or 0

        # Last generation time (most recent successful log entry)
        last_log = (
            SitemapGenerationLog.objects.filter(
                status="success",
                section__tenant_id=tenant_id,
            )
            .order_by("-created_at")
            .first()
        )
        last_generated = last_log.created_at if last_log else None

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("SITEMAP STATISTICS"))
        if tenant_id:
            self.stdout.write(f"Tenant: {tenant_id}")
        self.stdout.write("=" * 60)

        self.stdout.write(f"Total sections:      {total_sections}")
        self.stdout.write(
            f"Active sections:     {active_sections}"
            + (f"  ({total_sections - active_sections} inactive)" if total_sections > active_sections else "")
        )

        if stale_sections:
            self.stdout.write(self.style.WARNING(f"Stale sections:      {stale_sections} (need regeneration)"))
        else:
            self.stdout.write(f"Stale sections:      {stale_sections}")

        self.stdout.write(f"Total URLs:          {total_urls:,}")
        self.stdout.write(f"Total files:         {total_files}")
        self.stdout.write(f"Total size:          {self._format_bytes(total_size_bytes)}")

        if last_generated:
            self.stdout.write(f"Last generated:      {last_generated.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        else:
            self.stdout.write(self.style.WARNING("Last generated:      never"))

        # Per-section breakdown
        if total_sections > 0:
            self.stdout.write("\n" + "-" * 60)
            self.stdout.write("SECTION BREAKDOWN")
            self.stdout.write("-" * 60)
            self.stdout.write(f"{'Name':<30} {'Type':<12} {'URLs':>8} {'Files':>6} {'Stale':>6}")
            self.stdout.write("-" * 60)

            for section in sections_qs.order_by("name"):
                stale_marker = "*" if section.is_stale else ""
                inactive_marker = " (inactive)" if not section.is_active else ""
                self.stdout.write(
                    f"{section.name:<30} {section.sitemap_type:<12} "
                    f"{section.url_count:>8,} {section.file_count:>6} "
                    f"{stale_marker:>6}{inactive_marker}"
                )

            if stale_sections:
                self.stdout.write("  * = stale (needs regeneration)")

        self.stdout.write("=" * 60)

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        """Format byte count as human-readable string."""
        for unit in ("B", "KB", "MB", "GB"):
            if num_bytes < 1024:
                return f"{num_bytes:.1f} {unit}"
            num_bytes /= 1024
        return f"{num_bytes:.1f} TB"
