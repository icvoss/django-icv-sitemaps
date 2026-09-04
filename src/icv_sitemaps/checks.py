"""Django system checks for icv-sitemaps (#34).

``ICV_SITEMAPS_BASE_URL`` defaults to an empty string, and sitemap ``<loc>``
elements must be absolute URLs. An empty base URL is silently tolerated by
``generate_index`` (it emits a root-relative path, which is not a valid
sitemap entry) while ``ping_search_engines`` and the ``icv_sitemaps_ping``
management command both already surface the problem on their own paths. This
check surfaces it at startup too, on every ``manage.py`` invocation.

Severity is ``Warning``, not ``Error``: the setting is genuinely optional for
a consumer who only uses robots.txt or ads.txt and never generates a
sitemap. Raising an ``Error`` here would break ``manage.py`` outright for
that consumer. Do not gate severity on whether a ``SitemapSection`` is
configured: system checks run before the app registry and database are
reliably available, and a check that queries the database is a well-known
source of startup breakage during migrations, fresh installs and
``collectstatic``.
"""

from __future__ import annotations

from django.core.checks import Warning as CheckWarning
from django.core.checks import register


@register()
def check_base_url_configured(app_configs, **kwargs):
    """Warn when ``ICV_SITEMAPS_BASE_URL`` is empty.

    Read inside the function body (not at module import time) so the check
    responds to ``patch("icv_sitemaps.conf.ICV_SITEMAPS_BASE_URL", ...)`` in
    tests, matching the pattern used throughout ``views.py`` and
    ``services/``.
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_BASE_URL

    if ICV_SITEMAPS_BASE_URL:
        return []

    return [
        CheckWarning(
            "ICV_SITEMAPS_BASE_URL is not set.",
            hint=(
                "Sitemap <loc> elements will be emitted as root-relative paths "
                "instead of absolute URLs, which is invalid per the sitemap "
                "protocol and will be rejected by search engines. Set "
                'ICV_SITEMAPS_BASE_URL = "https://example.com" in your settings. '
                "If this project only serves robots.txt or ads.txt and never "
                "generates a sitemap, this warning can be ignored."
            ),
            id="icv_sitemaps.W001",
        )
    ]


@register()
def check_storage_backend_deprecated(app_configs, **kwargs):
    """Warn when the deprecated ``ICV_SITEMAPS_STORAGE_BACKEND`` is set (ADR-037).

    Read inside the function body (not at module import time), same reason
    as ``check_base_url_configured`` above.
    """
    from icv_sitemaps.conf import ICV_SITEMAPS_STORAGE_BACKEND

    if ICV_SITEMAPS_STORAGE_BACKEND == "django.core.files.storage.default_storage":
        return []

    return [
        CheckWarning(
            "ICV_SITEMAPS_STORAGE_BACKEND is deprecated.",
            hint=(
                "Configure a STORAGES alias for icv-sitemaps and point "
                "ICV_STORAGES_ALIAS at it instead, for example "
                'ICV_STORAGES_ALIAS = "sitemaps" with a matching entry in '
                "your STORAGES setting. ICV_SITEMAPS_STORAGE_BACKEND is "
                "removed in the next minor release."
            ),
            id="icv_sitemaps.W002",
        )
    ]
