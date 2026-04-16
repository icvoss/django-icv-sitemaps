"""Sitemap XML generation services."""

from __future__ import annotations

import gzip
import hashlib
import io
import logging
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape as xml_escape

from django.apps import apps
from django.core.files.base import ContentFile, File
from django.utils import timezone as django_timezone
from django.utils.module_loading import import_string

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XML namespace constants (issue #7)
# ---------------------------------------------------------------------------

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
IMAGE_NS = "http://www.google.com/schemas/sitemap-image/1.1"
VIDEO_NS = "http://www.google.com/schemas/sitemap-video/1.1"
NEWS_NS = "http://www.google.com/schemas/sitemap-news/0.9"

# Regex for sanitising tenant IDs in storage paths (issue #5)
_SAFE_TENANT_RE = re.compile(r"^[\w\-]+$")

# How often (in chunks) to force a full gc.collect() during iteration.
# With batch_size=5000 and _GC_INTERVAL=10 this fires every ~50K rows.
_GC_INTERVAL = 10


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_model(model_path: str):
    """Resolve a model from ``app_label.ModelName`` format via Django's app registry.

    Only accepts the ``app_label.ModelName`` format (e.g. ``"catalog.Product"``).
    Full dotted paths (e.g. ``"catalog.models.Product"``) are not supported — use
    the ``app_label.ModelName`` format instead.
    """
    parts = model_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"model_path {model_path!r} is not in 'app_label.ModelName' format.")
    return apps.get_model(parts[0], parts[1])


def _get_storage():
    """Return the configured storage backend instance."""
    from django.core.exceptions import ImproperlyConfigured
    from django.core.files.storage import Storage, default_storage

    from icv_sitemaps.conf import ICV_SITEMAPS_STORAGE_BACKEND

    backend_path = ICV_SITEMAPS_STORAGE_BACKEND
    if backend_path == "django.core.files.storage.default_storage":
        return default_storage
    StorageClass = import_string(backend_path)
    if not (isinstance(StorageClass, type) and issubclass(StorageClass, Storage)):
        raise ImproperlyConfigured(f"ICV_SITEMAPS_STORAGE_BACKEND {backend_path!r} is not a Django Storage subclass.")
    return StorageClass()


