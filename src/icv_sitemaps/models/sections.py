"""Sitemap section, file, and generation-log models."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from icv_sitemaps.conf import ICV_TENANT_MODEL
from icv_sitemaps.models.base import BaseModel, sync_tenant_key
from icv_sitemaps.models.choices import (
    CHANGEFREQ_CHOICES,
    GENERATION_ACTION_CHOICES,
    GENERATION_STATUS_CHOICES,
    SECTION_TYPE_CHOICES,
    SITEMAP_TYPE_CHOICES,
)

# Bounds for the per-section generation-limit overrides read from
# ``SitemapSection.settings`` (issue #61 part 2). Shared between
# ``SitemapSection.clean()`` (admin-time validation) and
# ``services.generation._section_limits()`` (generation-time validation),
# so the two never drift: the protocol caps are BR-GEN-001 (max URLs per
# file, sitemaps.org's 50,000-entry limit) and BR-GEN-002 (max file size,
# sitemaps.org's 50 MiB limit).
SECTION_LIMIT_BOUNDS: dict[str, tuple[int, int]] = {
    "max_urls_per_file": (1, 50000),
    "max_file_size_bytes": (1, 52428800),
}


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
    tenant_ref = models.ForeignKey(
        ICV_TENANT_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_set",
        verbose_name=_("tenant"),
        help_text=_("Tenant this row belongs to. Optional; when set, tenant_id is derived from it."),
    )
    section_type = models.CharField(
        max_length=10,
        choices=SECTION_TYPE_CHOICES,
        default="model",
        help_text=_(
            'Where this section\'s URLs come from: "model" (a Django queryset) or '
            '"static" (a declared list or callable in `settings`).'
        ),
    )
    model_path = models.CharField(
        max_length=500,
        default="",
        blank=True,
        help_text=_(
            'Django model in "app_label.ModelName" format, e.g. "catalog.Product". '
            'Required when section_type is "model"; left blank for "static" sections.'
        ),
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
        help_text=_(
            "Section-specific configuration overrides (JSON). Static sections read "
            '"url_provider" and "urls"; every section type may override generation '
            'limits with "max_urls_per_file", "max_file_size_bytes" and "gzip", '
            "falling back to the matching ICV_SITEMAPS_* setting when absent."
        ),
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

    def clean(self) -> None:
        super().clean()
        if self.section_type == "model" and not self.model_path:
            raise ValidationError({"model_path": _('model_path is required when section_type is "model".')})
        if self.section_type == "static" and self.model_path:
            raise ValidationError({"model_path": _('model_path must be blank when section_type is "static".')})
        self._clean_limit_overrides()
        sync_tenant_key(self)

    def _clean_limit_overrides(self) -> None:
        """Validate the optional generation-limit overrides in ``settings``.

        Mirrors ``services.generation._section_limits()`` bounds so the
        admin rejects a bad override before generation would (issue #61
        part 2). Raises ``ValidationError`` keyed on ``"settings"``.
        """
        section_settings = self.settings or {}
        for key, (minimum, maximum) in SECTION_LIMIT_BOUNDS.items():
            if key not in section_settings:
                continue
            value = section_settings[key]
            if isinstance(value, bool) or not isinstance(value, int) or not (minimum <= value <= maximum):
                raise ValidationError(
                    {
                        "settings": _(
                            'settings["%(key)s"] must be an integer between %(minimum)s and %(maximum)s '
                            "(got %(value)r)."
                        )
                        % {"key": key, "minimum": minimum, "maximum": maximum, "value": value}
                    }
                )
        if "gzip" in section_settings and not isinstance(section_settings["gzip"], bool):
            gzip_value = section_settings["gzip"]
            raise ValidationError(
                {"settings": _('settings["gzip"] must be a boolean (got %(value)r).') % {"value": gzip_value}}
            )

    def save(self, *args, **kwargs):
        sync_tenant_key(self)
        super().save(*args, **kwargs)


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
        default=timezone.now,
        help_text=_(
            "When this file's content was last generated. Carried forward from the "
            "previous row when a regeneration finds the shard's checksum unchanged, "
            "so this reflects content changes rather than every generation run "
            "(issue #19)."
        ),
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
