"""Views for serving sitemaps and discovery files."""

from __future__ import annotations

import hashlib
import logging
import os
import re

from django.http import Http404, HttpResponse, HttpResponsePermanentRedirect
from django.utils.cache import get_conditional_response, patch_cache_control
from django.utils.http import http_date, quote_etag
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_cache_timeout() -> int:
    """Return the configured cache timeout in seconds."""
    from icv_sitemaps.conf import ICV_SITEMAPS_CACHE_TIMEOUT

    return ICV_SITEMAPS_CACHE_TIMEOUT


def _content_etag(content: bytes | str) -> str:
    """Return a quoted strong ETag: the SHA-256 hex digest of *content*.

    A hash of the exact bytes served is a legitimate strong validator for
    both stored sitemap files (where it happens to equal ``SitemapFile
    .checksum`` when the shard is unchanged) and rendered discovery files
    (where there is no other persisted validator to reach for).
    """
    data = content.encode("utf-8") if isinstance(content, str) else content
    digest = hashlib.sha256(data).hexdigest()
    return quote_etag(digest)


def _apply_cache_control(response: HttpResponse) -> None:
    """Patch ``Cache-Control`` onto *response* per ``ICV_SITEMAPS_HTTP_CACHE_CONTROL``.

    Empty (default) derives ``public, max-age=<ICV_SITEMAPS_CACHE_TIMEOUT>``.
    The literal value ``"none"`` disables the header entirely. Any other
    non-empty string is sent verbatim. Callers on a render-failure path
    must not call this: a failed render is never cacheable regardless of
    this setting.
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_HTTP_CACHE_CONTROL

    override = ICV_SITEMAPS_HTTP_CACHE_CONTROL
    if override == "none":
        return
    if override:
        response["Cache-Control"] = override
        return
    patch_cache_control(response, public=True, max_age=_get_cache_timeout())


def _finalise_cacheable_response(
    request,
    response: HttpResponse,
    *,
    content: bytes | str,
    last_modified=None,
) -> HttpResponse:
    """Attach validators and Cache-Control, then resolve conditional GET.

    Sets ``ETag`` (always, hashed from *content*) and ``Last-Modified``
    (only when *last_modified* is a genuine, non-fabricated datetime),
    applies ``Cache-Control``, then defers to Django's own
    ``get_conditional_response`` to honour ``If-None-Match`` /
    ``If-Modified-Since`` and return a bodyless 304 when they match. This
    must only be called on a response that is genuinely fit to cache; a
    render-failure fallback body must never reach this helper.
    """
    etag = _content_etag(content)
    response["ETag"] = etag
    last_modified_epoch = None
    if last_modified is not None:
        last_modified_epoch = int(last_modified.timestamp())
        response["Last-Modified"] = http_date(last_modified_epoch)
    _apply_cache_control(response)
    return get_conditional_response(
        request,
        etag=etag,
        last_modified=last_modified_epoch,
        response=response,
    )


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


def _sitemap_response(content: bytes, path: str) -> HttpResponse:
    """Build an :class:`HttpResponse` for a stored sitemap file.

    Pre-gzipped ``.gz`` files are served as an opaque gzip download
    (``Content-Type: application/gzip``) with **no** ``Content-Encoding``
    header.  Search-engine sitemap fetchers (notably Googlebot) do not send
    ``Accept-Encoding: gzip`` and treat the ``.gz`` entity itself as the
    gzipped sitemap, decompressing it by content type.  Sending
    ``Content-Encoding: gzip`` marks the body as *transport*-compressed, which
    contradicts the ``.gz`` entity semantics and causes the sitemap to be
    rejected.  Plain files are served as ``application/xml``.
    """
    if path.endswith(".gz"):
        return HttpResponse(content, content_type="application/gzip")
    return HttpResponse(content, content_type="application/xml")


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

    Emits a strong ``ETag`` hashed from the served bytes and honours
    ``If-None-Match`` with a bodyless 304. No ``Last-Modified`` header: the
    index has no ``SitemapFile`` row of its own (it lists every section's
    files) and no other genuinely persisted modification time, so this
    view omits the header rather than fabricate one.
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_GZIP, ICV_SITEMAPS_MAX_FILE_SIZE_BYTES, ICV_SITEMAPS_STORAGE_PATH
    from icv_sitemaps.services.generation import generate_index
    from icv_sitemaps.storage import get_storage

    storage = get_storage()
    tenant_id = _get_tenant_id(request)

    storage_dir = ICV_SITEMAPS_STORAGE_PATH.rstrip("/")
    index_path = f"{storage_dir}/{tenant_id}/sitemap.xml" if tenant_id else f"{storage_dir}/sitemap.xml"

    gz_path = index_path + ".gz"

    # Attempt to serve from storage (prefer gz when GZIP enabled)
    for path in [gz_path, index_path] if ICV_SITEMAPS_GZIP else [index_path]:
        try:
            if storage.exists(path):
                file_size = storage.size(path)
                if file_size > ICV_SITEMAPS_MAX_FILE_SIZE_BYTES:
                    logger.warning(
                        "Sitemap index at %r exceeds size limit (%d > %d bytes) — refusing to serve.",
                        path,
                        file_size,
                        ICV_SITEMAPS_MAX_FILE_SIZE_BYTES,
                    )
                    raise Http404("Sitemap index file exceeds size limit.")
                with storage.open(path, "rb") as fh:
                    content = fh.read()
                response = _sitemap_response(content, path)
                return _finalise_cacheable_response(request, response, content=content)
        except Http404:
            raise
        except Exception:
            logger.exception("Error reading sitemap index from storage path %r.", path)

    # Fall back to on-the-fly generation for small sites
    logger.info("Sitemap index not found in storage — generating on the fly.")
    try:
        generate_index(tenant_id=tenant_id)
        for path in [gz_path, index_path] if ICV_SITEMAPS_GZIP else [index_path]:
            if storage.exists(path):
                file_size = storage.size(path)
                if file_size > ICV_SITEMAPS_MAX_FILE_SIZE_BYTES:
                    logger.warning(
                        "Generated sitemap index at %r exceeds size limit (%d > %d bytes) — refusing to serve.",
                        path,
                        file_size,
                        ICV_SITEMAPS_MAX_FILE_SIZE_BYTES,
                    )
                    raise Http404("Sitemap index file exceeds size limit.")
                with storage.open(path, "rb") as fh:
                    content = fh.read()
                response = _sitemap_response(content, path)
                return _finalise_cacheable_response(request, response, content=content)
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

    Emits a strong ``ETag`` hashed from the served bytes and honours
    ``If-None-Match`` with a bodyless 304. Emits ``Last-Modified`` (and
    honours ``If-Modified-Since``) only when a ``SitemapFile`` row exists
    for this exact storage path: that row's ``generated_at`` is a genuine,
    persisted modification time (carried forward unchanged when a
    regeneration reproduces the same content, per BR-IDX-003), never a
    fabricated "now". A file served with no matching row (for example one
    placed directly in storage) gets no ``Last-Modified`` header.
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_MAX_FILE_SIZE_BYTES, ICV_SITEMAPS_STORAGE_PATH
    from icv_sitemaps.models.sections import SitemapFile
    from icv_sitemaps.storage import get_storage

    storage = get_storage()

    if not _validate_filename(filename):
        raise Http404("Invalid filename.")

    storage_dir = ICV_SITEMAPS_STORAGE_PATH.rstrip("/")
    storage_path = f"{storage_dir}/{filename}"

    try:
        if not storage.exists(storage_path):
            raise Http404(f"Sitemap file not found: {filename!r}")

        file_size = storage.size(storage_path)
        if file_size > ICV_SITEMAPS_MAX_FILE_SIZE_BYTES:
            logger.warning(
                "Sitemap file at %r exceeds size limit (%d > %d bytes) — refusing to serve.",
                storage_path,
                file_size,
                ICV_SITEMAPS_MAX_FILE_SIZE_BYTES,
            )
            raise Http404("Sitemap file exceeds size limit.")

        with storage.open(storage_path, "rb") as fh:
            content = fh.read()

        response = _sitemap_response(content, storage_path)
        last_modified = (
            SitemapFile.objects.filter(storage_path=storage_path).values_list("generated_at", flat=True).first()
        )
        return _finalise_cacheable_response(request, response, content=content, last_modified=last_modified)
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

    The cache is treated as an optimisation: a backend failure on read or
    write degrades to regenerating (and not caching) the content rather
    than raising.  A rendering failure is served as an empty body but is
    never cached, since an empty robots.txt means "allow everything", the
    opposite of a restrictive ruleset that failed to render, and caching
    it would serve that for the full timeout.

    A successfully rendered (or cache-hit) body gets a strong ``ETag``
    hashed from that body and honours ``If-None-Match``, plus
    ``Cache-Control`` per ``ICV_SITEMAPS_HTTP_CACHE_CONTROL``. A
    render-failure body gets neither: it must not be validated as
    "unchanged" against a previous good body, and must not be told to a
    client or an intermediate cache as safe to reuse. No ``Last-Modified``:
    the rendered body aggregates every ``RobotsRule`` row for the tenant
    with no single genuine modification time to report.
    """
    from icv_sitemaps.cache import safe_get, safe_set
    from icv_sitemaps.services.robots import render_robots_txt

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:robots_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = safe_get(cache_key)
    render_failed = False
    if content is None:
        try:
            content = render_robots_txt(tenant_id=tenant_id)
        except Exception:
            logger.exception("Error rendering robots.txt.")
            content = ""
            render_failed = True
        else:
            safe_set(cache_key, content, timeout)

    response = HttpResponse(content, content_type="text/plain")
    if render_failed:
        return response
    return _finalise_cacheable_response(request, response, content=content)