def _storage_path(filename: str, tenant_id: str = "") -> str:
    """Prefix a storage filename with the tenant ID if provided (BR-027).

    Rejects tenant IDs containing path-traversal sequences or unsafe characters.
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_STORAGE_PATH

    base = ICV_SITEMAPS_STORAGE_PATH.rstrip("/")
    if tenant_id:
        if not _SAFE_TENANT_RE.match(tenant_id):
            raise ValueError(
                f"Unsafe tenant_id for storage path: {tenant_id!r}. "
                "Only alphanumeric characters, hyphens, and underscores are allowed."
            )
        return f"{base}/{tenant_id}/{filename}"
    return f"{base}/{filename}"


def _absolute_url(url: str) -> str:
    """Ensure a URL is absolute by prepending ICV_SITEMAPS_BASE_URL (BR-003).

    Raises ``ImproperlyConfigured`` when BASE_URL is empty and the URL is
    relative, rather than silently producing a broken ``/path`` loc.
    """
    from django.core.exceptions import ImproperlyConfigured

    from icv_sitemaps.conf import ICV_SITEMAPS_BASE_URL

    if url.startswith(("http://", "https://")):
        return url
    if not ICV_SITEMAPS_BASE_URL:
        raise ImproperlyConfigured(
            "ICV_SITEMAPS_BASE_URL must be set to generate absolute sitemap URLs. "
            'Example: ICV_SITEMAPS_BASE_URL = "https://example.com"'
        )
    base = ICV_SITEMAPS_BASE_URL.rstrip("/")
    return f"{base}{url}"


def _format_lastmod(value) -> str | None:
    """Return a W3C-formatted lastmod string, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def _checksum(data: bytes) -> str:
    """Return a SHA-256 hex digest of *data*."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Per-entry byte renderers
#
# Hand-written XML serialisation, avoiding ElementTree object overhead per
# row. Each renderer returns the bytes for a single ``<url>...</url>``
# element (or ``<sitemap>...</sitemap>`` for the index). All user-controlled
# strings are escaped via xml.sax.saxutils.escape.
# ---------------------------------------------------------------------------


def _esc(value) -> str:
    """XML-escape *value* coerced to str."""
    return xml_escape(str(value))


def _render_standard_url(entry: dict) -> bytes:
    parts: list[str] = ["  <url>\n", f"    <loc>{_esc(entry['loc'])}</loc>\n"]
    if entry.get("lastmod"):
        parts.append(f"    <lastmod>{_esc(entry['lastmod'])}</lastmod>\n")
    if entry.get("changefreq"):
        parts.append(f"    <changefreq>{_esc(entry['changefreq'])}</changefreq>\n")
    if entry.get("priority") is not None:
        parts.append(f"    <priority>{entry['priority']}</priority>\n")
    parts.append("  </url>\n")
    return "".join(parts).encode("utf-8")


def _render_image_url(entry: dict) -> bytes:
    parts: list[str] = ["  <url>\n", f"    <loc>{_esc(entry['loc'])}</loc>\n"]
    if entry.get("lastmod"):
        parts.append(f"    <lastmod>{_esc(entry['lastmod'])}</lastmod>\n")
    if entry.get("changefreq"):
        parts.append(f"    <changefreq>{_esc(entry['changefreq'])}</changefreq>\n")
    if entry.get("priority") is not None:
        parts.append(f"    <priority>{entry['priority']}</priority>\n")
    for image in entry.get("images") or ():
        parts.append("    <image:image>\n")
        parts.append(f"      <image:loc>{_esc(image['loc'])}</image:loc>\n")
        if image.get("caption"):
            parts.append(f"      <image:caption>{_esc(image['caption'])}</image:caption>\n")
        if image.get("title"):
            parts.append(f"      <image:title>{_esc(image['title'])}</image:title>\n")
        if image.get("geo_location"):
            parts.append(f"      <image:geo_location>{_esc(image['geo_location'])}</image:geo_location>\n")
        if image.get("license"):
            parts.append(f"      <image:license>{_esc(image['license'])}</image:license>\n")
        parts.append("    </image:image>\n")
    parts.append("  </url>\n")
    return "".join(parts).encode("utf-8")


def _render_video_url(entry: dict) -> bytes:
    parts: list[str] = ["  <url>\n", f"    <loc>{_esc(entry['loc'])}</loc>\n"]
    if entry.get("lastmod"):
        parts.append(f"    <lastmod>{_esc(entry['lastmod'])}</lastmod>\n")
    if entry.get("changefreq"):
        parts.append(f"    <changefreq>{_esc(entry['changefreq'])}</changefreq>\n")
    if entry.get("priority") is not None:
        parts.append(f"    <priority>{entry['priority']}</priority>\n")
    video = entry.get("video")
    if video:
        parts.append("    <video:video>\n")
        if video.get("thumbnail_loc"):
            parts.append(f"      <video:thumbnail_loc>{_esc(video['thumbnail_loc'])}</video:thumbnail_loc>\n")
        if video.get("title"):
            parts.append(f"      <video:title>{_esc(video['title'])}</video:title>\n")
        if video.get("description"):
            parts.append(f"      <video:description>{_esc(video['description'])}</video:description>\n")
        if video.get("content_loc"):
            parts.append(f"      <video:content_loc>{_esc(video['content_loc'])}</video:content_loc>\n")
        if video.get("player_loc"):
            parts.append(f"      <video:player_loc>{_esc(video['player_loc'])}</video:player_loc>\n")
        if video.get("duration") is not None:
            parts.append(f"      <video:duration>{video['duration']}</video:duration>\n")
        if video.get("rating") is not None:
            parts.append(f"      <video:rating>{video['rating']}</video:rating>\n")
        if video.get("publication_date"):
            parts.append(f"      <video:publication_date>{_esc(video['publication_date'])}</video:publication_date>\n")
        parts.append("    </video:video>\n")
    parts.append("  </url>\n")
    return "".join(parts).encode("utf-8")


def _render_news_url(entry: dict) -> bytes:
    parts: list[str] = ["  <url>\n", f"    <loc>{_esc(entry['loc'])}</loc>\n"]
    news = entry.get("news")
    if news:
        parts.append("    <news:news>\n")
        parts.append("      <news:publication>\n")
        parts.append(f"        <news:name>{_esc(news.get('publication_name', ''))}</news:name>\n")
        parts.append(f"        <news:language>{_esc(news.get('language', 'en'))}</news:language>\n")
        parts.append("      </news:publication>\n")
        pub_date = news.get("publication_date")
        if pub_date is not None:
            pub_date_str = _format_lastmod(pub_date) or str(pub_date)
            parts.append(f"      <news:publication_date>{_esc(pub_date_str)}</news:publication_date>\n")
        parts.append(f"      <news:title>{_esc(news.get('title', ''))}</news:title>\n")
        parts.append("    </news:news>\n")
    parts.append("  </url>\n")
    return "".join(parts).encode("utf-8")


_HEADERS: dict[str, bytes] = {
    "standard": (
        b'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    ),
    "image": (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
        b' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
    ),
    "video": (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
        b' xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">\n'
    ),
    "news": (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
        b' xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">\n'
    ),
}

_FOOTER = b"</urlset>\n"

_RENDERERS = {
    "standard": _render_standard_url,
    "image": _render_image_url,
    "video": _render_video_url,
    "news": _render_news_url,
}


def _renderer_for(sitemap_type: str):
    return _RENDERERS.get(sitemap_type, _render_standard_url)


def _header_for(sitemap_type: str) -> bytes:
    return _HEADERS.get(sitemap_type, _HEADERS["standard"])


# ---------------------------------------------------------------------------
# Streaming writer
# ---------------------------------------------------------------------------


class _StreamingSitemapWriter:
    """Stream a single sitemap shard to a local temp file.

    Writing always goes to a local temp file (optionally gzipped); on
    ``close()`` the file is uploaded once via the storage backend's
    ``save()`` API. This bounds memory regardless of entry count and works
    uniformly across local FS and remote (S3, Spaces, GCS) backends.
    """

    def __init__(self, sitemap_type: str, *, gzip_enabled: bool):
        self.sitemap_type = sitemap_type
        self.gzip_enabled = gzip_enabled
        self.url_count = 0
        self.bytes_written = 0
        self._renderer = _renderer_for(sitemap_type)
        self._hasher = hashlib.sha256()

        # NamedTemporaryFile with delete=False so we can close-then-reopen
        # and pass the path to storage.save(). We clean up explicitly in
        # finalize() / abort(), so a context manager wouldn't help here.
        self._tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
            prefix="icv-sitemap-",
            suffix=".xml.gz" if gzip_enabled else ".xml",
            delete=False,
        )
        if gzip_enabled:
            self._gz = gzip.GzipFile(fileobj=self._tmp, mode="wb")
            self._fh = self._gz
        else:
            self._gz = None
            self._fh = self._tmp

        self._write(_header_for(sitemap_type))

    def _write(self, data: bytes) -> None:
        self._fh.write(data)
        self._hasher.update(data)
        self.bytes_written += len(data)

    def write_entry(self, entry: dict) -> None:
        self._write(self._renderer(entry))
        self.url_count += 1

    def estimated_size_after(self, entry: dict) -> int:
        """Estimate uncompressed XML size after appending *entry*.

        Used for the MAX_FILE_SIZE_BYTES check. We compare against the
        protocol limit (which is uncompressed); ``bytes_written`` here is
        also uncompressed because it tracks input bytes to the writer
        (gzip happens on the underlying handle).
        """
        return self.bytes_written + len(entry.get("loc", "")) + 200

    def finalize(self) -> tuple[str, int, str]:
        """Write footer, close the file, and return (temp_path, size, checksum).

        The caller is responsible for uploading *temp_path* via storage.save()
        and then unlinking it via :func:`_cleanup_temp`.
        """
        self._write(_FOOTER)
        if self._gz is not None:
            self._gz.close()
        self._tmp.close()
        # On-disk size may differ from bytes_written when gzip is enabled.
        on_disk_size = os.path.getsize(self._tmp.name)
        return self._tmp.name, on_disk_size, self._hasher.hexdigest()

    def abort(self) -> None:
        """Close and unlink the temp file without finalising (error path)."""
        try:
            if self._gz is not None:
                self._gz.close()
            self._tmp.close()
        finally:
            _cleanup_temp(self._tmp.name)


def _cleanup_temp(path: str) -> None:
    """Remove a temp file, swallowing errors."""
    try:
        os.unlink(path)
    except OSError:
        pass


def _upload_temp_to_storage(storage, temp_path: str, dest_path: str) -> tuple[str, int]:
    """Upload a local temp file to *dest_path* atomically (BR-006).

    Writes to ``dest_path + ".tmp"`` first, then swaps to the final path.
    Returns ``(final_path, size_bytes)``.
    """
    tmp_dest = dest_path + ".tmp"

    if storage.exists(tmp_dest):
        storage.delete(tmp_dest)
    with open(temp_path, "rb") as fh:
        storage.save(tmp_dest, File(fh))

    if storage.exists(dest_path):
        storage.delete(dest_path)
    with open(temp_path, "rb") as fh:
        storage.save(dest_path, File(fh))

    if storage.exists(tmp_dest):
        storage.delete(tmp_dest)

    size = os.path.getsize(temp_path)
    return dest_path, size


# ---------------------------------------------------------------------------
# Buffered fallback (kept behind ICV_SITEMAPS_STREAMING_WRITER=False)
# ---------------------------------------------------------------------------


def _build_buffered_xml(sitemap_type: str, entries: list[dict]) -> bytes:
    """Build a complete sitemap document in memory.

    Used when ``ICV_SITEMAPS_STREAMING_WRITER`` is disabled and for the
    sitemap *index* (always small). Reuses the per-entry byte renderers so
    output is byte-identical to the streaming path.
    """
    renderer = _renderer_for(sitemap_type)
    chunks: list[bytes] = [_header_for(sitemap_type)]
    for entry in entries:
        chunks.append(renderer(entry))
    chunks.append(_FOOTER)
    return b"".join(chunks)


def _write_buffered_to_storage(
    storage,
    path: str,
    data: bytes,
    *,
    gzip_enabled: bool = False,
) -> tuple[str, int]:
    """Buffered-write fallback for non-streaming callers (e.g. the index).

    Atomic write (BR-006): write to a temporary path, then swap.
    """
    if gzip_enabled:
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(data)
        data = buf.getvalue()
        if not path.endswith(".gz"):
            path = path + ".gz"

    tmp_path = path + ".tmp"
    if storage.exists(tmp_path):
        storage.delete(tmp_path)
    storage.save(tmp_path, ContentFile(data))

    if storage.exists(path):
        storage.delete(path)
    storage.save(path, ContentFile(data))

    if storage.exists(tmp_path):
        storage.delete(tmp_path)

    return path, len(data)


# ---------------------------------------------------------------------------
# Entry extraction helpers
# ---------------------------------------------------------------------------


def _extract_entry(instance, sitemap_type: str, base_url: str) -> dict | None:
    """Extract a sitemap entry dict from a model instance."""
    try:
        raw_url = instance.get_sitemap_url()
    except Exception:
        return None

    loc = _absolute_url(raw_url) if base_url else raw_url

    lastmod_val = getattr(instance, "get_sitemap_lastmod", lambda: None)()
    entry: dict = {
        "loc": loc,
        "lastmod": _format_lastmod(lastmod_val),
        "changefreq": getattr(instance, "get_sitemap_changefreq", lambda: "daily")(),
        "priority": getattr(instance, "get_sitemap_priority", lambda: 0.5)(),
    }

    if sitemap_type == "image":
        images = getattr(instance, "get_sitemap_images", list)()
        entry["images"] = images

    elif sitemap_type == "video":
        video = getattr(instance, "get_sitemap_video", lambda: None)()
        entry["video"] = video

    elif sitemap_type == "news":
        news = getattr(instance, "get_sitemap_news", lambda: None)()
        entry["news"] = news

    return entry


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


def generate_section(
    name_or_section,
    *,
    tenant_id: str = "",
    force: bool = False,
) -> int:
    """Generate sitemap XML files for a single section.

    Returns the number of URLs written. Skips generation when the section is
    not stale unless *force* is ``True`` (BR-009).

    Creates/updates ``SitemapFile`` records, writes XML to storage, creates a
    ``SitemapGenerationLog``, marks the section as ``is_stale=False``, then
    calls ``generate_index()``. Sends ``sitemap_section_generated`` on success.
    """
    from icv_sitemaps.conf import (
        ICV_SITEMAPS_BATCH_SIZE,
        ICV_SITEMAPS_GZIP,
        ICV_SITEMAPS_MAX_FILE_SIZE_BYTES,
        ICV_SITEMAPS_MAX_URLS_PER_FILE,
        ICV_SITEMAPS_NEWS_MAX_AGE_DAYS,
        ICV_SITEMAPS_STREAMING_WRITER,
    )
    from icv_sitemaps.models.sections import SitemapFile, SitemapGenerationLog, SitemapSection
    from icv_sitemaps.signals import sitemap_section_generated

    # Resolve section.
    if isinstance(name_or_section, str):
        try:
            section = SitemapSection.objects.get(name=name_or_section, tenant_id=tenant_id)
        except SitemapSection.DoesNotExist:
            logger.error(
                "generate_section: section %r (tenant=%r) not found",
                name_or_section,
                tenant_id,
            )
            return 0
    else:
        section = name_or_section

    # Skip if not stale (BR-009).
    if not force and not section.is_stale:
        logger.debug("generate_section: %r is up to date, skipping", section.name)
        return 0

    start_ms = int(time.monotonic() * 1000)

    log = SitemapGenerationLog.objects.create(
        section=section,
        action="generate_section",
        status="running",
    )

    try:
        model_class = _resolve_model(section.model_path)
    except (ValueError, LookupError, ImportError) as exc:
        logger.exception("generate_section: cannot resolve model %r", section.model_path)
        log.status = "failed"
        log.detail = str(exc)
        log.save(update_fields=["status", "detail"])
        return 0

    try:
        queryset = model_class.get_sitemap_queryset()
    except AttributeError:
        queryset = model_class.objects.all()

    # News max-age cutoff (BR-015).
    if section.sitemap_type == "news":
        cutoff = django_timezone.now() - django_timezone.timedelta(days=ICV_SITEMAPS_NEWS_MAX_AGE_DAYS)

    storage = _get_storage()
    base_url_setting = _get_base_url()
    sitemap_type = section.sitemap_type

    # Track previously generated files for cleanup (BR-029).
    old_paths = set(section.files.values_list("storage_path", flat=True))

    new_files: list[dict] = []  # list of {sequence, path, url_count, size, checksum}
    file_sequence = 0
    total_urls = 0

    if ICV_SITEMAPS_STREAMING_WRITER:
        total_urls, new_files = _generate_streaming(
            section=section,
            tenant_id=tenant_id,
            queryset=queryset,
            sitemap_type=sitemap_type,
            base_url_setting=base_url_setting,
            cutoff=cutoff if section.sitemap_type == "news" else None,
            model_class=model_class,
            storage=storage,
            gzip_enabled=ICV_SITEMAPS_GZIP,
            batch_size=ICV_SITEMAPS_BATCH_SIZE,
            max_urls=ICV_SITEMAPS_MAX_URLS_PER_FILE,
            max_bytes=ICV_SITEMAPS_MAX_FILE_SIZE_BYTES,
        )
    else:
        total_urls, new_files = _generate_buffered(
            section=section,
            tenant_id=tenant_id,
            queryset=queryset,
            sitemap_type=sitemap_type,
            base_url_setting=base_url_setting,
            cutoff=cutoff if section.sitemap_type == "news" else None,
            model_class=model_class,
            storage=storage,
            gzip_enabled=ICV_SITEMAPS_GZIP,
            batch_size=ICV_SITEMAPS_BATCH_SIZE,
            max_urls=ICV_SITEMAPS_MAX_URLS_PER_FILE,
            max_bytes=ICV_SITEMAPS_MAX_FILE_SIZE_BYTES,
        )

    # Write a valid empty urlset for sections with no URLs (TS-012).
    if not new_files:
        empty_data = _build_buffered_xml(sitemap_type, [])
        filename = f"{section.name}-{file_sequence}.xml"
        path = _storage_path(filename, tenant_id=tenant_id if tenant_id else section.tenant_id)
        final_path, size = _write_buffered_to_storage(storage, path, empty_data, gzip_enabled=ICV_SITEMAPS_GZIP)
        new_files.append(
            {
                "sequence": 0,
                "path": final_path,
                "url_count": 0,
                "size": size,
                "checksum": _checksum(empty_data),
            }
        )

    # Update DB records for generated files.
    section.files.all().delete()
    for f in new_files:
        SitemapFile.objects.create(
            section=section,
            sequence=f["sequence"],
            storage_path=f["path"],
            url_count=f["url_count"],
            file_size_bytes=f["size"],
            checksum=f["checksum"],
        )

    # Remove stale storage files that are no longer referenced (BR-029).
    new_paths = {f["path"] for f in new_files}
    for stale_path in old_paths - new_paths:
        try:
            if storage.exists(stale_path):
                storage.delete(stale_path)
        except Exception:
            logger.warning("generate_section: failed to delete stale file %r", stale_path)

    # Update section stats.
    section.url_count = total_urls
    section.file_count = len(new_files)
    section.is_stale = False
    section.last_generated_at = django_timezone.now()
    section.save(
        update_fields=[
            "url_count",
            "file_count",
            "is_stale",
            "last_generated_at",
            "updated_at",
        ]
    )

    duration_ms = int(time.monotonic() * 1000) - start_ms

    # Update generation log.
    log.status = "success"
    log.url_count = total_urls
    log.file_count = len(new_files)
    log.duration_ms = duration_ms
    log.save(update_fields=["status", "url_count", "file_count", "duration_ms"])

    # Regenerate the sitemap index (BR-012).
    generate_index(tenant_id=section.tenant_id)

    # Conditional ping (BR-017): only ping when the index checksum changes.
    if _should_ping(tenant_id=section.tenant_id):
        from icv_sitemaps.conf import ICV_SITEMAPS_PING_ENABLED

        if ICV_SITEMAPS_PING_ENABLED:
            try:
                from icv_sitemaps.services.ping import ping_search_engines

                ping_search_engines(tenant_id=section.tenant_id)
            except Exception:
                logger.warning("generate_section: ping failed after generating %r", section.name)

    sitemap_section_generated.send(
        sender=section.__class__,
        instance=section,
        url_count=total_urls,
        file_count=len(new_files),
        duration_ms=duration_ms,
    )

    logger.info(
        "generate_section: %r generated %d URLs in %d files (%dms)",
        section.name,
        total_urls,
        len(new_files),
        duration_ms,
    )
    return total_urls


def _iter_section_entries(
    *,
    queryset,
    section,
    sitemap_type: str,
    base_url_setting: str,
    cutoff,
    model_class,
    batch_size: int,
):
    """Yield ``(entry_dict)`` for every eligible instance.

    Uses keyset pagination so we don't hold a long-running cursor across
    managed Postgres SSL/idle timeouts (BR-GEN-001).

    Memory management: Django model instances form reference cycles
    (``_state``, descriptor caches, deferred attrs) that CPython's
    generational GC promotes to gen-2, which is collected infrequently.
    On multi-million-row sections these zombie cycles accumulate faster
    than gen-2 collection runs, causing monotonic RSS growth.

    We break this by:
    - explicitly ``del``-ing the chunk list after extracting entries
    - calling ``gc.collect()`` every ``_GC_INTERVAL`` chunks to flush
      promoted cycles before they pile up
    - calling ``reset_queries()`` to prevent any residual query-log
      growth (safe even when ``DEBUG=False``)
    """
    import gc

    from django.db import close_old_connections, reset_queries

    news_date_field = ""
    if sitemap_type == "news":
        news_date_field = getattr(model_class, "sitemap_news_date_field", "")

    last_pk = None
    chunk_count = 0
    while True:
        chunk_qs = queryset.order_by("pk")
        if last_pk is not None:
            chunk_qs = chunk_qs.filter(pk__gt=last_pk)
        chunk = list(chunk_qs[:batch_size])
        if not chunk:
            break

        last_pk = chunk[-1].pk

        for instance in chunk:
            if sitemap_type == "news" and news_date_field and cutoff is not None:
                pub_date = getattr(instance, news_date_field, None)
                if pub_date is not None and pub_date < cutoff:
                    continue

            entry = _extract_entry(instance, sitemap_type, base_url_setting)
            if entry is None:
                continue

            yield entry

        # Release all model instances and their cached relations before
        # the next chunk — prevents the generator frame from pinning
        # 5000 instances (+ prefetch caches) across the yield boundary.
        del chunk
        chunk_count += 1

        reset_queries()

        # Force a full GC collection every _GC_INTERVAL chunks to
        # reclaim ref-cycles promoted to gen-2. On a 2.4M-row section
        # with batch_size=5000 this fires ~every 50K rows — frequent
        # enough to bound RSS, infrequent enough to be negligible cost.
        if chunk_count % _GC_INTERVAL == 0:
            gc.collect()

        close_old_connections()


def _generate_streaming(
    *,
    section,
    tenant_id: str,
    queryset,
    sitemap_type: str,
    base_url_setting: str,
    cutoff,
    model_class,
    storage,
    gzip_enabled: bool,
    batch_size: int,
    max_urls: int,
    max_bytes: int,
) -> tuple[int, list[dict]]:
    """Stream entries directly to per-shard temp files, then upload each."""
    new_files: list[dict] = []
    file_sequence = 0
    total_urls = 0

    writer = _StreamingSitemapWriter(sitemap_type, gzip_enabled=gzip_enabled)
    try:
        for entry in _iter_section_entries(
            queryset=queryset,
            section=section,
            sitemap_type=sitemap_type,
            base_url_setting=base_url_setting,
            cutoff=cutoff,
            model_class=model_class,
            batch_size=batch_size,
        ):
            if writer.url_count >= max_urls or (
                writer.url_count > 0 and writer.estimated_size_after(entry) > max_bytes
            ):
                temp_path, size, checksum = writer.finalize()
                try:
                    final_path = _publish_shard(
                        section=section,
                        tenant_id=tenant_id,
                        sequence=file_sequence,
                        storage=storage,
                        temp_path=temp_path,
                        gzip_enabled=gzip_enabled,
                    )
                finally:
                    _cleanup_temp(temp_path)
                new_files.append(
                    {
                        "sequence": file_sequence,
                        "path": final_path,
                        "url_count": writer.url_count,
                        "size": size,
                        "checksum": checksum,
                    }
                )
                total_urls += writer.url_count
                file_sequence += 1
                writer = _StreamingSitemapWriter(sitemap_type, gzip_enabled=gzip_enabled)

            writer.write_entry(entry)

        # Final shard (only if it has any entries).
        if writer.url_count > 0:
            temp_path, size, checksum = writer.finalize()
            try:
                final_path = _publish_shard(
                    section=section,
                    tenant_id=tenant_id,
                    sequence=file_sequence,
                    storage=storage,
                    temp_path=temp_path,
                    gzip_enabled=gzip_enabled,
                )
            finally:
                _cleanup_temp(temp_path)
            new_files.append(
                {
                    "sequence": file_sequence,
                    "path": final_path,
                    "url_count": writer.url_count,
                    "size": size,
                    "checksum": checksum,
                }
            )
            total_urls += writer.url_count
        else:
            writer.abort()
    except Exception:
        writer.abort()
        raise

    return total_urls, new_files


def _publish_shard(
    *,
    section,
    tenant_id: str,
    sequence: int,
    storage,
    temp_path: str,
    gzip_enabled: bool,
) -> str:
    """Upload a finalised shard temp file to its final storage path."""
    filename = f"{section.name}-{sequence}.xml"
    if gzip_enabled:
        filename += ".gz"
    dest = _storage_path(filename, tenant_id=tenant_id if tenant_id else section.tenant_id)
    final_path, _ = _upload_temp_to_storage(storage, temp_path, dest)
    return final_path


def _generate_buffered(
    *,
    section,
    tenant_id: str,
    queryset,
    sitemap_type: str,
    base_url_setting: str,
    cutoff,
    model_class,
    storage,
    gzip_enabled: bool,
    batch_size: int,
    max_urls: int,
    max_bytes: int,
) -> tuple[int, list[dict]]:
    """Legacy buffered code path (ICV_SITEMAPS_STREAMING_WRITER=False)."""
    new_files: list[dict] = []
    file_sequence = 0
    total_urls = 0
    current_entries: list[dict] = []
    current_size = 0

    def _flush() -> None:
        nonlocal total_urls, file_sequence, current_entries, current_size
        if not current_entries:
            return
        data = _build_buffered_xml(sitemap_type, current_entries)
        filename = f"{section.name}-{file_sequence}.xml"
        path = _storage_path(filename, tenant_id=tenant_id if tenant_id else section.tenant_id)
        final_path, size = _write_buffered_to_storage(storage, path, data, gzip_enabled=gzip_enabled)
        new_files.append(
            {
                "sequence": file_sequence,
                "path": final_path,
                "url_count": len(current_entries),
                "size": size,
                "checksum": _checksum(data),
            }
        )
        total_urls += len(current_entries)
        file_sequence += 1
        current_entries = []
        current_size = 0

    for entry in _iter_section_entries(
        queryset=queryset,
        section=section,
        sitemap_type=sitemap_type,
        base_url_setting=base_url_setting,
        cutoff=cutoff,
        model_class=model_class,
        batch_size=batch_size,
    ):
        entry_size_estimate = len(entry.get("loc", "")) + 200
        if current_entries and (len(current_entries) >= max_urls or current_size + entry_size_estimate > max_bytes):
            _flush()
        current_entries.append(entry)
        current_size += entry_size_estimate

    _flush()
    return total_urls, new_files


def _should_ping(*, tenant_id: str = "") -> bool:
    """Return True when search engine pinging is enabled.

    Placeholder for the BR-017 index-checksum deduplication logic.  For now
    this simply delegates to the ``ICV_SITEMAPS_PING_ENABLED`` setting so that
    the conditional ping call in ``generate_section`` compiles and behaves
    correctly.
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_PING_ENABLED

    return ICV_SITEMAPS_PING_ENABLED


