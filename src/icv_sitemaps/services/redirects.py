"""Redirect rule evaluation and 404 tracking services."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from django.db.models import F

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from icv_sitemaps.models.redirects import RedirectLog, RedirectRule

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------


def get_cached_redirect_rules(*, tenant_id: str = "") -> list[dict]:
    """Return active redirect rules as a cache-friendly list of dicts.

    Rules are sorted by priority (ascending). The cache is invalidated by
    signal handlers in ``handlers.py`` whenever a rule is saved or deleted.
    """
    from django.core.cache import cache

    from icv_sitemaps.conf import ICV_SITEMAPS_REDIRECT_CACHE_TIMEOUT

    cache_key = f"icv_sitemaps:redirects:{tenant_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    from icv_sitemaps.models.redirects import RedirectRule

    rules = list(
        RedirectRule.objects.active()
        .filter(tenant_id=tenant_id)
        .order_by("priority", "pk")
        .values(
            "id",
            "match_type",
            "source_pattern",
            "destination",
            "status_code",
            "preserve_query_string",
        )
    )

    cache.set(cache_key, rules, timeout=ICV_SITEMAPS_REDIRECT_CACHE_TIMEOUT)
    return rules


def check_redirect(path: str, *, tenant_id: str = "") -> dict | None:
    """Check whether *path* matches an active redirect rule.

    Returns the first matching rule as a dict, or ``None``.
    Rules are evaluated in priority order: exact matches first, then prefix,
    then regex.
    """
    rules = get_cached_redirect_rules(tenant_id=tenant_id)

    for rule in rules:
        if _rule_matches(rule, path):
            return rule

    return None


def _rule_matches(rule: dict, path: str) -> bool:
    """Return True if *rule* matches *path*."""
    match_type = rule["match_type"]
    pattern = rule["source_pattern"]

    if match_type == "exact":
        return path == pattern
    if match_type == "prefix":
        return path.startswith(pattern)
    if match_type == "regex":
        try:
            return re.search(pattern, path) is not None
        except re.error:
            logger.warning("Invalid regex pattern in redirect rule: %r", pattern)
            return False
    return False


def invalidate_redirect_cache(*, tenant_id: str = "") -> None:
    """Delete the cached redirect rules for *tenant_id*."""
    from django.core.cache import cache

    cache_key = f"icv_sitemaps:redirects:{tenant_id}"
    cache.delete(cache_key)


# ---------------------------------------------------------------------------
# Rule management
# ---------------------------------------------------------------------------


def add_redirect(
    source_pattern: str,
    destination: str,
    status_code: int = 301,
    *,
    match_type: str = "exact",
    tenant_id: str = "",
    name: str = "",
    priority: int = 0,
    source: str = "admin",
    **kwargs,
) -> RedirectRule:
    """Create a new redirect rule.

    Validates inputs and invalidates the redirect cache after creation.

    Args:
        source_pattern: URL path pattern to match.
        destination: Target URL (empty for 410 Gone).
        status_code: HTTP status code (301, 302, 307, 308, 410).
        match_type: Match strategy — ``"exact"``, ``"prefix"``, or ``"regex"``.
        tenant_id: Tenant identifier.
        name: Human-readable label. Auto-generated if blank.
        priority: Lower numbers are evaluated first.
        source: How this rule was created (admin, auto, signal, import).
        **kwargs: Additional field values passed to ``RedirectRule.objects.create``.

    Returns:
        The newly created ``RedirectRule`` instance.

    Raises:
        ValueError: If inputs are invalid.
    """
    from icv_sitemaps.models.redirects import RedirectRule

    valid_status_codes = {301, 302, 307, 308, 410}
    if status_code not in valid_status_codes:
        raise ValueError(f"status_code must be one of {sorted(valid_status_codes)}, got: {status_code!r}")

    valid_match_types = {"exact", "prefix", "regex"}
    if match_type not in valid_match_types:
        raise ValueError(f"match_type must be one of {sorted(valid_match_types)}, got: {match_type!r}")

    if status_code != 410 and not destination:
        raise ValueError("destination is required for non-410 redirects.")

    if status_code == 410:
        destination = ""

    if not source_pattern:
        raise ValueError("source_pattern must not be empty.")

    if not name:
        name = f"{source_pattern} \u2192 {destination or '410'}"

    rule = RedirectRule.objects.create(
        name=name,
        match_type=match_type,
        source_pattern=source_pattern,
        destination=destination,
        status_code=status_code,
        tenant_id=tenant_id,
        priority=priority,
        source=source,
        **kwargs,
    )

    invalidate_redirect_cache(tenant_id=tenant_id)
    return rule


def bulk_import_redirects(
    rows: list[dict],
    *,
    tenant_id: str = "",
    source: str = "import",
) -> dict:
    """Import redirect rules from a list of dicts.

    Each dict should contain at minimum ``source_pattern`` and ``destination``.
    Optional keys: ``status_code``, ``match_type``, ``name``.

    Returns a summary dict with ``created``, ``updated``, and ``errors`` counts.
    """
    from icv_sitemaps.models.redirects import RedirectRule

    created = 0
    updated = 0
    errors: list[dict] = []

    for i, row in enumerate(rows):
        try:
            source_pattern = row["source_pattern"]
            destination = row.get("destination", "")
            status_code = int(row.get("status_code", 301))
            match_type = row.get("match_type", "exact")
            name = row.get("name", f"{source_pattern} \u2192 {destination or '410'}")

            _obj, was_created = RedirectRule.objects.update_or_create(
                source_pattern=source_pattern,
                tenant_id=tenant_id,
                match_type=match_type,
                defaults={
                    "destination": destination,
                    "status_code": status_code,
                    "name": name,
                    "source": source,
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        except Exception as exc:
            errors.append({"row": i, "error": str(exc), "data": row})

    invalidate_redirect_cache(tenant_id=tenant_id)

    return {"created": created, "updated": updated, "errors": errors}


# ---------------------------------------------------------------------------
# 404 tracking
# ---------------------------------------------------------------------------


def record_404(path: str, *, tenant_id: str = "", referrer: str = "") -> RedirectLog:
    """Record or increment a 404 occurrence for *path*.

    Uses ``update_or_create`` with ``F('hit_count') + 1`` for atomic
    increments. Maintains a top-10 referrer dict.
    """
    from django.utils import timezone as tz

    from icv_sitemaps.models.redirects import RedirectLog

    try:
        log_entry = RedirectLog.objects.get(path=path, tenant_id=tenant_id)
        # Atomic increment — avoids race conditions.
        RedirectLog.objects.filter(pk=log_entry.pk).update(
            hit_count=F("hit_count") + 1,
            last_seen_at=tz.now(),
        )
        log_entry.refresh_from_db()

        # Update referrers (best-effort, non-atomic).
        if referrer:
            referrers = log_entry.referrers or {}
            referrers[referrer] = referrers.get(referrer, 0) + 1
            # Keep only top 10 referrers by count.
            if len(referrers) > 10:
                referrers = dict(sorted(referrers.items(), key=lambda kv: kv[1], reverse=True)[:10])
            log_entry.referrers = referrers
            log_entry.save(update_fields=["referrers"])

    except RedirectLog.DoesNotExist:
        referrers = {referrer: 1} if referrer else {}
        log_entry = RedirectLog.objects.create(
            path=path,
            tenant_id=tenant_id,
            referrers=referrers,
        )

    return log_entry


def get_top_404s(
    *,
    tenant_id: str = "",
    limit: int = 50,
    min_hits: int = 2,
) -> QuerySet[RedirectLog]:
    """Return unresolved 404 log entries ordered by hit count.

    Args:
        tenant_id: Tenant identifier.
        limit: Maximum number of entries to return.
        min_hits: Minimum hit count threshold.

    Returns:
        Queryset of ``RedirectLog`` entries.
    """
    from icv_sitemaps.models.redirects import RedirectLog

    return (
        RedirectLog.objects.filter(
            tenant_id=tenant_id,
            resolved=False,
            hit_count__gte=min_hits,
        )
        .order_by("-hit_count")[:limit]
    )
