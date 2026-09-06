"""Sitemap section management services."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def create_section(
    name: str,
    *,
    model_class=None,
    urls: list[dict] | None = None,
    url_provider: str = "",
    sitemap_type: str = "standard",
    tenant_id: str = "",
    max_urls_per_file: int | None = None,
    max_file_size_bytes: int | None = None,
    gzip: bool | None = None,
    **kwargs,
):
    """Create a ``SitemapSection`` record.

    If *model_class* is provided and uses ``SitemapMixin``, its class-level
    attributes seed the section configuration before *kwargs* are applied.
    This produces a ``section_type="model"`` section.

    If *urls* or *url_provider* is provided instead, this produces a
    ``section_type="static"`` section whose entries come from the declared
    list or callable rather than a Django queryset. *model_class* and
    *urls*/*url_provider* are mutually exclusive.

    *max_urls_per_file*, *max_file_size_bytes* and *gzip*, when given,
    override the matching ``ICV_SITEMAPS_*`` setting for this section only
    (issue #61 part 2). They are stored in the section's ``settings`` JSON
    alongside ``url_provider``/``urls`` and validated against the same
    bounds ``SitemapSection.clean()`` and generation enforce, raising
    ``ValueError`` on an out-of-bounds value: this is a programming error
    at the call site, not a value to persist and fail later at generation.

    Returns the created ``SitemapSection`` instance.
    """
    from icv_sitemaps.mixins import SitemapMixin
    from icv_sitemaps.models.sections import SECTION_LIMIT_BOUNDS, SitemapSection

    if model_class is not None and (urls is not None or url_provider):
        raise ValueError("create_section: model_class and urls/url_provider are mutually exclusive.")

    limit_overrides: dict = {}
    for key, value in (("max_urls_per_file", max_urls_per_file), ("max_file_size_bytes", max_file_size_bytes)):
        if value is None:
            continue
        minimum, maximum = SECTION_LIMIT_BOUNDS[key]
        if isinstance(value, bool) or not isinstance(value, int) or not (minimum <= value <= maximum):
            raise ValueError(
                f"create_section: {key} must be an integer between {minimum} and {maximum} (got {value!r})."
            )
        limit_overrides[key] = value
    if gzip is not None:
        if not isinstance(gzip, bool):
            raise ValueError(f"create_section: gzip must be a boolean (got {gzip!r}).")
        limit_overrides["gzip"] = gzip

    # Seed defaults from SitemapMixin attributes when available.
    defaults: dict = {
        "sitemap_type": sitemap_type,
        "tenant_id": tenant_id,
    }

    if urls is not None or url_provider:
        defaults["section_type"] = "static"
        section_settings: dict = dict(kwargs.pop("settings", {}) or {})
        if url_provider:
            section_settings["url_provider"] = url_provider
        if urls is not None:
            section_settings["urls"] = urls
        section_settings.update(limit_overrides)
        defaults["settings"] = section_settings
    else:
        if limit_overrides:
            section_settings = dict(kwargs.pop("settings", {}) or {})
            section_settings.update(limit_overrides)
            defaults["settings"] = section_settings

        if model_class is not None:
            defaults["model_path"] = f"{model_class._meta.app_label}.{model_class.__name__}"

            if isinstance(model_class, type) and issubclass(model_class, SitemapMixin):
                mixin_type = getattr(model_class, "sitemap_type", sitemap_type)
                if mixin_type:
                    defaults["sitemap_type"] = mixin_type
                changefreq = getattr(model_class, "sitemap_changefreq", None)
                if changefreq:
                    defaults["changefreq"] = changefreq
                priority = getattr(model_class, "sitemap_priority", None)
                if priority is not None:
                    defaults["priority"] = priority

    # Caller overrides take precedence over seeded defaults.
    defaults.update(kwargs)

    section = SitemapSection.objects.create(name=name, **defaults)
    logger.info("create_section: created section %r (tenant=%r)", name, tenant_id)
    return section


def delete_section(
    name_or_section,
    *,
    tenant_id: str = "",
) -> None:
    """Delete a section along with all its ``SitemapFile`` records and storage files.

    Sends ``sitemap_section_deleted`` signal after deletion.
    """
    from icv_sitemaps.models.sections import SitemapSection
    from icv_sitemaps.services.generation import _get_storage
    from icv_sitemaps.signals import sitemap_section_deleted

    if isinstance(name_or_section, str):
        try:
            section = SitemapSection.objects.get(name=name_or_section, tenant_id=tenant_id)
        except SitemapSection.DoesNotExist:
            logger.warning(
                "delete_section: section %r (tenant=%r) not found",
                name_or_section,
                tenant_id,
            )
            return
    else:
        section = name_or_section

    # Collect storage paths before deleting DB records.
    storage_paths = list(section.files.values_list("storage_path", flat=True))

    # Delete section (cascades to SitemapFile and SitemapGenerationLog).
    section.delete()

    # Remove generated files from storage (BR-029).
    storage = _get_storage()
    for path in storage_paths:
        try:
            if storage.exists(path):
                storage.delete(path)
        except Exception:
            logger.warning("delete_section: failed to delete storage file %r", path)

    sitemap_section_deleted.send(sender=SitemapSection, instance=section)
    logger.info(
        "delete_section: deleted section %r and %d file(s)",
        section.name,
        len(storage_paths),
    )
