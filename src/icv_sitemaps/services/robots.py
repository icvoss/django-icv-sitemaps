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


def _longest_match_order(agent_rules: list[RobotsRule]) -> list[RobotsRule]:
    """Order one user-agent group's rules per RFC 9309 s2.2.2 longest match.

    The most specific match (measured in path-pattern octets) MUST be used
    by a conforming crawler, with ``allow`` winning an exact-length tie.
    ``order`` is the final tiebreaker between rules of equal specificity, so
    it keeps a meaningful job without governing precedence overall.

    Args:
        agent_rules: Rules belonging to one already-folded user-agent group.

    Returns:
        The rules sorted into the order a conforming crawler would apply
        them: longest path first, ``allow`` before ``disallow`` on a tie,
        then ``order`` ascending.
    """
    return sorted(
        agent_rules,
        key=lambda rule: (-len(rule.path), 0 if rule.directive == "allow" else 1, rule.order),
    )


def render_robots_txt(*, tenant_id: str = "") -> str:
    """Render the complete robots.txt content from database rules and settings.

    Groups rules by user-agent (folded case-insensitively per RFC 9309
    s2.2.1, so ``Googlebot`` and ``googlebot`` combine into one group under
    the first-seen spelling), rendering each group as a separate block.
    Within a group, rules are emitted in RFC 9309 s2.2.2 longest-match
    order: descending path length, with ``allow`` before ``disallow`` on an
    exact-length tie, and ``order`` as the final tiebreaker between rules of
    equal specificity. Appends the sitemap URL directive and any extra
    directives from settings.

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

    # Group rules by user-agent, case-insensitively (RFC 9309 s2.2.1), keeping
    # the first-seen spelling as the emitted label for the merged group.
    group_labels: dict[str, str] = {}
    groups: dict[str, list[RobotsRule]] = {}
    for rule in rules:
        key = rule.user_agent.casefold()
        group_labels.setdefault(key, rule.user_agent)
        groups.setdefault(key, []).append(rule)

    lines: list[str] = []

    for key, agent_rules in groups.items():
        lines.append(f"User-agent: {group_labels[key]}")
        for rule in _longest_match_order(agent_rules):
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


def invalidate_robots_cache(*, tenant_id: str = "") -> None:
    """Delete the cached robots.txt content for *tenant_id*.

    Named counterpart to :func:`icv_sitemaps.services.redirects.invalidate_redirect_cache`
    (#29): a documented escape hatch for a consumer who writes ``RobotsRule``
    rows with a raw ``RobotsRule.objects.bulk_create(...)`` call of their
    own, which emits no ``post_save`` signal and so leaves the rendered
    robots.txt cache stale until ``ICV_SITEMAPS_CACHE_TIMEOUT`` expires
    (#37). The key matches the one built in ``handlers.py`` and
    ``views.py`` exactly.
    """
    from icv_sitemaps.cache import safe_delete

    cache_key = f"icv_sitemaps:robots_txt:{tenant_id}"
    safe_delete(cache_key)


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
        order: Tiebreaker between rules of equal specificity within the
            user-agent group. Rules are emitted in RFC 9309 longest-match
            order, so this does not govern precedence.
        comment: Optional comment explaining the rule.
        **kwargs: Additional field values passed to ``RobotsRule.objects.create``.

    Returns:
        The newly created ``RobotsRule`` instance.

    Raises:
        ValueError: If ``directive`` or ``path`` is invalid.
    """
    from icv_sitemaps.models.discovery import RobotsRule

    directive_lower = directive.lower()
    valid_directives = {"allow", "disallow", "crawl-delay", "sitemap", "host"}
    if directive_lower not in valid_directives:
        raise ValueError(f"directive must be one of {sorted(valid_directives)}, got: {directive!r}")

    path_directives = {"allow", "disallow"}
    if directive_lower in path_directives and not path.startswith("/"):
        raise ValueError(f"path must start with '/' for {directive_lower}, got: {path!r}")

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

    invalidate_robots_cache(tenant_id=tenant_id)

    return rule
