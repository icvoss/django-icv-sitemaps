"""
Management command to manage redirect rules.

Supports listing, importing (CSV), exporting (CSV), and pruning expired rules.
"""

import csv
import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Manage redirect rules — list, import (CSV), export (CSV), prune expired"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--list",
            action="store_true",
            dest="list_rules",
            help="List active redirect rules",
        )
        group.add_argument(
            "--import",
            type=str,
            dest="import_file",
            metavar="FILE",
            help="Import redirects from a CSV file (columns: source_pattern,destination,status_code,match_type,name)",
        )
        group.add_argument(
            "--export",
            type=str,
            dest="export_file",
            metavar="FILE",
            help="Export active redirects to a CSV file",
        )
        group.add_argument(
            "--prune",
            action="store_true",
            help="Remove expired redirect rules",
        )
        group.add_argument(
            "--top-404s",
            action="store_true",
            dest="top_404s",
            help="Show top unresolved 404 paths",
        )
        parser.add_argument(
            "--tenant",
            type=str,
            default="",
            metavar="TENANT",
            help="Tenant ID (default: empty for single-tenant)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Limit for --list and --top-404s (default: 50)",
        )

    def handle(self, **options):
        tenant_id = options["tenant"]

        if options["list_rules"]:
            self._list_rules(tenant_id, options["limit"])
        elif options["import_file"]:
            self._import_csv(options["import_file"], tenant_id)
        elif options["export_file"]:
            self._export_csv(options["export_file"], tenant_id)
        elif options["prune"]:
            self._prune_expired(tenant_id)
        elif options["top_404s"]:
            self._top_404s(tenant_id, options["limit"])

    def _list_rules(self, tenant_id: str, limit: int) -> None:
        from icv_sitemaps.models.redirects import RedirectRule

        rules = RedirectRule.objects.active().filter(tenant_id=tenant_id).order_by("priority")[:limit]
        if not rules:
            self.stdout.write("No active redirect rules found.")
            return

        for rule in rules:
            dest = rule.destination or "410 Gone"
            self.stdout.write(
                f"  [{rule.priority}] {rule.source_pattern} -> {dest} "
                f"({rule.status_code}, {rule.match_type}, hits={rule.hit_count})"
            )

    def _import_csv(self, filepath: str, tenant_id: str) -> None:
        from icv_sitemaps.services.redirects import bulk_import_redirects

        try:
            with open(filepath, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except FileNotFoundError as exc:
            raise CommandError(f"File not found: {filepath}") from exc
        except Exception as exc:
            raise CommandError(f"Error reading CSV: {exc}") from exc

        if not rows:
            self.stdout.write("CSV file is empty.")
            return

        result = bulk_import_redirects(rows, tenant_id=tenant_id, source="import")
        self.stdout.write(
            f"Import complete: {result['created']} created, "
            f"{result['updated']} updated, {len(result['errors'])} errors."
        )
        for error in result["errors"]:
            self.stderr.write(f"  Row {error['row']}: {error['error']}")

    def _export_csv(self, filepath: str, tenant_id: str) -> None:
        from icv_sitemaps.models.redirects import RedirectRule

        rules = RedirectRule.objects.active().filter(tenant_id=tenant_id).order_by("priority")
        fieldnames = ["source_pattern", "destination", "status_code", "match_type", "name"]

        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rule in rules:
                writer.writerow(
                    {
                        "source_pattern": rule.source_pattern,
                        "destination": rule.destination,
                        "status_code": rule.status_code,
                        "match_type": rule.match_type,
                        "name": rule.name,
                    }
                )

        self.stdout.write(f"Exported {rules.count()} rule(s) to {filepath}.")

    def _prune_expired(self, tenant_id: str) -> None:
        from django.utils import timezone

        from icv_sitemaps.models.redirects import RedirectRule

        qs = RedirectRule.objects.filter(expires_at__isnull=False, expires_at__lt=timezone.now())
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        deleted, _ = qs.delete()
        self.stdout.write(f"Pruned {deleted} expired redirect rule(s).")

    def _top_404s(self, tenant_id: str, limit: int) -> None:
        from icv_sitemaps.services.redirects import get_top_404s

        entries = get_top_404s(tenant_id=tenant_id, limit=limit, min_hits=1)
        if not entries:
            self.stdout.write("No unresolved 404 entries found.")
            return

        for entry in entries:
            self.stdout.write(f"  {entry.path} ({entry.hit_count} hits, last: {entry.last_seen_at})")
