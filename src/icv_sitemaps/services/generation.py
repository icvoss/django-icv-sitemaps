"""Sitemap XML generation services."""

from __future__ import annotations

import gzip
import hashlib
import io
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from django.apps import apps
from django.core.files.base import ContentFile
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


def _write_to_storage(storage, path: str, data: bytes, *, gzip_enabled: bool = False) -> tuple[str, int]:
    """Write *data* atomically to *path* in *storage*.

    Returns ``(final_path, size_bytes)``.

    Atomic write (BR-006): write to a temporary path, then rename.
    """
    if gzip_enabled:
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(data)
        data = buf.getvalue()
        if not path.endswith(".gz"):
            path = path + ".gz"

    # Atomic write (BR-006): write to temp path, then overwrite the final path.
    # Most Django storage backends do not support true rename, so we write
    # the final file by deleting the old one first and saving fresh.
    tmp_path = path + ".tmp"

    # Write to temp path first.
    if storage.exists(tmp_path):
        storage.delete(tmp_path)
    storage.save(tmp_path, ContentFile(data))

    # Swap temp → final: delete old file, save data to final path.
    if storage.exists(path):
        storage.delete(path)
    storage.save(path, ContentFile(data))

    # Remove temp file now that final file is in place.
    if storage.exists(tmp_path):
        storage.delete(tmp_path)

    return path, len(data)


# ---------------------------------------------------------------------------
# XML builders
# ---------------------------------------------------------------------------


def _build_standard_xml(entries: list[dict]) -> bytes:
    """Build a standard sitemap XML document."""
    root = ET.Element(
        "urlset",
        xmlns=SITEMAP_NS,
    )
    for entry in entries:
        url_el = ET.SubElement(root, "url")
        ET.SubElement(url_el, "loc").text = entry["loc"]
        if entry.get("lastmod"):
            ET.SubElement(url_el, "lastmod").text = entry["lastmod"]
        if entry.get("changefreq"):
            ET.SubElement(url_el, "changefreq").text = entry["changefreq"]
        if entry.get("priority") is not None:
            ET.SubElement(url_el, "priority").text = str(entry["priority"])
    return _xml_bytes(root)


def _build_image_xml(entries: list[dict]) -> bytes:
    """Build an image sitemap XML document (BR-013)."""
    ET.register_namespace("", SITEMAP_NS)
    ET.register_namespace("image", IMAGE_NS)

    root = ET.Element(
        "urlset",
        attrib={
            "xmlns": SITEMAP_NS,
            "xmlns:image": IMAGE_NS,
        },
    )
    for entry in entries:
        url_el = ET.SubElement(root, "url")
        ET.SubElement(url_el, "loc").text = entry["loc"]
        if entry.get("lastmod"):
            ET.SubElement(url_el, "lastmod").text = entry["lastmod"]
        if entry.get("changefreq"):
            ET.SubElement(url_el, "changefreq").text = entry["changefreq"]
        if entry.get("priority") is not None:
            ET.SubElement(url_el, "priority").text = str(entry["priority"])
        for image in entry.get("images", []):
            img_el = ET.SubElement(url_el, f"{{{IMAGE_NS}}}image")
            ET.SubElement(img_el, f"{{{IMAGE_NS}}}loc").text = image["loc"]
            if image.get("caption"):
                ET.SubElement(img_el, f"{{{IMAGE_NS}}}caption").text = image["caption"]
            if image.get("title"):
                ET.SubElement(img_el, f"{{{IMAGE_NS}}}title").text = image["title"]
            if image.get("geo_location"):
                ET.SubElement(img_el, f"{{{IMAGE_NS}}}geo_location").text = image["geo_location"]
            if image.get("license"):
                ET.SubElement(img_el, f"{{{IMAGE_NS}}}license").text = image["license"]
    return _xml_bytes(root)


