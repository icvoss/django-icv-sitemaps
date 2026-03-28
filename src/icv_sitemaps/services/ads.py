"""Ads.txt and app-ads.txt service functions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from icv_sitemaps.models import AdsEntry

logger = logging.getLogger(__name__)


def render_ads_txt(*, app_ads: bool = False, tenant_id: str = "") -> str:
    """Render the complete ads.txt or app-ads.txt content from database entries.

    Each active entry is rendered as a single line in the format::

        domain, publisher_id, RELATIONSHIP[, certification_id]

    Args:
        app_ads: When ``True``, renders app-ads.txt entries (``is_app_ads=True``).
                 When ``False``, renders ads.txt entries (``is_app_ads=False``).
        tenant_id: Tenant identifier.  Empty string for single-tenant use.

    Returns:
        Fully rendered ads.txt or app-ads.txt string.
    """
    from icv_sitemaps.models.discovery import AdsEntry

    entries = AdsEntry.objects.filter(
        is_active=True,
        is_app_ads=app_ads,
        tenant_id=tenant_id,
    ).order_by("domain", "publisher_id")

    lines: list[str] = []
    for entry in entries:
        if entry.comment:
            lines.append(f"# {entry.comment}")
        parts = [entry.domain, entry.publisher_id, entry.relationship]
        if entry.certification_id:
            parts.append(entry.certification_id)
        lines.append(", ".join(parts))

    return "\n".join(lines)


def add_ads_entry(
    domain: str,
    publisher_id: str,
    relationship: str,
    *,
    certification_id: str = "",
    is_app_ads: bool = False,
    tenant_id: str = "",
    **kwargs,
) -> AdsEntry:
    """Create a new ``AdsEntry`` record.

    Validates that ``relationship`` is ``"DIRECT"`` or ``"RESELLER"``.
    Invalidates the ads.txt (or app-ads.txt) cache for the given tenant.

    Args:
        domain: Advertising system domain, e.g. ``"google.com"``.
        publisher_id: Publisher account ID.
        relationship: ``"DIRECT"`` or ``"RESELLER"``.
        certification_id: Optional TAG-ID certification authority ID.
        is_app_ads: When ``True``, entry belongs to app-ads.txt.
        tenant_id: Tenant identifier.
        **kwargs: Additional field values passed to ``AdsEntry.objects.create``.

    Returns:
        The newly created ``AdsEntry`` instance.

    Raises:
        ValueError: If ``relationship`` is not ``"DIRECT"`` or ``"RESELLER"``.
    """
    from django.core.cache import cache

    from icv_sitemaps.models.discovery import AdsEntry

    relationship_upper = relationship.upper()
    if relationship_upper not in ("DIRECT", "RESELLER"):
        raise ValueError(f"relationship must be 'DIRECT' or 'RESELLER', got: {relationship!r}")

    entry = AdsEntry.objects.create(
        domain=domain,
        publisher_id=publisher_id,
        relationship=relationship_upper,
        certification_id=certification_id,
        is_app_ads=is_app_ads,
        tenant_id=tenant_id,
        **kwargs,
    )

    # Invalidate the appropriate cache key
    cache_key = f"icv_sitemaps:app_ads_txt:{tenant_id}" if is_app_ads else f"icv_sitemaps:ads_txt:{tenant_id}"
    cache.delete(cache_key)

    return entry
