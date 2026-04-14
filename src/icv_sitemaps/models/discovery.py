"""Discovery file models: robots.txt rules, ads.txt entries, and freeform config."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from icv_sitemaps.models.base import BaseModel
from icv_sitemaps.models.choices import (
    DIRECTIVE_CHOICES,
    FILE_TYPE_CHOICES,
    RELATIONSHIP_CHOICES,
)


class RobotsRule(BaseModel):
    """Database-driven robots.txt rule.

    Each rule defines a single directive (Allow or Disallow) for a specific
    user agent. Rules are rendered in ``order`` sequence within each user
    agent group when ``robots.txt`` is generated.
    """

    tenant_id = models.CharField(
        max_length=200,
        default="",
        blank=True,
        db_index=True,
        help_text=_("Tenant identifier. Leave blank for single-tenant use."),
    )
    user_agent = models.CharField(
        max_length=200,
        default="*",
        help_text=_('User agent string, e.g. "*", "Googlebot", or "GPTBot".'),
    )
    directive = models.CharField(
        max_length=20,
        choices=DIRECTIVE_CHOICES,
        help_text=_("Robots.txt directive, e.g. Allow, Disallow, or Crawl-delay."),
    )
    path = models.CharField(
        max_length=500,
        default="/",
        help_text=_('URL path pattern, e.g. "/admin/", "/api/", or "/*.pdf$".'),
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text=_("Sort order within the user agent group (lower = first)."),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Whether this rule is included when rendering robots.txt."),
    )
    comment = models.CharField(
        max_length=500,
        blank=True,
        help_text=_("Optional comment explaining the purpose of this rule."),
    )

    class Meta:
        ordering = ["user_agent", "order"]
        db_table = "icv_sitemaps_robots_rule"
        verbose_name = _("robots.txt rule")
        verbose_name_plural = _("robots.txt rules")
        indexes = [
            models.Index(
                fields=["tenant_id", "user_agent", "order"],
                name="icv_sm_robots_tnt_ua_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_agent}: {self.directive} {self.path}"


class AdsEntry(BaseModel):
    """Authorised digital advertising seller declaration for ads.txt / app-ads.txt.

    Each record corresponds to a single line in the rendered file, declaring
    an advertising system domain, publisher account, and relationship type.
    """

    tenant_id = models.CharField(
        max_length=200,
        default="",
        blank=True,
        db_index=True,
        help_text=_("Tenant identifier. Leave blank for single-tenant use."),
    )
    domain = models.CharField(
        max_length=200,
        help_text=_('Advertising system domain, e.g. "google.com".'),
    )
    publisher_id = models.CharField(
        max_length=200,
        help_text=_("Publisher account ID assigned by the advertising system."),
    )
    relationship = models.CharField(
        max_length=10,
        choices=RELATIONSHIP_CHOICES,
        help_text=_("Whether the seller is a direct publisher or a reseller."),
    )
    certification_id = models.CharField(
        max_length=200,
        blank=True,
        help_text=_("Optional TAG-ID certification authority ID."),
    )
    is_app_ads = models.BooleanField(
        default=False,
        help_text=_("If True, this entry belongs to app-ads.txt; otherwise ads.txt."),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Whether this entry is included when rendering the ads file."),
    )
    comment = models.CharField(
        max_length=500,
        blank=True,
        help_text=_("Optional comment for internal reference."),
    )

    class Meta:
        ordering = ["domain", "publisher_id"]
        db_table = "icv_sitemaps_ads_entry"
        verbose_name = _("ads.txt entry")
        verbose_name_plural = _("ads.txt entries")

    def __str__(self) -> str:
        return f"{self.domain}, {self.publisher_id}, {self.relationship}"


class DiscoveryFileConfig(BaseModel):
    """Content and configuration for freeform text-based discovery files.

    Covers files that do not need per-record modelling: ``llms.txt``,
    ``security.txt``, and ``humans.txt``. One record per file type per
    tenant is enforced via a unique constraint.
    """

    tenant_id = models.CharField(
        max_length=200,
        default="",
        blank=True,
        db_index=True,
        help_text=_("Tenant identifier. Leave blank for single-tenant use."),
    )
    file_type = models.CharField(
        max_length=20,
        choices=FILE_TYPE_CHOICES,
        help_text=_("The discovery file this record configures."),
    )
    content = models.TextField(
        help_text=_("Raw file content to serve at the file's canonical URL."),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Whether this file is served when requested."),
    )
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text=_("The user who last edited this configuration."),
    )

    class Meta:
        ordering = ["file_type"]
        db_table = "icv_sitemaps_discovery_config"
        verbose_name = _("discovery file configuration")
        verbose_name_plural = _("discovery file configurations")
        constraints = [
            models.UniqueConstraint(
                fields=["file_type", "tenant_id"],
                name="icv_sm_disc_type_tnt_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_file_type_display()} ({self.tenant_id or 'default'})"