def _get_base_url() -> str:
    from icv_sitemaps.conf import ICV_SITEMAPS_BASE_URL

    return ICV_SITEMAPS_BASE_URL


def generate_all_sections(
    *,
    tenant_id: str = "",
    force: bool = False,
) -> dict[str, int]:
    """Generate sitemaps for all active sections.

    Returns a dict mapping section names to URL counts. Only processes stale
    sections unless *force* is ``True`` (BR-010). Sends
    ``sitemap_generation_complete`` after all sections are done.
    """
    from icv_sitemaps.models.sections import SitemapSection
    from icv_sitemaps.signals import sitemap_generation_complete

    start_ms = int(time.monotonic() * 1000)

    qs = SitemapSection.objects.filter(is_active=True, tenant_id=tenant_id)
    if not force:
        qs = qs.filter(is_stale=True)

    results: dict[str, int] = {}
    for section in qs:
        try:
            url_count = generate_section(section, tenant_id=tenant_id, force=force)
            results[section.name] = url_count
        except Exception:
            logger.exception("generate_all_sections: error generating section %r", section.name)
            results[section.name] = 0

    duration_ms = int(time.monotonic() * 1000) - start_ms
    total_urls = sum(results.values())

    sitemap_generation_complete.send(
        sender=None,
        sections=list(results.keys()),
        total_urls=total_urls,
        duration_ms=duration_ms,
    )

    logger.info(
        "generate_all_sections: %d sections, %d total URLs (%dms)",
        len(results),
        total_urls,
        duration_ms,
    )
    return results


