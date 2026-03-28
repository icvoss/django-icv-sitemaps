"""Search engine ping service."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Ping URL templates per search engine.
# Substituting ``{sitemap_url}`` yields the final ping URL.
_PING_URLS: dict[str, str] = {
    "google": "https://www.google.com/ping?sitemap={sitemap_url}",
    "bing": "https://www.bing.com/ping?sitemap={sitemap_url}",
    "yandex": "https://webmaster.yandex.com/ping?sitemap={sitemap_url}",
}


def ping_search_engines(*, sitemap_url: str = "", tenant_id: str = "") -> dict[str, int]:
    """Notify configured search engines of a sitemap update.

    Reads ``ICV_SITEMAPS_PING_ENGINES`` and ``ICV_SITEMAPS_PING_ENABLED``
    from settings.  When pinging is disabled or no sitemap URL is resolvable,
    returns an empty dict.

    Logs a ``SitemapGenerationLog`` record with ``action="ping"`` after
    completing all requests.

    Args:
        sitemap_url: Explicit sitemap URL to ping.  When empty, constructed
            from ``ICV_SITEMAPS_BASE_URL`` + ``/sitemap.xml``.
        tenant_id: Tenant identifier used when resolving the sitemap URL and
            writing the log record.

    Returns:
        Mapping of engine name → HTTP status code (or ``0`` on error).
    """
    from django.conf import settings as django_settings

    from icv_sitemaps.conf import ICV_SITEMAPS_PING_ENABLED, ICV_SITEMAPS_PING_ENGINES

    if not ICV_SITEMAPS_PING_ENABLED:
        logger.debug("Search engine pinging is disabled (ICV_SITEMAPS_PING_ENABLED=False).")
        return {}

    resolved_url = sitemap_url
    if not resolved_url:
        base_url = getattr(django_settings, "ICV_SITEMAPS_BASE_URL", "").rstrip("/")
        if base_url:
            resolved_url = f"{base_url}/sitemap.xml"

    if not resolved_url:
        logger.warning("Cannot ping search engines: no sitemap URL provided and ICV_SITEMAPS_BASE_URL is not set.")
        return {}

    if not resolved_url.startswith(("https://", "http://")):
        logger.warning("Refusing to ping with non-HTTP URL: %r", resolved_url)
        return {}

    results: dict[str, int] = {}

    try:
        import urllib.parse
        import urllib.request

        for engine in ICV_SITEMAPS_PING_ENGINES:
            ping_template = _PING_URLS.get(engine)
            if not ping_template:
                logger.warning("Unknown ping engine: %r — skipping.", engine)
                results[engine] = 0
                continue

            ping_url = ping_template.format(sitemap_url=urllib.parse.quote(resolved_url, safe=""))
            try:
                with urllib.request.urlopen(ping_url, timeout=10) as resp:  # noqa: S310
                    results[engine] = resp.status
                logger.info("Pinged %s: HTTP %d.", engine, results[engine])
            except Exception:
                logger.exception("Failed to ping %s.", engine)
                results[engine] = 0

    finally:
        _write_ping_log(results, tenant_id=tenant_id)
        _fire_pinged_signal(results)

    return results


def _write_ping_log(results: dict[str, int], *, tenant_id: str) -> None:
    """Persist a ``SitemapGenerationLog`` record for the ping run."""
    from icv_sitemaps.models.sections import SitemapGenerationLog

    status = "success" if all(v > 0 for v in results.values()) else "failed"
    detail = "; ".join(f"{engine}={code}" for engine, code in results.items())

    try:
        SitemapGenerationLog.objects.create(
            section=None,
            action="ping",
            status=status,
            detail=detail,
        )
    except Exception:
        logger.exception("Failed to write ping log.")


def _fire_pinged_signal(results: dict[str, int]) -> None:
    """Fire the ``sitemap_pinged`` signal."""
    from icv_sitemaps.signals import sitemap_pinged

    try:
        sitemap_pinged.send(sender=None, results=results)
    except Exception:
        logger.exception("Error firing sitemap_pinged signal.")