@require_http_methods(["GET", "HEAD"])
def llms_txt_view(request) -> HttpResponse:
    """Serve llms.txt (GET /llms.txt).

    Returns 404 when no active ``DiscoveryFileConfig`` record exists for the
    ``llms_txt`` type.  Content is cached for ``ICV_SITEMAPS_CACHE_TIMEOUT``
    seconds.

    Emits a strong ``ETag`` hashed from the served body and honours
    ``If-None-Match``, plus ``Cache-Control`` per
    ``ICV_SITEMAPS_HTTP_CACHE_CONTROL``. No ``Last-Modified``:
    ``get_discovery_file_content()`` returns the stored text only, not the
    row's ``updated_at``, and there is no other genuine modification time
    to report here.
    """
    from icv_sitemaps.cache import safe_get, safe_set
    from icv_sitemaps.services.discovery import get_discovery_file_content

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:discovery:llms_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = safe_get(cache_key)
    if content is None:
        content = get_discovery_file_content("llms_txt", tenant_id=tenant_id)
        if content is None:
            raise Http404("llms.txt not configured.")
        safe_set(cache_key, content, timeout)

    response = HttpResponse(content, content_type="text/plain; charset=utf-8")
    return _finalise_cacheable_response(request, response, content=content)


@require_http_methods(["GET", "HEAD"])
def ads_txt_view(request) -> HttpResponse:
    """Serve ads.txt (GET /ads.txt).

    Content is rendered from active ``AdsEntry`` records with
    ``is_app_ads=False`` and cached for ``ICV_SITEMAPS_CACHE_TIMEOUT``
    seconds.

    A successfully rendered (or cache-hit) body gets a strong ``ETag`` and
    honours ``If-None-Match``, plus ``Cache-Control``. A render-failure
    body gets neither, for the same reason as ``robots_txt_view``: an
    empty ads.txt reads as "no authorised sellers declared", which must
    not be served as a validated, cacheable 200 when it is really a
    rendering failure. No ``Last-Modified``: the body aggregates every
    matching ``AdsEntry`` row with no single genuine modification time.
    """
    from icv_sitemaps.cache import safe_get, safe_set
    from icv_sitemaps.services.ads import render_ads_txt

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:ads_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = safe_get(cache_key)
    render_failed = False
    if content is None:
        try:
            content = render_ads_txt(app_ads=False, tenant_id=tenant_id)
        except Exception:
            logger.exception("Error rendering ads.txt.")
            content = ""
            render_failed = True
        else:
            safe_set(cache_key, content, timeout)

    response = HttpResponse(content, content_type="text/plain")
    if render_failed:
        return response
    return _finalise_cacheable_response(request, response, content=content)


