"""
Management command to ping search engines with the sitemap URL.
"""

import logging
import urllib.error
import urllib.parse
import urllib.request

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

# Import canonical endpoint map from the ping service to avoid divergence.
# The inline fallback uses this dict via the ``{url}`` placeholder convention.
from icv_sitemaps.services.ping import _PING_URLS as _SERVICE_PING_URLS  # noqa: E402

# Build a fallback dict using the same template strings but with `{url}` as
# the placeholder (the inline _ping_inline method uses `{url}`, not `{sitemap_url}`).
PING_ENDPOINTS: dict[str, str] = {
    engine: template.replace("{sitemap_url}", "{url}") for engine, template in _SERVICE_PING_URLS.items()
}


class Command(BaseCommand):
    help = "Ping search engines with the sitemap URL to trigger re-crawling"

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            type=str,
            default="",
            metavar="URL",
            help="Override the sitemap URL to submit (uses ICV_SITEMAPS_BASE_URL if omitted)",
        )
        parser.add_argument(
            "--tenant",
            type=str,
            default="",
            metavar="TENANT",
            help="Tenant ID for multi-tenant setups",
        )

    def handle(self, *args, **options):
        sitemap_url: str = options["url"]
        tenant_id: str = options["tenant"]

        from icv_sitemaps.conf import ICV_SITEMAPS_BASE_URL, ICV_SITEMAPS_PING_ENABLED

        if not ICV_SITEMAPS_PING_ENABLED:
            self.stdout.write(
                self.style.WARNING("ICV_SITEMAPS_PING_ENABLED is False — pinging disabled. Set it to True to enable.")
            )
            return

        if not sitemap_url:
            sitemap_url = self._resolve_sitemap_url(ICV_SITEMAPS_BASE_URL, tenant_id)

        if not sitemap_url:
            self.stdout.write(self.style.ERROR("No sitemap URL available. Set ICV_SITEMAPS_BASE_URL or pass --url."))
            return

        self.stdout.write(f"Pinging search engines for: {sitemap_url}\n")

        # Try service layer first; fall back to inline implementation
        try:
            from icv_sitemaps.services import ping_search_engines

            results = ping_search_engines(sitemap_url=sitemap_url, tenant_id=tenant_id)
            self._print_results(results)
            return
        except ImportError:
            pass

        # Inline fallback
        results = self._ping_inline(sitemap_url)
        self._print_results(results)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_sitemap_url(self, base_url: str, tenant_id: str) -> str:
        """Build the sitemap index URL from the configured base URL."""
        if not base_url:
            return ""
        base_url = base_url.rstrip("/")
        path = "/sitemap.xml"
        if tenant_id:
            path = f"/sitemap-{tenant_id}.xml"
        return f"{base_url}{path}"

    def _ping_inline(self, sitemap_url: str) -> dict[str, dict]:
        """Ping each configured engine directly and return results."""
        from icv_sitemaps.conf import ICV_SITEMAPS_PING_ENGINES

        results: dict[str, dict] = {}

        for engine in ICV_SITEMAPS_PING_ENGINES:
            endpoint_template = PING_ENDPOINTS.get(engine)
            if not endpoint_template:
                results[engine] = {
                    "success": False,
                    "status_code": None,
                    "error": f"Unknown engine '{engine}' — no ping endpoint configured",
                }
                continue

            ping_url = endpoint_template.format(url=urllib.parse.quote(sitemap_url, safe=""))
            try:
                with urllib.request.urlopen(ping_url, timeout=10) as response:
                    status_code = response.getcode()
                    success = 200 <= status_code < 300
                    results[engine] = {
                        "success": success,
                        "status_code": status_code,
                        "error": "" if success else f"HTTP {status_code}",
                    }
            except urllib.error.HTTPError as exc:
                results[engine] = {
                    "success": False,
                    "status_code": exc.code,
                    "error": str(exc),
                }
                logger.warning("Ping to %s returned HTTP %s", engine, exc.code)
            except Exception as exc:
                results[engine] = {
                    "success": False,
                    "status_code": None,
                    "error": str(exc),
                }
                logger.exception("Ping to %s failed", engine)

        return results

    def _print_results(self, results: dict) -> None:
        """Print per-engine ping results."""
        self.stdout.write("=" * 50)
        self.stdout.write("PING RESULTS")
        self.stdout.write("=" * 50)

        all_ok = True
        for engine, result in results.items():
            if result.get("success"):
                status_code = result.get("status_code", "")
                self.stdout.write(self.style.SUCCESS(f"  {engine:<12} OK (HTTP {status_code})"))
            else:
                all_ok = False
                error = result.get("error", "unknown error")
                self.stdout.write(self.style.ERROR(f"  {engine:<12} FAILED — {error}"))

        self.stdout.write("=" * 50)
        if all_ok:
            self.stdout.write(self.style.SUCCESS("All engines pinged successfully."))
        else:
            self.stdout.write(self.style.WARNING("Some engines failed. Check output above."))
