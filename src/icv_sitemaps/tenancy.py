"""Single resolution point for the tenant identifier of a request.

Every call site that needs the tenant ID for the current request (views,
``RedirectMiddleware``) calls ``resolve_tenant_id()`` rather than
reimplementing the resolution and validation of ``ICV_SITEMAPS_TENANT_PREFIX_FUNC``,
so the fail-closed behaviour below cannot drift between call sites.

``ICV_SITEMAPS_TENANT_PREFIX_FUNC`` is the only thing that decides which
tenant's discovery files and sitemaps a request receives. ``""`` is not a
neutral sentinel: it is the single-tenant bucket. A resolver that raises, or
returns a value that is not a safe tenant identifier, has no correct tenant
to serve, so the only defensible behaviour is to refuse by raising
``TenantResolutionError`` rather than silently falling back to ``""``. The
output of the views that key off this function is the crawlable surface of
a site: a wrong-tenant ``robots.txt`` or sitemap served with a 200 is fetched
and indexed by search engines, and that effect outlives the transient
failure that caused it.
"""

from __future__ import annotations

import re

from icv_sitemaps.exceptions import TenantResolutionError

_SAFE_TENANT_ID = re.compile(r"[\w\-]+")


def resolve_tenant_id(request) -> str:
    """Return the tenant identifier for *request*.

    Calls ``ICV_SITEMAPS_TENANT_PREFIX_FUNC`` (a dotted callable path) when
    set, passing the request as the only argument. Falls back to ``""`` for
    single-tenant sites (the setting is unset, or the callable returns a
    falsy value).

    Raises ``TenantResolutionError`` when the callable raises, or returns a
    truthy value that is not a string matching ``[\\w\\-]+``. Callers do not
    catch this to substitute ``""``: see the module docstring for why.
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_TENANT_PREFIX_FUNC

    if not ICV_SITEMAPS_TENANT_PREFIX_FUNC:
        return ""

    try:
        from django.utils.module_loading import import_string

        func = import_string(ICV_SITEMAPS_TENANT_PREFIX_FUNC)
        result = func(request)
    except Exception as exc:
        raise TenantResolutionError(
            f"ICV_SITEMAPS_TENANT_PREFIX_FUNC {ICV_SITEMAPS_TENANT_PREFIX_FUNC!r} raised while "
            f"resolving the tenant for this request."
        ) from exc

    if not result:
        return ""

    if not isinstance(result, str) or not _SAFE_TENANT_ID.fullmatch(result):
        raise TenantResolutionError(
            f"ICV_SITEMAPS_TENANT_PREFIX_FUNC {ICV_SITEMAPS_TENANT_PREFIX_FUNC!r} returned an "
            f"unsafe tenant_id {result!r}; must match [\\w\\-]+."
        )

    return result
