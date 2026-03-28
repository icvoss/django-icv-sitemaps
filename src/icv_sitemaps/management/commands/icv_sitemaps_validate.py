"""
Management command to validate generated sitemaps against the sitemap protocol.

Checks per file:
  - URL count <= 50,000
  - File size <= 50 MB
  - Valid XML structure
  - All <loc> values are absolute URLs
"""

import logging
import xml.etree.ElementTree as ET

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

# Sitemap XML namespaces
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
NEWS_NS = "http://www.google.com/schemas/sitemap-news/0.9"
IMAGE_NS = "http://www.google.com/schemas/sitemap-image/1.1"
VIDEO_NS = "http://www.google.com/schemas/sitemap-video/1.1"

MAX_URLS = 50_000
MAX_BYTES = 52_428_800  # 50 MiB


class Command(BaseCommand):
    help = "Validate generated sitemaps against the sitemap protocol"

    def add_arguments(self, parser):
        parser.add_argument(
            "--section",
            type=str,
            default="",
            metavar="NAME",
            help="Validate files for a specific section only",
        )

    def handle(self, *args, **options):
        section_name: str = options["section"]

        from icv_sitemaps.models import SitemapFile, SitemapSection

        if section_name:
            try:
                section = SitemapSection.objects.get(name=section_name)
            except SitemapSection.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"SitemapSection '{section_name}' not found."))
                return
            files = SitemapFile.objects.filter(section=section).select_related("section")
            self.stdout.write(f"Validating {files.count()} file(s) for section '{section_name}'...\n")
        else:
            files = SitemapFile.objects.select_related("section").order_by("section__name", "sequence")
            self.stdout.write(f"Validating {files.count()} sitemap file(s)...\n")

        if not files.exists():
            self.stdout.write(self.style.WARNING("No sitemap files found to validate."))
            return

        passed = 0
        failed = 0

        for sitemap_file in files:
            ok, issues = self._validate_file(sitemap_file)
            label = f"{sitemap_file.section.name}/{sitemap_file.sequence}"
            if ok:
                self.stdout.write(self.style.SUCCESS(f"  PASS  {label}"))
                passed += 1
            else:
                self.stdout.write(self.style.ERROR(f"  FAIL  {label}"))
                for issue in issues:
                    self.stdout.write(self.style.ERROR(f"        - {issue}"))
                failed += 1

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"VALIDATION COMPLETE — passed: {passed}, failed: {failed}")
        self.stdout.write("=" * 60)

        if failed:
            self.stdout.write(self.style.ERROR(f"{failed} file(s) failed validation."))
        else:
            self.stdout.write(self.style.SUCCESS("All files passed validation."))

    # ------------------------------------------------------------------
    # Validation logic
    # ------------------------------------------------------------------

    def _validate_file(self, sitemap_file) -> tuple[bool, list[str]]:
        """Validate a single SitemapFile record. Returns (passed, issues)."""
        issues: list[str] = []

        # 1. Check recorded metadata first (fast, no I/O)
        if sitemap_file.url_count > MAX_URLS:
            issues.append(f"URL count {sitemap_file.url_count} exceeds protocol limit of {MAX_URLS}")
        if sitemap_file.file_size_bytes > MAX_BYTES:
            issues.append(
                f"File size {sitemap_file.file_size_bytes} bytes exceeds protocol limit of {MAX_BYTES} bytes (50 MiB)"
            )

        # 2. Attempt to load and parse the XML from storage
        xml_content = self._read_file_content(sitemap_file, issues)
        if xml_content is None:
            return False, issues

        # 3. Parse XML
        root = self._parse_xml(xml_content, issues)
        if root is None:
            return False, issues

        # 4. Validate <loc> elements contain absolute URLs
        self._validate_loc_elements(root, issues)

        return len(issues) == 0, issues

    def _read_file_content(self, sitemap_file, issues: list[str]) -> bytes | None:
        """Read raw file content from storage. Returns None and appends to issues on failure."""
        from django.core.files.storage import default_storage

        storage_path = sitemap_file.storage_path

        try:
            if not default_storage.exists(storage_path):
                issues.append(f"File not found in storage: {storage_path}")
                return None

            with default_storage.open(storage_path, "rb") as fh:
                content = fh.read()

            # Handle gzip transparently
            if storage_path.endswith(".gz") or content[:2] == b"\x1f\x8b":
                import gzip

                content = gzip.decompress(content)

            return content

        except Exception as exc:
            issues.append(f"Failed to read from storage ({storage_path}): {exc}")
            logger.exception("Failed to read sitemap file '%s' during validation", storage_path)
            return None

    def _parse_xml(self, content: bytes, issues: list[str]) -> ET.Element | None:
        """Parse XML content. Returns root element or None on failure."""
        try:
            root = ET.fromstring(content)
            return root
        except ET.ParseError as exc:
            issues.append(f"Invalid XML: {exc}")
            return None

    def _validate_loc_elements(self, root: ET.Element, issues: list[str]) -> None:
        """Check that all <loc> elements contain absolute URLs."""
        # Support both sitemap index and urlset
        loc_elements = root.findall(f".//{{{SITEMAP_NS}}}loc")

        if not loc_elements:
            # Try without namespace (some generators omit the default namespace)
            loc_elements = root.findall(".//loc")

        invalid_locs: list[str] = []
        for loc in loc_elements:
            value = (loc.text or "").strip()
            if not value.startswith(("http://", "https://")):
                invalid_locs.append(value or "(empty)")

        if invalid_locs:
            sample = invalid_locs[:3]
            more = len(invalid_locs) - 3
            sample_str = ", ".join(f"'{v}'" for v in sample)
            suffix = f" (+{more} more)" if more > 0 else ""
            issues.append(f"{len(invalid_locs)} <loc> element(s) are not absolute URLs: {sample_str}{suffix}")