def generate_index(*, tenant_id: str = "") -> str:
    """Generate the sitemap index XML listing all SitemapFile records.

    Returns the storage path of the written index file (BR-011, BR-012).
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_GZIP
    from icv_sitemaps.models.sections import SitemapFile

    storage = _get_storage()

    sitemap_files = (
        SitemapFile.objects.filter(
            section__is_active=True,
            section__tenant_id=tenant_id,
        )
        .select_related("section")
        .order_by("section__name", "sequence")
    )

    base_url = _get_base_url().rstrip("/")

    # Build the index XML (small — always buffered).
    ET.register_namespace("", SITEMAP_NS)
    root = ET.Element("sitemapindex", attrib={"xmlns": SITEMAP_NS})

    for sf in sitemap_files:
        sitemap_el = ET.SubElement(root, "sitemap")
        loc = f"{base_url}/{sf.storage_path.lstrip('/')}"
        ET.SubElement(sitemap_el, "loc").text = loc
        lastmod = _format_lastmod(sf.generated_at)
        if lastmod:
            ET.SubElement(sitemap_el, "lastmod").text = lastmod

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    sbuf = io.StringIO()
    sbuf.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    tree.write(sbuf, encoding="unicode", xml_declaration=False)
    data = sbuf.getvalue().encode("utf-8")

    index_filename = "sitemap.xml"
    index_path = _storage_path(index_filename, tenant_id=tenant_id)

    final_path, _ = _write_buffered_to_storage(storage, index_path, data, gzip_enabled=ICV_SITEMAPS_GZIP)

    logger.debug("generate_index: wrote %r", final_path)
    return final_path


def mark_section_stale(
    section_name: str,
    *,
    tenant_id: str = "",
) -> bool:
    """Mark a sitemap section as stale.

    Uses a single UPDATE query to avoid an extra SELECT (avoids N+1 when
    called from auto-section signal handlers on every model save).

    Returns ``True`` if the section was found and marked. Sends
    ``sitemap_section_stale`` signal only when the state actually changed.
    """
    from icv_sitemaps.models.sections import SitemapSection
    from icv_sitemaps.signals import sitemap_section_stale

    updated = SitemapSection.objects.filter(
        name=section_name,
        tenant_id=tenant_id,
        is_stale=False,
    ).update(is_stale=True)

    if updated:
        try:
            section = SitemapSection.objects.get(name=section_name, tenant_id=tenant_id)
            sitemap_section_stale.send(sender=section.__class__, instance=section)
        except SitemapSection.DoesNotExist:
            pass
        return True

    return SitemapSection.objects.filter(name=section_name, tenant_id=tenant_id).exists()


def get_generation_stats(*, tenant_id: str = "") -> dict:
    """Return aggregate generation statistics for the given tenant.

    Returns a dict with keys:
    - ``total_sections``: int
    - ``stale_count``: int
    - ``total_urls``: int
    - ``total_files``: int
    - ``last_generation_at``: datetime | None
    """
    from django.db.models import Max, Sum

    from icv_sitemaps.models.sections import SitemapSection

    qs = SitemapSection.objects.filter(tenant_id=tenant_id)
    aggregate = qs.aggregate(
        total_urls=Sum("url_count"),
        total_files=Sum("file_count"),
        last_generation_at=Max("last_generated_at"),
    )

    return {
        "total_sections": qs.count(),
        "stale_count": qs.filter(is_stale=True).count(),
        "total_urls": aggregate["total_urls"] or 0,
        "total_files": aggregate["total_files"] or 0,
        "last_generation_at": aggregate["last_generation_at"],
    }
