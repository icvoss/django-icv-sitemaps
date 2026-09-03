"""Ads.txt and app-ads.txt service functions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from icv_sitemaps.models import AdsEntry

logger = logging.getLogger(__name__)

# IAB ads.txt v1.1 s3.2.1 placeholder record declaring "no authorised
# sellers", emitted when there are no active entries (issue #22). The empty-
# file method was deprecated for this purpose and "should be ignored by
# consuming systems after March 1, 2020".
ADS_TXT_PLACEHOLDER_RECORD = "placeholder.example.com, placeholder, DIRECT, placeholder"


def render_ads_txt(*, app_ads: bool = False, tenant_id: str = "") -> str:
    """Render the complete ads.txt or app-ads.txt content from database entries.

    Each active entry is rendered as a single line in the format::

        domain, publisher_id, RELATIONSHIP[, certification_id]

    When there are no active entries, the IAB placeholder record is emitted
    instead of an empty body (unless ``ICV_SITEMAPS_ADS_TXT_EMPTY_PLACEHOLDER``
    is set to ``False``).

    Args:
        app_ads: When ``True``, renders app-ads.txt entries (``is_app_ads=True``).
                 When ``False``, renders ads.txt entries (``is_app_ads=False``).
        tenant_id: Tenant identifier.  Empty string for single-tenant use.

    Returns:
        Fully rendered ads.txt or app-ads.txt string.
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_ADS_TXT_EMPTY_PLACEHOLDER
    from icv_sitemaps.models.discovery import AdsEntry

    entries = AdsEntry.objects.filter(
        is_active=True,
        is_app_ads=app_ads,
        tenant_id=tenant_id,
    ).order_by("domain", "publisher_id")

    lines: list[str] = []
    for entry in entries:
        # Defence at the render boundary, not just on write (issue #18): a
        # row can reach here with an embedded newline regardless of how it
        # was written (a database restored from before this fix, a direct
        # AdsEntry.objects.create()/bulk_create() call, an admin edit that
        # bypassed clean() some other way). A bad row is skipped rather
        # than stripped: stripping would turn a forged record into a
        # differently shaped, valid-looking one, whereas skipping omits it
        # and leaves a trace an operator can find.
        fields_to_check = (entry.domain, entry.publisher_id, entry.certification_id, entry.comment)
        if any("\n" in value or "\r" in value for value in fields_to_check):
            logger.warning(
                "render_ads_txt: skipping AdsEntry %s (tenant=%r), a field contains a newline character.",
                entry.pk,
                tenant_id,
            )
            continue

        if entry.comment:
            lines.append(f"# {entry.comment}")
        parts = [entry.domain, entry.publisher_id, entry.relationship]
        if entry.certification_id:
            parts.append(entry.certification_id)
        lines.append(", ".join(parts))

    if not lines and ICV_SITEMAPS_ADS_TXT_EMPTY_PLACEHOLDER:
        lines.append(ADS_TXT_PLACEHOLDER_RECORD)

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
        ValueError: If ``relationship`` is not ``"DIRECT"`` or ``"RESELLER"``,
            or if ``domain``, ``publisher_id``, ``certification_id``,
            ``comment``, or any string value passed via ``**kwargs``
            contains a newline character.
    """
    from icv_sitemaps.cache import safe_delete
    from icv_sitemaps.models.discovery import AdsEntry

    relationship_upper = relationship.upper()
    if relationship_upper not in ("DIRECT", "RESELLER"):
        raise ValueError(f"relationship must be 'DIRECT' or 'RESELLER', got: {relationship!r}")

    comment = kwargs.pop("comment", "")
    for field_name, value in [
        ("domain", domain),
        ("publisher_id", publisher_id),
        ("certification_id", certification_id),
        ("comment", comment),
    ]:
        if "\n" in value or "\r" in value:
            raise ValueError(f"{field_name} must not contain newline characters.")

    # kwargs is documented as "additional field values passed to
    # AdsEntry.objects.create", so any string it carries reaches the same
    # rendered output and must be checked too, not just the four named
    # parameters above.
    for field_name, value in kwargs.items():
        if isinstance(value, str) and ("\n" in value or "\r" in value):
            raise ValueError(f"{field_name} must not contain newline characters.")

    entry = AdsEntry.objects.create(
        domain=domain,
        publisher_id=publisher_id,
        relationship=relationship_upper,
        certification_id=certification_id,
        is_app_ads=is_app_ads,
        tenant_id=tenant_id,
        comment=comment,
        **kwargs,
    )

    # Invalidate the appropriate cache key
    cache_key = f"icv_sitemaps:app_ads_txt:{tenant_id}" if is_app_ads else f"icv_sitemaps:ads_txt:{tenant_id}"
    safe_delete(cache_key)

    return entry
