"""Robots.txt service functions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings as django_settings

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from icv_sitemaps.models import RobotsRule

logger = logging.getLogger(__name__)


def get_robots_rules(*, tenant_id: str = "") -> QuerySet[RobotsRule]:
    """Return all active robots rules for a tenant, ordered for rendering.

    Args:
        tenant_id: Tenant identifier.  Empty string for single-tenant use.

    Returns:
        Ordered queryset of active ``RobotsRule`` records.
    """
    from icv_sitemaps.models.discovery import RobotsRule

    return RobotsRule.objects.filter(is_active=True, tenant_id=tenant_id).order_by("user_agent", "order")


def render_robots_txt(*, tenant_id: str = "") -> str:
    """Render the complete robots.txt content from database rules and settings.

    Groups rules by user-agent, rendering each group as a separate block.
    Appends the sitemap URL directive and any extra directives from settings.

    Args:
        tenant_id: Tenant identifier.  Empty string for single-tenant use.

    Returns:
        Fully rendered robots.txt string.
    """
    from icv_sitemaps.conf import (
        ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES,
        ICV_SITEMAPS_ROBOTS_SITEMAP_URL,
    )

    rules = get_robots_rules(tenant_id=tenant_id)

    # Group rules by user-agent, preserving ordering
    groups: dict[str, list[RobotsRule]] = {}
    for rule in rules:
        groups.setdefault(rule.user_agent, []).append(rule)

    lines: list[str] = []

    for user_agent, agent_rules in groups.items():
        lines.append(f"User-agent: {user_agent}")
        for rule in agent_rules:
            if rule.comment:
                lines.append(f"# {rule.comment}")
            lines.append(f"{rule.directive.capitalize()}: {rule.path}")
        lines.append("")

    # Sitemap URL
    sitemap_url = ICV_SITEMAPS_ROBOTS_SITEMAP_URL
    if not sitemap_url:
        base_url = getattr(django_settings, "ICV_SITEMAPS_BASE_URL", "").rstrip("/")
        if base_url:
            sitemap_url = f"{base_url}/sitemap.xml"

    if sitemap_url:
        lines.append(f"Sitemap: {sitemap_url}")

    # Extra directives from settings — strip newlines to prevent injection
    for directive in ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES:
        lines.append(str(directive).replace("\r", "").replace("\n", ""))

    return "\n".join(lines)


def add_robots_rule(
    user_agent: str,
    directive: str,
    path: str,
    *,
    tenant_id: str = "",
    order: int = 0,
    comment: str = "",
    **kwargs,
) -> RobotsRule:
    """Create a new ``RobotsRule`` record.

    Validates that ``directive`` is ``"allow"`` or ``"disallow"`` and that
    ``path`` starts with ``/``.  Invalidates the robots.txt cache for the
    given tenant after creation.

    Args:
        user_agent: User agent string, e.g. ``"*"``, ``"Googlebot"``.
        directive: ``"allow"`` or ``"disallow"``.
        path: URL path pattern, e.g. ``"/admin/"``.
        tenant_id: Tenant identifier.
        order: Sort order within the user-agent group.
        comment: Optional comment explaining the rule.
        **kwargs: Additional field values passed to ``RobotsRule.objects.create``.

    Returns:
        The newly created ``RobotsRule`` instance.

    Raises:
        ValueError: If ``directive`` or ``path`` is invalid.
    """
    from django.core.cache import cache

    from icv_sitemaps.models.discovery import RobotsRule

    directive_lower = directive.lower()
    if directive_lower not in ("allow", "disallow"):
        raise ValueError(f"directive must be 'allow' or 'disallow', got: {directive!r}")

    if not path.startswith("/"):
        raise ValueError(f"path must start with '/', got: {path!r}")

    for field_name, value in [("user_agent", user_agent), ("path", path), ("comment", comment)]:
        if "\n" in value or "\r" in value:
            raise ValueError(f"{field_name} must not contain newline characters.")

    rule = RobotsRule.objects.create(
        user_agent=user_agent,
        directive=directive_lower,
        path=path,
        tenant_id=tenant_id,
        order=order,
        comment=comment,
        **kwargs,
    )

    cache_key = f"icv_sitemaps:robots_txt:{tenant_id}"
    cache.delete(cache_key)

    return rule