@require_http_methods(["GET", "HEAD"])
def app_ads_txt_view(request) -> HttpResponse:
    """Serve app-ads.txt (GET /app-ads.txt).

    Content is rendered from active ``AdsEntry`` records with
    ``is_app_ads=True`` and cached for ``ICV_SITEMAPS_CACHE_TIMEOUT`` seconds.

    Same validator and Cache-Control treatment as ``ads_txt_view``,
    including the same render-failure carve-out: a failed render is never
    given an ``ETag`` or a positive ``Cache-Control`` max-age.
    """
    from icv_sitemaps.cache import safe_get, safe_set
    from icv_sitemaps.services.ads import render_ads_txt

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:app_ads_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = safe_get(cache_key)
    render_failed = False
    if content is None:
        try:
            content = render_ads_txt(app_ads=True, tenant_id=tenant_id)
        except Exception:
            logger.exception("Error rendering app-ads.txt.")
            content = ""
            render_failed = True
        else:
            safe_set(cache_key, content, timeout)

    response = HttpResponse(content, content_type="text/plain")
    if render_failed:
        return response
    return _finalise_cacheable_response(request, response, content=content)


@require_http_methods(["GET", "HEAD"])
def security_txt_view(request) -> HttpResponse:
    """Serve /.well-known/security.txt.

    Returns 404 when no active ``DiscoveryFileConfig`` record exists for the
    ``security_txt`` type.  Content is cached for ``ICV_SITEMAPS_CACHE_TIMEOUT``
    seconds.

    Same validator and Cache-Control treatment as ``llms_txt_view``: a
    strong ``ETag`` hashed from the body, no ``Last-Modified``.
    """
    from icv_sitemaps.cache import safe_get, safe_set
    from icv_sitemaps.services.discovery import get_discovery_file_content

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:discovery:security_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = safe_get(cache_key)
    if content is None:
        content = get_discovery_file_content("security_txt", tenant_id=tenant_id)
        if content is None:
            raise Http404("security.txt not configured.")
        safe_set(cache_key, content, timeout)

    response = HttpResponse(content, content_type="text/plain")
    return _finalise_cacheable_response(request, response, content=content)


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

    Same validator and Cache-Control treatment as ``llms_txt_view``: a
    strong ``ETag`` hashed from the body, no ``Last-Modified``.
    """
    from icv_sitemaps.cache import safe_get, safe_set
    from icv_sitemaps.services.discovery import get_discovery_file_content

    tenant_id = _get_tenant_id(request)
    cache_key = f"icv_sitemaps:discovery:humans_txt:{tenant_id}"
    timeout = _get_cache_timeout()

    content = safe_get(cache_key)
    if content is None:
        content = get_discovery_file_content("humans_txt", tenant_id=tenant_id)
        if content is None:
            raise Http404("humans.txt not configured.")
        safe_set(cache_key, content, timeout)

    response = HttpResponse(content, content_type="text/plain")
    return _finalise_cacheable_response(request, response, content=content)
