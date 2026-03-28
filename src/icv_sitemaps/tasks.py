"""Celery tasks for icv-sitemaps.

Celery is optional.  When not installed, a no-op ``shared_task`` decorator is
used so imports succeed and tasks can be called synchronously without a Celery
worker.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from celery import shared_task
except ImportError:
    import functools

    # Celery not installed — define a no-op decorator so imports don't fail.
    # When bind=True, inject a minimal FakeTask as the first argument so the
    # function can use ``self.retry()``.
    def shared_task(func=None, **kwargs):  # type: ignore[misc]
        bind = kwargs.get("bind", False)

        class _FakeTask:
            """Minimal stand-in for a Celery task instance when Celery is absent."""

            @staticmethod
            def retry(exc=None, **kw: Any) -> None:
                if exc:
                    raise exc

        _fake = _FakeTask()

        def decorator(f):
            if bind:

                @functools.wraps(f)
                def wrapper(*args, **kw):
                    return f(_fake, *args, **kw)

                return wrapper
            return f

        if func is not None:
            return decorator(func)
        return decorator


# ---------------------------------------------------------------------------
# Sitemap generation tasks
# ---------------------------------------------------------------------------


@shared_task
def regenerate_stale_sitemaps(tenant_id: str = "") -> dict[str, int]:
    """Regenerate all stale sitemap sections for *tenant_id*.

    Only processes sections where ``is_stale=True``.  Intended as a periodic
    Celery beat task (every 15 minutes per the spec).

    Args:
        tenant_id: Tenant identifier.  Empty string for single-tenant use.

    Returns:
        Mapping of section name → URL count.
    """
    from icv_sitemaps.services.generation import generate_all_sections

    logger.info("regenerate_stale_sitemaps: starting (tenant=%r)", tenant_id)
    results = generate_all_sections(tenant_id=tenant_id, force=False)
    logger.info("regenerate_stale_sitemaps: complete — %d section(s) processed.", len(results))
    return results


@shared_task
def regenerate_all_sitemaps(tenant_id: str = "") -> dict[str, int]:
    """Force regeneration of all active sitemap sections for *tenant_id*.

    Regenerates every active section regardless of staleness.  Intended as a
    daily Celery beat task (03:00 per the spec).

    Args:
        tenant_id: Tenant identifier.

    Returns:
        Mapping of section name → URL count.
    """
    from icv_sitemaps.services.generation import generate_all_sections

    logger.info("regenerate_all_sitemaps: starting (tenant=%r)", tenant_id)
    results = generate_all_sections(tenant_id=tenant_id, force=True)
    logger.info("regenerate_all_sitemaps: complete — %d section(s) processed.", len(results))
    return results


@shared_task
def ping_engines_task(sitemap_url: str = "", tenant_id: str = "") -> dict[str, int]:
    """Ping configured search engines with the sitemap URL.

    Args:
        sitemap_url: Explicit sitemap URL.  When empty, constructed from
            ``ICV_SITEMAPS_BASE_URL`` + ``/sitemap.xml``.
        tenant_id: Tenant identifier.

    Returns:
        Mapping of engine name → HTTP status code.
    """
    from icv_sitemaps.services.ping import ping_search_engines

    logger.info("ping_engines_task: pinging (tenant=%r)", tenant_id)
    results = ping_search_engines(sitemap_url=sitemap_url, tenant_id=tenant_id)
    logger.info("ping_engines_task: results=%r", results)
    return results


# ---------------------------------------------------------------------------
# Cleanup tasks
# ---------------------------------------------------------------------------


@shared_task
def cleanup_generation_logs(days_older_than: int = 30) -> int:
    """Delete ``SitemapGenerationLog`` records older than *days_older_than* days.

    Intended as a daily Celery beat task (04:00 per the spec).

    Args:
        days_older_than: Retention period in days.  Defaults to 30.

    Returns:
        Number of records deleted.
    """
    from django.utils import timezone

    from icv_sitemaps.models.sections import SitemapGenerationLog

    cutoff = timezone.now() - timezone.timedelta(days=days_older_than)
    deleted, _ = SitemapGenerationLog.objects.filter(created_at__lt=cutoff).delete()
    logger.info(
        "cleanup_generation_logs: deleted %d record(s) older than %d days.",
        deleted,
        days_older_than,
    )
    return deleted


@shared_task
def cleanup_orphan_files(tenant_id: str = "") -> int:
    """Remove storage files not referenced by any ``SitemapFile`` record.

    Intended as a weekly Celery beat task.  Scans the storage path for the
    given tenant and deletes any XML / XML.GZ files that have no matching
    ``SitemapFile.storage_path`` record.

    Args:
        tenant_id: Tenant identifier.

    Returns:
        Number of orphan files deleted.
    """
    from django.core.files.storage import default_storage

    from icv_sitemaps.conf import ICV_SITEMAPS_STORAGE_PATH
    from icv_sitemaps.models.sections import SitemapFile

    storage_dir = ICV_SITEMAPS_STORAGE_PATH.rstrip("/")
    scan_prefix = f"{storage_dir}/{tenant_id}/" if tenant_id else f"{storage_dir}/"

    # Collect all storage paths currently tracked in the DB.
    # When no tenant_id is given, include ALL tenants' paths.
    if tenant_id:
        known_paths: set[str] = set(
            SitemapFile.objects.filter(section__tenant_id=tenant_id).values_list("storage_path", flat=True)
        )
    else:
        known_paths = set(SitemapFile.objects.values_list("storage_path", flat=True))

    deleted_count = 0

    try:
        _directories, files = default_storage.listdir(scan_prefix)
    except Exception:
        logger.exception("cleanup_orphan_files: cannot list storage directory %r.", scan_prefix)
        return 0

    for filename in files:
        if not (filename.endswith(".xml") or filename.endswith(".xml.gz")):
            continue
        path = f"{scan_prefix}{filename}"
        if path not in known_paths:
            try:
                default_storage.delete(path)
                deleted_count += 1
                logger.info("cleanup_orphan_files: deleted orphan file %r.", path)
            except Exception:
                logger.exception("cleanup_orphan_files: failed to delete %r.", path)

    # When no tenant specified, also recurse into tenant subdirectories.
    if not tenant_id:
        for subdir in _directories:
            sub_prefix = f"{scan_prefix}{subdir}/"
            try:
                _, sub_files = default_storage.listdir(sub_prefix)
            except Exception:
                continue
            for filename in sub_files:
                if not (filename.endswith(".xml") or filename.endswith(".xml.gz")):
                    continue
                path = f"{sub_prefix}{filename}"
                if path not in known_paths:
                    try:
                        default_storage.delete(path)
                        deleted_count += 1
                        logger.info("cleanup_orphan_files: deleted orphan file %r.", path)
                    except Exception:
                        logger.exception("cleanup_orphan_files: failed to delete %r.", path)

    logger.info(
        "cleanup_orphan_files: %d orphan file(s) deleted (tenant=%r).",
        deleted_count,
        tenant_id,
    )
    return deleted_count