def _build_video_xml(entries: list[dict]) -> bytes:
    """Build a video sitemap XML document (BR-014)."""
    ET.register_namespace("", SITEMAP_NS)
    ET.register_namespace("video", VIDEO_NS)

    root = ET.Element(
        "urlset",
        attrib={
            "xmlns": SITEMAP_NS,
            "xmlns:video": VIDEO_NS,
        },
    )
    for entry in entries:
        url_el = ET.SubElement(root, "url")
        ET.SubElement(url_el, "loc").text = entry["loc"]
        if entry.get("lastmod"):
            ET.SubElement(url_el, "lastmod").text = entry["lastmod"]
        if entry.get("changefreq"):
            ET.SubElement(url_el, "changefreq").text = entry["changefreq"]
        if entry.get("priority") is not None:
            ET.SubElement(url_el, "priority").text = str(entry["priority"])
        video = entry.get("video")
        if video:
            vid_el = ET.SubElement(url_el, f"{{{VIDEO_NS}}}video")
            if video.get("thumbnail_loc"):
                ET.SubElement(vid_el, f"{{{VIDEO_NS}}}thumbnail_loc").text = video["thumbnail_loc"]
            if video.get("title"):
                ET.SubElement(vid_el, f"{{{VIDEO_NS}}}title").text = video["title"]
            if video.get("description"):
                ET.SubElement(vid_el, f"{{{VIDEO_NS}}}description").text = video["description"]
            if video.get("content_loc"):
                ET.SubElement(vid_el, f"{{{VIDEO_NS}}}content_loc").text = video["content_loc"]
            if video.get("player_loc"):
                ET.SubElement(vid_el, f"{{{VIDEO_NS}}}player_loc").text = video["player_loc"]
            if video.get("duration") is not None:
                ET.SubElement(vid_el, f"{{{VIDEO_NS}}}duration").text = str(video["duration"])
            if video.get("rating") is not None:
                ET.SubElement(vid_el, f"{{{VIDEO_NS}}}rating").text = str(video["rating"])
            if video.get("publication_date"):
                ET.SubElement(vid_el, f"{{{VIDEO_NS}}}publication_date").text = str(video["publication_date"])
    return _xml_bytes(root)


def _build_news_xml(entries: list[dict]) -> bytes:
    """Build a news sitemap XML document (BR-015, BR-016)."""
    ET.register_namespace("", SITEMAP_NS)
    ET.register_namespace("news", NEWS_NS)

    root = ET.Element(
        "urlset",
        attrib={
            "xmlns": SITEMAP_NS,
            "xmlns:news": NEWS_NS,
        },
    )
    for entry in entries:
        url_el = ET.SubElement(root, "url")
        ET.SubElement(url_el, "loc").text = entry["loc"]
        news = entry.get("news")
        if news:
            news_el = ET.SubElement(url_el, f"{{{NEWS_NS}}}news")
            pub_el = ET.SubElement(news_el, f"{{{NEWS_NS}}}publication")
            ET.SubElement(pub_el, f"{{{NEWS_NS}}}name").text = news.get("publication_name", "")
            ET.SubElement(pub_el, f"{{{NEWS_NS}}}language").text = news.get("language", "en")
            pub_date = news.get("publication_date")
            if pub_date is not None:
                pub_date_str = _format_lastmod(pub_date) or str(pub_date)
                ET.SubElement(news_el, f"{{{NEWS_NS}}}publication_date").text = pub_date_str
            ET.SubElement(news_el, f"{{{NEWS_NS}}}title").text = news.get("title", "")
    return _xml_bytes(root)


def _xml_bytes(root: ET.Element) -> bytes:
    """Serialise an ElementTree root element to bytes with XML declaration."""
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    # Use a StringIO so tree.write(encoding="unicode") can write strings,
    # then encode the whole thing to UTF-8 bytes at the end.
    import io as _io

    sbuf = _io.StringIO()
    sbuf.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    tree.write(sbuf, encoding="unicode", xml_declaration=False)
    return sbuf.getvalue().encode("utf-8")


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


