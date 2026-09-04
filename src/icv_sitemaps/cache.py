"""Fail-open wrappers around the ``ICV_CACHES_ALIAS`` cache (ADR-037).

The package treats the configured cache as an optimisation, never a
dependency: every read, write and invalidation the package performs goes
through this module rather than calling ``django.core.cache.cache``
directly, so a backend outage (for example an unreachable Redis with no
``IGNORE_EXCEPTIONS``) degrades the request instead of raising out of a
view, a signal handler, or a service function.

Same fail-open shape as ``middleware.RedirectMiddleware``: catch broadly,
log, and carry on. The three operations are not symmetric, though.

- A failed ``get`` is safe to swallow: the caller regenerates the content.
- A failed ``set`` is safe to swallow: the value simply is not cached.
- A failed ``delete`` is not safe to swallow silently. It leaves stale
  content being served for up to the cache timeout after the database
  record it was keyed on has already changed, which is a correctness
  problem, not a performance one. It is logged at ``WARNING`` rather than
  ``DEBUG``, naming the key, so an operator can find and manually evict it.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def safe_get(cache_key: str, default: Any = None) -> Any:
    """Return ``cache.get(cache_key)``, or *default* if the backend raises."""
    from django.core.cache import caches

    from icv_sitemaps.conf import ICV_CACHES_ALIAS

    try:
        return caches[ICV_CACHES_ALIAS].get(cache_key, default)
    except Exception:
        logger.exception("icv_sitemaps: cache backend raised on get(%r), treating as a cache miss.", cache_key)
        return default


def safe_set(cache_key: str, value: Any, timeout: int | None = None) -> None:
    """Call ``cache.set(cache_key, value, timeout)``, swallowing backend errors."""
    from django.core.cache import caches

    from icv_sitemaps.conf import ICV_CACHES_ALIAS

    try:
        caches[ICV_CACHES_ALIAS].set(cache_key, value, timeout)
    except Exception:
        logger.exception("icv_sitemaps: cache backend raised on set(%r), value will not be cached.", cache_key)


def safe_delete(cache_key: str) -> None:
    """Call ``cache.delete(cache_key)``, logging (not swallowing quietly) on failure.

    A failed delete leaves stale content in the cache for up to its
    timeout, which is a correctness problem: this is logged at ``WARNING``
    with the key, not at ``DEBUG``, so it is visible to normal log
    monitoring rather than only to someone debugging with verbose logging
    enabled.
    """
    from django.core.cache import caches

    from icv_sitemaps.conf import ICV_CACHES_ALIAS

    try:
        caches[ICV_CACHES_ALIAS].delete(cache_key)
    except Exception:
        logger.warning(
            "icv_sitemaps: cache backend raised on delete(%r); stale content may be served for up to the "
            "configured cache timeout.",
            cache_key,
            exc_info=True,
        )
