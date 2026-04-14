"""Redirect and 404 tracking models."""

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from icv_sitemaps.models.base import BaseModel
from icv_sitemaps.models.choices import (
    REDIRECT_MATCH_TYPE_CHOICES,
    REDIRECT_SOURCE_CHOICES,
    REDIRECT_STATUS_CODE_CHOICES,
)

# ------------------------------------------------------------------
# Managers
# ------------------------------------------------------------------


class RedirectRuleManager(models.Manager):
    """Default manager for RedirectRule — active, non-expired rules."""

    def active(self) -> models.QuerySet:
        """Return only active, non-expired redirect rules."""
        return self.filter(is_active=True).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        )


# ------------------------------------------------------------------
# RedirectRule
# ------------------------------------------------------------------


class RedirectRule(BaseModel):
    """HTTP redirect or 410 Gone rule.

    Evaluated by ``RedirectMiddleware`` on every request (when enabled).
    Rules are matched against the request path in priority order; the first
    match wins.
    """

    name = models.CharField(
        max_length=200,
        verbose_name=_("name"),
        help_text=_("Human-readable label for this redirect rule."),
    )
    match_type = models.CharField(
        max_length=10,
        choices=REDIRECT_MATCH_TYPE_CHOICES,
        default="exact",
        verbose_name=_("match type"),
        help_text=_("How to match the source pattern against the request path."),
    )
    source_pattern = models.CharField(
        max_length=2000,
        db_index=True,
        verbose_name=_("source pattern"),
        help_text=_("URL path to match (exact path, prefix, or regex)."),
    )
    destination = models.CharField(
        max_length=2000,
        blank=True,
        default="",
        verbose_name=_("destination"),
        help_text=_("Target URL. Leave blank for 410 Gone responses."),
    )
    status_code = models.PositiveSmallIntegerField(
        choices=REDIRECT_STATUS_CODE_CHOICES,
        default=301,
        verbose_name=_("status code"),
        help_text=_("HTTP status code for the redirect response."),
    )
    preserve_query_string = models.BooleanField(
        default=True,
        verbose_name=_("preserve query string"),
        help_text=_("Carry the original query string to the destination URL."),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("is active"),
        help_text=_("Inactive rules are not evaluated."),
    )
    priority = models.PositiveIntegerField(
        default=0,
        db_index=True,
        verbose_name=_("priority"),
        help_text=_("Lower numbers are evaluated first."),
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("expires at"),
        help_text=_("Rule is automatically skipped after this time. Null means never expires."),
    )
    hit_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("hit count"),
        help_text=_("Number of times this rule has been matched."),
    )
    last_hit_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("last hit at"),
        help_text=_("When this rule last matched a request."),
    )
    source = models.CharField(
        max_length=10,
        choices=REDIRECT_SOURCE_CHOICES,
        default="admin",
        verbose_name=_("source"),
        help_text=_("How this rule was created."),
    )
    tenant_id = models.CharField(
        max_length=200,
        default="",
        blank=True,
        db_index=True,
        verbose_name=_("tenant ID"),
        help_text=_("Tenant identifier. Leave blank for single-tenant use."),
    )
    notes = models.TextField(
        blank=True,
        default="",
        verbose_name=_("notes"),
        help_text=_("Optional notes about this redirect rule."),
    )

    objects = RedirectRuleManager()

    class Meta:
        db_table = "icv_sitemaps_redirect_rule"
        ordering = ["priority", "source_pattern"]
        verbose_name = _("redirect rule")
        verbose_name_plural = _("redirect rules")
        indexes = [
            models.Index(
                fields=["tenant_id", "is_active", "priority"],
                name="icv_sm_rdr_tnt_actv_pri_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_pattern", "tenant_id"],
                condition=models.Q(match_type="exact"),
                name="icv_sm_rdr_src_tnt_exact_uniq",
            ),
        ]

    def __str__(self) -> str:
        dest = self.destination or "410 Gone"
        return f"{self.source_pattern} \u2192 {dest} ({self.status_code})"


# ------------------------------------------------------------------
# RedirectLog
# ------------------------------------------------------------------


class RedirectLog(BaseModel):
    """Aggregated 404 tracking for redirect intelligence.

    Each record represents a unique path that returned 404. The hit_count
    is incremented atomically on each occurrence. Admins can review
    high-traffic 404s and create redirect rules from them.
    """

    path = models.CharField(
        max_length=2000,
        verbose_name=_("path"),
        help_text=_("Request path that returned 404."),
    )
    tenant_id = models.CharField(
        max_length=200,
        default="",
        blank=True,
        db_index=True,
        verbose_name=_("tenant ID"),
        help_text=_("Tenant identifier. Leave blank for single-tenant use."),
    )
    hit_count = models.PositiveIntegerField(
        default=1,
        verbose_name=_("hit count"),
        help_text=_("Number of times this path returned 404."),
    )
    first_seen_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("first seen at"),
        help_text=_("When this 404 was first recorded."),
    )
    last_seen_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("last seen at"),
        help_text=_("When this 404 was most recently recorded."),
    )
    referrers = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("referrers"),
        help_text=_("Top referrers for this 404, as {url: count} pairs."),
    )
    resolved = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("resolved"),
        help_text=_("Whether a redirect rule has been created for this path."),
    )

    class Meta:
        db_table = "icv_sitemaps_redirect_log"
        ordering = ["-hit_count"]
        verbose_name = _("404 log entry")
        verbose_name_plural = _("404 log entries")
        constraints = [
            models.UniqueConstraint(
                fields=["path", "tenant_id"],
                name="icv_sm_rdlog_path_tnt_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.path} ({self.hit_count} hits)"
