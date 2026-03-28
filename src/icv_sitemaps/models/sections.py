"""Sitemap section, file, and generation-log models."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from icv_sitemaps.models.base import BaseModel
from icv_sitemaps.models.choices import (
    CHANGEFREQ_CHOICES,
    GENERATION_ACTION_CHOICES,
    GENERATION_STATUS_CHOICES,
    SITEMAP_TYPE_CHOICES,
)


class SitemapSection(BaseModel):
    """Logical section of the sitemap (e.g. "products", "articles").

    Each section maps to one or more XML sitemap files and tracks its
    staleness state for incremental regeneration.
    """

    name = models.CharField(
        max_length=200,
        help_text=_('Logical section name, e.g. "products" or "articles".'),
    )
    tenant_id = models.CharField(
        max_length=200,
        default="",
        blank=True,
        db_index=True,
        help_text=_("Tenant identifier for multi-tenant setups. Leave blank for single-tenant use."),
    )
    model_path = models.CharField(
        max_length=500,
        help_text=_('Django model in "app_label.ModelName" format, e.g. "catalog.Product".'),
    )
    sitemap_type = models.CharField(
        max_length=20,
        choices=SITEMAP_TYPE_CHOICES,
        default="standard",
        help_text=_("Type of sitemap to generate for this section."),
    )
    changefreq = models.CharField(
        max_length=20,
        choices=CHANGEFREQ_CHOICES,
        default="daily",
        help_text=_("Default change frequency for URLs in this section."),
    )
    priority = models.DecimalField(
        max_digits=2,
        decimal_places=1,
        default="0.5",
        help_text=_("Default URL priority for this section (0.0-1.0)."),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Whether this section is included in sitemap generation."),
    )
    is_stale = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Whether this section needs regeneration."),
    )
    last_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Timestamp of the last successful generation run."),
    )
    url_count = models.PositiveIntegerField(
        default=0,
        help_text=_("Total URLs across all files for this section."),
    )
    file_count = models.PositiveIntegerField(
        default=0,
        help_text=_("Number of XML files generated for this section."),
    )
    settings = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Section-specific configuration overrides (JSON)."),
    )

    class Meta:
        ordering = ["name"]
        db_table = "icv_sitemaps_section"
        verbose_name = _("sitemap section")
        verbose_name_plural = _("sitemap sections")
        constraints = [
            models.UniqueConstraint(
                fields=["name", "tenant_id"],
                name="icv_sm_sect_name_tnt_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["is_active", "is_stale"],
                name="icv_sm_sect_actv_stl_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.sitemap_type})"


class SitemapFile(BaseModel):
    """Individual XML sitemap file produced during generation.

    A single ``SitemapSection`` may produce multiple files when the URL
    count exceeds the 50,000-URL protocol limit.
    """

    section = models.ForeignKey(
        SitemapSection,
        on_delete=models.CASCADE,
        related_name="files",
        help_text=_("The parent sitemap section that produced this file."),
    )
    sequence = models.PositiveIntegerField(
        default=0,
        help_text=_("File sequence number within the section (0-based)."),
    )
    storage_path = models.CharField(
        max_length=500,
        help_text=_('Path to the XML file in storage, e.g. "sitemaps/products-0.xml".'),
    )
    url_count = models.PositiveIntegerField(
        default=0,
        help_text=_("Number of URLs in this file."),
    )
    file_size_bytes = models.PositiveIntegerField(
        default=0,
        help_text=_("Size of the generated XML file in bytes."),
    )
    checksum = models.CharField(
        max_length=64,
        blank=True,
        help_text=_("SHA-256 hash of the file contents for change detection."),
    )
    generated_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_("When this file was generated."),
    )

    class Meta:
        ordering = ["section", "sequence"]
        db_table = "icv_sitemaps_file"
        verbose_name = _("sitemap file")
        verbose_name_plural = _("sitemap files")
        constraints = [
            models.UniqueConstraint(
                fields=["section", "sequence"],
                name="icv_sm_file_sect_seq_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.section.name}-{self.sequence}"


class SitemapGenerationLog(BaseModel):
    """Audit trail for sitemap generation runs."""

    section = models.ForeignKey(
        SitemapSection,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="generation_logs",
        help_text=_("Section that was generated. Null for a full-site regeneration run."),
    )
    action = models.CharField(
        max_length=30,
        choices=GENERATION_ACTION_CHOICES,
        help_text=_("Action type for this generation run."),
    )
    status = models.CharField(
        max_length=20,
        choices=GENERATION_STATUS_CHOICES,
        help_text=_("Current status of this generation run."),
    )
    url_count = models.PositiveIntegerField(
        default=0,
        help_text=_("Total URLs generated in this run."),
    )
    file_count = models.PositiveIntegerField(
        default=0,
        help_text=_("Number of files written in this run."),
    )
    duration_ms = models.PositiveIntegerField(
        default=0,
        help_text=_("Generation time in milliseconds."),
    )
    detail = models.TextField(
        blank=True,
        help_text=_("Error message or summary for this run."),
    )

    class Meta:
        ordering = ["-created_at"]
        db_table = "icv_sitemaps_generation_log"
        verbose_name = _("sitemap generation log")
        verbose_name_plural = _("sitemap generation logs")

    def __str__(self) -> str:
        return f"{self.action} ({self.status}) \u2014 {self.created_at:%Y-%m-%d %H:%M}"