def _should_ping(tenant_id: str = "") -> bool:
    """Return True if the sitemap index has changed since the last ping (BR-017).

    Reads the current index file from storage, computes a SHA-256 checksum, and
    compares it against the value stored in cache.  Returns ``True`` (and updates
    the cache) when the checksum differs, so pinging only happens when something
    actually changed.  Returns ``True`` when the index cannot be read, to err on
    the side of pinging.
    """
    from django.core.cache import cache as django_cache
    from django.core.files.storage import default_storage

    from icv_sitemaps.conf import ICV_SITEMAPS_GZIP, ICV_SITEMAPS_STORAGE_PATH

    storage_dir = ICV_SITEMAPS_STORAGE_PATH.rstrip("/")
    base_path = f"{storage_dir}/{tenant_id}/sitemap.xml" if tenant_id else f"{storage_dir}/sitemap.xml"
    candidate_paths = [base_path + ".gz", base_path] if ICV_SITEMAPS_GZIP else [base_path]

    new_checksum: str | None = None
    for path in candidate_paths:
        try:
            if default_storage.exists(path):
                with default_storage.open(path, "rb") as fh:
                    new_checksum = _checksum(fh.read())
                break
        except Exception:
            continue

    if new_checksum is None:
        # Cannot read index — ping to be safe.
        return True

    cache_key = f"icv_sitemaps:index_checksum:{tenant_id}"
    old_checksum = django_cache.get(cache_key)

    if new_checksum == old_checksum:
        return False

    django_cache.set(cache_key, new_checksum, timeout=None)
    return True


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

    # Accumulate entries across batches, splitting into files when limits hit.
    current_entries: list[dict] = []
    current_size: int = 0
    file_sequence: int = 0
    total_urls: int = 0
    new_files: list[dict] = []  # list of {sequence, path, url_count, size, checksum}

    def _flush_file(entries: list[dict], sequence: int) -> None:
        nonlocal total_urls
        if not entries:
            return

        data = _build_xml_for_type(sitemap_type, entries)
        ext = ".xml"
        filename = f"{section.name}-{sequence}{ext}"
        path = _storage_path(filename, tenant_id=tenant_id if tenant_id else section.tenant_id)
        final_path, size = _write_to_storage(storage, path, data, gzip_enabled=ICV_SITEMAPS_GZIP)
        digest = _checksum(data)
        new_files.append(
            {
                "sequence": sequence,
                "path": final_path,
                "url_count": len(entries),
                "size": size,
                "checksum": digest,
            }
        )
        total_urls += len(entries)

    # Keyset pagination: issue a fresh query per batch to avoid long-running
    # cursors that get killed by managed Postgres SSL/idle timeouts (BR-GEN-001).
    from django.db import close_old_connections

    last_pk = None
    while True:
        chunk_qs = queryset.order_by("pk")
        if last_pk is not None:
            chunk_qs = chunk_qs.filter(pk__gt=last_pk)
        chunk = list(chunk_qs[:ICV_SITEMAPS_BATCH_SIZE])
        if not chunk:
            break

        for instance in chunk:
            # Skip news entries older than cutoff (BR-015).
            if section.sitemap_type == "news":
                news_date_field = getattr(model_class, "sitemap_news_date_field", "")
                if news_date_field:
                    pub_date = getattr(instance, news_date_field, None)
                    if pub_date is not None and pub_date < cutoff:
                        continue

            entry = _extract_entry(instance, sitemap_type, base_url_setting)
            if entry is None:
                continue

            # Estimate entry size.
            entry_size_estimate = len(entry.get("loc", "")) + 200

            # Check if adding this entry would exceed limits (BR-001, BR-002).
            if current_entries and (
                len(current_entries) >= ICV_SITEMAPS_MAX_URLS_PER_FILE
                or current_size + entry_size_estimate > ICV_SITEMAPS_MAX_FILE_SIZE_BYTES
            ):
                _flush_file(current_entries, file_sequence)
                file_sequence += 1
                current_entries = []
                current_size = 0

            current_entries.append(entry)
            current_size += entry_size_estimate

        last_pk = chunk[-1].pk
        close_old_connections()

    # Flush the last batch.
    _flush_file(current_entries, file_sequence)

    # Write a valid empty urlset for sections with no URLs (TS-012).
    if not new_files:
        empty_data = _build_xml_for_type(sitemap_type, [])
        ext = ".xml"
        filename = f"{section.name}-0{ext}"
        path = _storage_path(
            filename,
            tenant_id=tenant_id if tenant_id else section.tenant_id,
        )
        final_path, size = _write_to_storage(storage, path, empty_data, gzip_enabled=ICV_SITEMAPS_GZIP)
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


def _should_ping(*, tenant_id: str = "") -> bool:
    """Return True when search engine pinging is enabled.

    Placeholder for the BR-017 index-checksum deduplication logic.  For now
    this simply delegates to the ``ICV_SITEMAPS_PING_ENABLED`` setting so that
    the conditional ping call in ``generate_section`` compiles and behaves
    correctly.
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_PING_ENABLED

    return ICV_SITEMAPS_PING_ENABLED


def _build_xml_for_type(sitemap_type: str, entries: list[dict]) -> bytes:
    """Dispatch to the correct XML builder based on *sitemap_type*."""
    if sitemap_type == "image":
        return _build_image_xml(entries)
    if sitemap_type == "video":
        return _build_video_xml(entries)
    if sitemap_type == "news":
        return _build_news_xml(entries)
    return _build_standard_xml(entries)


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

    # Build the index XML.
    ET.register_namespace("", SITEMAP_NS)
    root = ET.Element("sitemapindex", attrib={"xmlns": SITEMAP_NS})

    for sf in sitemap_files:
        sitemap_el = ET.SubElement(root, "sitemap")
        # Build a public URL from the storage path.
        loc = f"{base_url}/{sf.storage_path.lstrip('/')}"
        ET.SubElement(sitemap_el, "loc").text = loc
        lastmod = _format_lastmod(sf.generated_at)
        if lastmod:
            ET.SubElement(sitemap_el, "lastmod").text = lastmod

    data = _xml_bytes(root)
    index_filename = "sitemap.xml"
    index_path = _storage_path(index_filename, tenant_id=tenant_id)

    final_path, _ = _write_to_storage(storage, index_path, data, gzip_enabled=ICV_SITEMAPS_GZIP)

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
        # Fetch section for signal — only when state actually changed.
        try:
            section = SitemapSection.objects.get(name=section_name, tenant_id=tenant_id)
            sitemap_section_stale.send(sender=section.__class__, instance=section)
        except SitemapSection.DoesNotExist:
            pass
        return True

    # Check if the section exists but was already stale.
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
