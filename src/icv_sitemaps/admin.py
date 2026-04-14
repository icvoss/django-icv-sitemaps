"""Admin registrations for icv-sitemaps models."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from icv_sitemaps.models.discovery import AdsEntry, DiscoveryFileConfig, RobotsRule
from icv_sitemaps.models.redirects import RedirectLog, RedirectRule
from icv_sitemaps.models.sections import (
    SitemapFile,
    SitemapGenerationLog,
    SitemapSection,
)

# ---------------------------------------------------------------------------
# Admin actions
# ---------------------------------------------------------------------------


@admin.action(description=_("Mark selected sections as stale"))
def mark_stale(modeladmin, request, queryset):
    """Set is_stale=True on all selected SitemapSection records."""
    updated = queryset.update(is_stale=True)
    modeladmin.message_user(
        request,
        _("%(count)d section(s) marked as stale.") % {"count": updated},
    )


@admin.action(description=_("Regenerate selected sections"))
def regenerate_selected(modeladmin, request, queryset):
    """Trigger regeneration for selected sections (async when Celery is available)."""
    from icv_sitemaps.conf import ICV_SITEMAPS_ASYNC_GENERATION

    count = 0
    for section in queryset:
        queryset.filter(pk=section.pk).update(is_stale=True)
        if ICV_SITEMAPS_ASYNC_GENERATION:
            try:
                from icv_sitemaps.tasks import regenerate_stale_sitemaps

                regenerate_stale_sitemaps.delay(tenant_id=section.tenant_id)
                count += 1
                continue
            except Exception:
                pass
        # Synchronous fallback
        try:
            from icv_sitemaps.services.generation import generate_section

            generate_section(section, force=True)
            count += 1
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Admin regenerate failed for section %r.", section.name)

    modeladmin.message_user(
        request,
        _("%(count)d section(s) queued for regeneration.") % {"count": count},
    )


@admin.action(description=_("Delete selected sections (including storage files)"))
def delete_with_files(modeladmin, request, queryset):
    """Delete selected sections using the delete_section service to clean up storage."""
    from icv_sitemaps.services.sections import delete_section

    count = 0
    for section in queryset:
        delete_section(section.name, tenant_id=section.tenant_id)
        count += 1
    modeladmin.message_user(
        request,
        _("%(count)d section(s) deleted with storage files.") % {"count": count},
    )


@admin.action(description=_("Regenerate all sections (full site)"))
def generate_all(modeladmin, request, queryset):
    """Force regeneration of all active sections for affected tenants."""
    from icv_sitemaps.conf import ICV_SITEMAPS_ASYNC_GENERATION

    tenant_ids = set(queryset.values_list("tenant_id", flat=True))
    for tenant_id in tenant_ids:
        if ICV_SITEMAPS_ASYNC_GENERATION:
            try:
                from icv_sitemaps.tasks import regenerate_all_sitemaps

                regenerate_all_sitemaps.delay(tenant_id=tenant_id)
                continue
            except Exception:
                pass
        from icv_sitemaps.services.generation import generate_all_sections

        generate_all_sections(tenant_id=tenant_id, force=True)

    modeladmin.message_user(
        request,
        _("Full regeneration triggered for %(count)d tenant(s).") % {"count": len(tenant_ids)},
    )


# ---------------------------------------------------------------------------
# SitemapSection
# ---------------------------------------------------------------------------


@admin.register(SitemapSection)
class SitemapSectionAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "sitemap_type",
        "is_active",
        "is_stale",
        "url_count",
        "file_count",
        "last_generated_at",
    ]
    list_filter = ["sitemap_type", "is_active", "is_stale"]
    search_fields = ["name", "model_path"]
    readonly_fields = ["url_count", "file_count", "last_generated_at", "created_at", "updated_at"]
    actions = [mark_stale, regenerate_selected, generate_all, delete_with_files]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "name",
                    "tenant_id",
                    "model_path",
                    "sitemap_type",
                    "changefreq",
                    "priority",
                    "is_active",
                    "is_stale",
                ]
            },
        ),
        (
            _("Statistics"),
            {
                "fields": ["url_count", "file_count", "last_generated_at"],
                "classes": ["collapse"],
            },
        ),
        (
            _("Advanced"),
            {"fields": ["settings"], "classes": ["collapse"]},
        ),
        (
            _("Timestamps"),
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]


# ---------------------------------------------------------------------------
# SitemapFile (read-only)
# ---------------------------------------------------------------------------


@admin.register(SitemapFile)
class SitemapFileAdmin(admin.ModelAdmin):
    list_display = ["section", "sequence", "url_count", "file_size_bytes", "generated_at"]
    list_filter = ["section"]
    readonly_fields = [
        "section",
        "sequence",
        "storage_path",
        "url_count",
        "file_size_bytes",
        "checksum",
        "generated_at",
        "created_at",
        "updated_at",
    ]
    list_select_related = ["section"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


# ---------------------------------------------------------------------------
# SitemapGenerationLog (read-only)
# ---------------------------------------------------------------------------


@admin.register(SitemapGenerationLog)
class SitemapGenerationLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "section", "action", "status", "url_count", "duration_ms"]
    list_filter = ["action", "status"]
    readonly_fields = [
        "section",
        "action",
        "status",
        "url_count",
        "file_count",
        "duration_ms",
        "detail",
        "created_at",
        "updated_at",
    ]
    date_hierarchy = "created_at"
    list_select_related = ["section"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


# ---------------------------------------------------------------------------
# RobotsRule
# ---------------------------------------------------------------------------


@admin.register(RobotsRule)
class RobotsRuleAdmin(admin.ModelAdmin):
    list_display = ["user_agent", "directive", "path", "order", "is_active", "tenant_id"]
    list_filter = ["user_agent", "directive", "is_active"]
    list_editable = ["directive", "path", "order", "is_active"]
    search_fields = ["user_agent", "path", "comment"]
    ordering = ["tenant_id", "user_agent", "order"]


# ---------------------------------------------------------------------------
# AdsEntry
# ---------------------------------------------------------------------------


@admin.register(AdsEntry)
class AdsEntryAdmin(admin.ModelAdmin):
    list_display = [
        "domain",
        "publisher_id",
        "relationship",
        "is_app_ads",
        "is_active",
        "tenant_id",
    ]
    list_filter = ["relationship", "is_app_ads", "is_active"]
    list_editable = ["is_active"]
    search_fields = ["domain", "publisher_id", "comment"]
    ordering = ["tenant_id", "domain", "publisher_id"]


# ---------------------------------------------------------------------------
# DiscoveryFileConfig
# ---------------------------------------------------------------------------


@admin.register(DiscoveryFileConfig)
class DiscoveryFileConfigAdmin(admin.ModelAdmin):
    list_display = ["file_type", "tenant_id", "is_active", "updated_at"]
    list_filter = ["file_type", "is_active"]
    readonly_fields = ["created_at", "updated_at"]
    search_fields = ["tenant_id"]
    ordering = ["tenant_id", "file_type"]


# ---------------------------------------------------------------------------
# RedirectRule
# ---------------------------------------------------------------------------


@admin.register(RedirectRule)
class RedirectRuleAdmin(admin.ModelAdmin):
    list_display = [
        "priority",
        "source_pattern",
        "destination",
        "status_code",
        "match_type",
        "hit_count",
        "is_active",
    ]
    list_display_links = ["source_pattern"]
    list_filter = ["status_code", "match_type", "is_active", "source"]
    list_editable = ["is_active", "priority"]
    search_fields = ["source_pattern", "destination", "name", "notes"]
    readonly_fields = ["hit_count", "last_hit_at", "created_at", "updated_at"]
    ordering = ["tenant_id", "priority"]


# ---------------------------------------------------------------------------
# RedirectLog (read-only)
# ---------------------------------------------------------------------------


@admin.action(description=_("Create 410 Gone rule from selected 404s"))
def create_gone_from_404(modeladmin, request, queryset):
    """Create a 410 Gone redirect rule for each selected 404 log entry."""
    from icv_sitemaps.services.redirects import add_redirect

    count = 0
    for log_entry in queryset.filter(resolved=False):
        try:
            add_redirect(
                log_entry.path,
                "",
                410,
                tenant_id=log_entry.tenant_id,
                source="auto",
                name=f"410 from 404 log: {log_entry.path}",
            )
            log_entry.resolved = True
            log_entry.save(update_fields=["resolved"])
            count += 1
        except Exception:
            pass
    modeladmin.message_user(
        request,
        _("%(count)d 410 Gone rule(s) created.") % {"count": count},
    )


@admin.register(RedirectLog)
class RedirectLogAdmin(admin.ModelAdmin):
    list_display = ["path", "hit_count", "first_seen_at", "last_seen_at", "resolved", "tenant_id"]
    list_filter = ["resolved"]
    ordering = ["-hit_count"]
    readonly_fields = [
        "path",
        "tenant_id",
        "hit_count",
        "first_seen_at",
        "last_seen_at",
        "referrers",
        "resolved",
        "created_at",
        "updated_at",
    ]
    actions = [create_gone_from_404]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
