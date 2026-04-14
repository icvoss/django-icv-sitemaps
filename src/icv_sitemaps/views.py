"""Views for serving sitemaps and discovery files."""

from __future__ import annotations

import logging
import os
import re

from django.core.cache import cache
from django.http import Http404, HttpResponse, HttpResponsePermanentRedirect
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_cache_timeout() -> int:
    """Return the configured cache timeout in seconds."""
    from icv_sitemaps.conf import ICV_SITEMAPS_CACHE_TIMEOUT

    return ICV_SITEMAPS_CACHE_TIMEOUT


def _get_tenant_id(request) -> str:
    """Return the tenant identifier for this request.

    Calls ``ICV_SITEMAPS_TENANT_PREFIX_FUNC`` (a dotted callable path) when
    set, passing the request as the only argument.  Falls back to ``""`` for
    single-tenant sites.
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_TENANT_PREFIX_FUNC

    if not ICV_SITEMAPS_TENANT_PREFIX_FUNC:
        return ""

    try:
        from django.utils.module_loading import import_string

        func = import_string(ICV_SITEMAPS_TENANT_PREFIX_FUNC)
        result = func(request) or ""
        if result and not re.fullmatch(r"[\w\-]+", result):
            logger.warning(
                "ICV_SITEMAPS_TENANT_PREFIX_FUNC returned unsafe tenant_id %r — ignoring.",
                result,
            )
            return ""
        return result
    except Exception:
        logger.exception(
            "Error calling ICV_SITEMAPS_TENANT_PREFIX_FUNC %r.",
            ICV_SITEMAPS_TENANT_PREFIX_FUNC,
        )
        return ""


def _validate_filename(filename: str) -> bool:
    """Return ``True`` when *filename* is safe to use as a storage path.

    Rejects path traversal attempts (``..``) and absolute paths.
    """
    if not filename:
        return False
    if os.path.isabs(filename):
        return False
    normalised = os.path.normpath(filename)
    return ".." not in normalised.split(os.sep)


# ---------------------------------------------------------------------------
# Sitemap views
# ---------------------------------------------------------------------------


@require_http_methods(["GET", "HEAD"])
def sitemap_index_view(request) -> HttpResponse:
    """Serve the sitemap index file from storage (GET /sitemap.xml).

    Reads the pre-generated ``sitemap.xml`` (or ``sitemap.xml.gz``) from the
    configured storage backend.  Falls back to on-the-fly generation via
    ``generate_index()`` when no file is present, suitable for small sites
    that have not yet run the generation command.
    """
    from django.core.files.storage import default_storage

    from icv_sitemaps.conf import ICV_SITEMAPS_GZIP, ICV_SITEMAPS_MAX_FILE_SIZE_BYTES, ICV_SITEMAPS_STORAGE_PATH
    from icv_sitemaps.services.generation import generate_index

    tenant_id = _get_tenant_id(request)

    storage_dir = ICV_SITEMAPS_STORAGE_PATH.rstrip("/")
    index_path = f"{storage_dir}/{tenant_id}/sitemap.xml" if tenant_id else f"{storage_dir}/sitemap.xml"

    gz_path = index_path + ".gz"

    # Attempt to serve from storage (prefer gz when GZIP enabled)
    for path in [gz_path, index_path] if ICV_SITEMAPS_GZIP else [index_path]:
        try:
            if default_storage.exists(path):
                file_size = default_storage.size(path)
                if file_size > ICV_SITEMAPS_MAX_FILE_SIZE_BYTES:
                    logger.warning(
                        "Sitemap index at %r exceeds size limit (%d > %d bytes) — refusing to serve.",
                        path,
                        file_size,
                        ICV_SITEMAPS_MAX_FILE_SIZE_BYTES,
                    )
                    raise Http404("Sitemap index file exceeds size limit.")
                with default_storage.open(path, "rb") as fh:
                    content = fh.read()
                response = HttpResponse(content, content_type="application/xml")
                if path.endswith(".gz"):
                    response["Content-Encoding"] = "gzip"
                return response
        except Http404:
            raise
        except Exception:
            logger.exception("Error reading sitemap index from storage path %r.", path)

    # Fall back to on-the-fly generation for small sites
    logger.info("Sitemap index not found in storage — generating on the fly.")
    try:
        generate_index(tenant_id=tenant_id)
        for path in [gz_path, index_path] if ICV_SITEMAPS_GZIP else [index_path]:
            if default_storage.exists(path):
                file_size = default_storage.size(path)
                if file_size > ICV_SITEMAPS_MAX_FILE_SIZE_BYTES:
                    logger.warning(
                        "Generated sitemap index at %r exceeds size limit (%d > %d bytes) — refusing to serve.",
                        path,
                        file_size,
                        ICV_SITEMAPS_MAX_FILE_SIZE_BYTES,
                    )
                    raise Http404("Sitemap index file exceeds size limit.")
                with default_storage.open(path, "rb") as fh:
                    content = fh.read()
                response = HttpResponse(content, content_type="application/xml")
                if path.endswith(".gz"):
                    response["Content-Encoding"] = "gzip"
                return response
    except Http404:
        raise
    except Exception:
        logger.exception("On-the-fly sitemap index generation failed.")

    raise Http404("Sitemap index not found.")


@require_http_methods(["GET", "HEAD"])
def sitemap_file_view(request, filename: str) -> HttpResponse:
    """Serve an individual sitemap file from storage (GET /sitemaps/<path:filename>).

    Validates *filename* to prevent path traversal before attempting to read
    from the configured storage backend.
    """
    from django.core.files.storage import default_storage

    from icv_sitemaps.conf import ICV_SITEMAPS_MAX_FILE_SIZE_BYTES, ICV_SITEMAPS_STORAGE_PATH

    if not _validate_filename(filename):
        raise Http404("Invalid filename.")

    storage_dir = ICV_SITEMAPS_STORAGE_PATH.rstrip("/")
    storage_path = f"{storage_dir}/{filename}"

    try:
        if not default_storage.exists(storage_path):
            raise Http404(f"Sitemap file not found: {filename!r}")

        file_size = default_storage.size(storage_path)
        if file_size > ICV_SITEMAPS_MAX_FILE_SIZE_BYTES:
            logger.warning(
                "Sitemap file at %r exceeds size limit (%d > %d bytes) — refusing to serve.",
                storage_path,
                file_size,
                ICV_SITEMAPS_MAX_FILE_SIZE_BYTES,
            )
            raise Http404("Sitemap file exceeds size limit.")

        with default_storage.open(storage_path, "rb") as fh:
            content = fh.read()

        response = HttpResponse(content, content_type="application/xml")
        if storage_path.endswith(".gz"):
            response["Content-Encoding"] = "gzip"
        return response
    except Http404:
        raise
    except Exception as exc:
        logger.exception("Error serving sitemap file %r.", filename)
        raise Http404("Error reading sitemap file.") from exc


# ---------------------------------------------------------------------------
# Discovery file views
# ---------------------------------------------------------------------------


@require_http_methods(["GET", "HEAD"])
def robots_txt_view(request) -> HttpResponse:
    """Serve robots.txt (GET /robots.txt).

    Content is rendered from database ``RobotsRule`` records and settings,
    then cached for ``ICV_SITEMAPS_CACHE_TIMEOUT`` seconds.  Cache is
    invalidated automatically when rules change (see ``handlers.py``).
    """
    from icv_sitemaps.services.robots import render_robots_txt

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:robots_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = cache.get(cache_key)
    if content is None:
        try:
            content = render_robots_txt(tenant_id=tenant_id)
        except Exception:
            logger.exception("Error rendering robots.txt.")
            content = ""
        cache.set(cache_key, content, timeout)

    return HttpResponse(content, content_type="text/plain")


@require_http_methods(["GET", "HEAD"])
def llms_txt_view(request) -> HttpResponse:
    """Serve llms.txt (GET /llms.txt).

    Returns 404 when no active ``DiscoveryFileConfig`` record exists for the
    ``llms_txt`` type.  Content is cached for ``ICV_SITEMAPS_CACHE_TIMEOUT``
    seconds.
    """
    from icv_sitemaps.services.discovery import get_discovery_file_content

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:discovery:llms_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = cache.get(cache_key)
    if content is None:
        content = get_discovery_file_content("llms_txt", tenant_id=tenant_id)
        if content is None:
            raise Http404("llms.txt not configured.")
        cache.set(cache_key, content, timeout)

    return HttpResponse(content, content_type="text/plain; charset=utf-8")


@require_http_methods(["GET", "HEAD"])
def ads_txt_view(request) -> HttpResponse:
    """Serve ads.txt (GET /ads.txt).

    Content is rendered from active ``AdsEntry`` records with
    ``is_app_ads=False`` and cached for ``ICV_SITEMAPS_CACHE_TIMEOUT``
    seconds.
    """
    from icv_sitemaps.services.ads import render_ads_txt

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:ads_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = cache.get(cache_key)
    if content is None:
        try:
            content = render_ads_txt(app_ads=False, tenant_id=tenant_id)
        except Exception:
            logger.exception("Error rendering ads.txt.")
            content = ""
        cache.set(cache_key, content, timeout)

    return HttpResponse(content, content_type="text/plain")


@require_http_methods(["GET", "HEAD"])
def app_ads_txt_view(request) -> HttpResponse:
    """Serve app-ads.txt (GET /app-ads.txt).

    Content is rendered from active ``AdsEntry`` records with
    ``is_app_ads=True`` and cached for ``ICV_SITEMAPS_CACHE_TIMEOUT`` seconds.
    """
    from icv_sitemaps.services.ads import render_ads_txt

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:app_ads_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = cache.get(cache_key)
    if content is None:
        try:
            content = render_ads_txt(app_ads=True, tenant_id=tenant_id)
        except Exception:
            logger.exception("Error rendering app-ads.txt.")
            content = ""
        cache.set(cache_key, content, timeout)

    return HttpResponse(content, content_type="text/plain")


@require_http_methods(["GET", "HEAD"])
def security_txt_view(request) -> HttpResponse:
    """Serve /.well-known/security.txt.

    Returns 404 when no active ``DiscoveryFileConfig`` record exists for the
    ``security_txt`` type.  Content is cached for ``ICV_SITEMAPS_CACHE_TIMEOUT``
    seconds.
    """
    from icv_sitemaps.services.discovery import get_discovery_file_content

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:discovery:security_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = cache.get(cache_key)
    if content is None:
        content = get_discovery_file_content("security_txt", tenant_id=tenant_id)
        if content is None:
            raise Http404("security.txt not configured.")
        cache.set(cache_key, content, timeout)

    return HttpResponse(content, content_type="text/plain")


def security_txt_root_view(request) -> HttpResponsePermanentRedirect:
    """Redirect /security.txt to /.well-known/security.txt (301).

    The canonical location for security.txt is ``/.well-known/security.txt``
    per RFC 9116.  Requests to the root path are permanently redirected.
    """
    try:
        from django.urls import reverse

        canonical_url = reverse("icv_sitemaps:security-txt")
    except Exception:
        canonical_url = "/.well-known/security.txt"

    return HttpResponsePermanentRedirect(canonical_url)


@require_http_methods(["GET", "HEAD"])
def humans_txt_view(request) -> HttpResponse:
    """Serve humans.txt (GET /humans.txt).

    Returns 404 when no active ``DiscoveryFileConfig`` record exists for the
    ``humans_txt`` type.  Content is cached for ``ICV_SITEMAPS_CACHE_TIMEOUT``
    seconds.
    """
    from icv_sitemaps.services.discovery import get_discovery_file_content

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:discovery:humans_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = cache.get(cache_key)
    if content is None:
        content = get_discovery_file_content("humans_txt", tenant_id=tenant_id)
        if content is None:
            raise Http404("humans.txt not configured.")
        cache.set(cache_key, content, timeout)

    return HttpResponse(content, content_type="text/plain")
