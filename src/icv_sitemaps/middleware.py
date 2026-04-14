"""Redirect middleware for icv-sitemaps.

Evaluates redirect rules on every request when ``ICV_SITEMAPS_REDIRECT_ENABLED``
is ``True``. Add ``"icv_sitemaps.middleware.RedirectMiddleware"`` to your
``MIDDLEWARE`` setting, after any security/WAF middleware and before Django's
``CommonMiddleware``.

Fail-open design: if the database or cache is unavailable, the middleware
passes the request through without interruption.
"""

from __future__ import annotations

import logging
import random
import re

from django.http import (
    HttpResponse,
    HttpResponseGone,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
)

logger = logging.getLogger(__name__)


class RedirectMiddleware:
    """Evaluate redirect rules and track 404s."""

    def __init__(self, get_response):
        self.get_response = get_response
        self._ignore_patterns: list[re.Pattern] | None = None

    def __call__(self, request) -> HttpResponse:
        from icv_sitemaps.conf import ICV_SITEMAPS_REDIRECT_ENABLED

        if not ICV_SITEMAPS_REDIRECT_ENABLED:
            return self.get_response(request)

        # Fail-open: never break the request cycle.
        try:
            rule = self._check_redirect(request)
        except Exception:
            logger.exception("RedirectMiddleware: error checking redirect, passing through.")
            return self.get_response(request)

        if rule is not None:
            return self._serve_redirect(rule, request)

        response = self.get_response(request)

        if response.status_code == 404:
            self._maybe_record_404(request)

        return response

    def _check_redirect(self, request) -> dict | None:
        """Look up a matching redirect rule for this request."""
        from icv_sitemaps.services.redirects import check_redirect

        tenant_id = self._get_tenant_id(request)
        return check_redirect(request.path, tenant_id=tenant_id)

    def _serve_redirect(self, rule: dict, request) -> HttpResponse:
        """Return the appropriate redirect or 410 response."""
        from django.db.models import F
        from django.utils import timezone

        from icv_sitemaps.models.redirects import RedirectRule
        from icv_sitemaps.signals import redirect_matched

        # Increment hit_count atomically.
        RedirectRule.objects.filter(pk=rule["id"]).update(
            hit_count=F("hit_count") + 1,
            last_hit_at=timezone.now(),
        )

        status_code = rule["status_code"]

        redirect_matched.send(
            sender=RedirectRule,
            rule=rule,
            path=request.path,
            status_code=status_code,
        )

        if status_code == 410:
            return HttpResponseGone()

        destination = rule["destination"]
        if rule["preserve_query_string"] and request.META.get("QUERY_STRING"):
            separator = "&" if "?" in destination else "?"
            destination = f"{destination}{separator}{request.META['QUERY_STRING']}"

        if status_code in (301, 308):
            return HttpResponsePermanentRedirect(destination)
        return HttpResponseRedirect(destination)

    def _maybe_record_404(self, request) -> None:
        """Track a 404 response if 404 tracking is enabled."""
        from icv_sitemaps.conf import (
            ICV_SITEMAPS_404_IGNORE_PATTERNS,
            ICV_SITEMAPS_404_TRACKING_ENABLED,
            ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE,
        )

        if not ICV_SITEMAPS_404_TRACKING_ENABLED:
            return

        # Sample rate check.
        if ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE < 1.0 and random.random() > ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE:  # noqa: S311, E501
            return

        path = request.path

        # Check ignore patterns (static assets, etc.).
        if self._ignore_patterns is None:
            self._ignore_patterns = [re.compile(p) for p in ICV_SITEMAPS_404_IGNORE_PATTERNS]
        if any(p.search(path) for p in self._ignore_patterns):
            return

        try:
            from icv_sitemaps.services.redirects import record_404

            tenant_id = self._get_tenant_id(request)
            referrer = request.META.get("HTTP_REFERER", "")
            record_404(path, tenant_id=tenant_id, referrer=referrer)
        except Exception:
            logger.exception("RedirectMiddleware: error recording 404 for %r.", path)

    def _get_tenant_id(self, request) -> str:
        """Resolve tenant ID from the request."""
        from icv_sitemaps.conf import ICV_SITEMAPS_TENANT_PREFIX_FUNC

        if not ICV_SITEMAPS_TENANT_PREFIX_FUNC:
            return ""

        try:
            from django.utils.module_loading import import_string

            func = import_string(ICV_SITEMAPS_TENANT_PREFIX_FUNC)
            result = func(request) or ""
            if result and not re.fullmatch(r"[\w\-]+", result):
                logger.warning(
                    "RedirectMiddleware: tenant func returned unsafe value %r — ignoring.",
                    result,
                )
                return ""
            return result
        except Exception:
            logger.exception("RedirectMiddleware: tenant resolution failed.")
            return ""
