"""Single resolution point for the storage backend icv-sitemaps writes to.

Every storage access in this package (views, tasks, management commands,
generation services) calls ``get_storage()`` rather than importing
``django.core.files.storage.default_storage`` directly, so
``ICV_STORAGES_ALIAS`` (ADR-037) is honoured everywhere consistently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.core.files.storage import Storage


def get_storage() -> Storage:
    """Return the configured storage backend instance.

    Read inside the function body (not at module import time) so this
    responds to ``patch("icv_sitemaps.conf.NAME", ...)`` in tests, matching
    the pattern used throughout ``views.py`` and ``services/``.

    Resolves ``ICV_STORAGES_ALIAS`` into the host project's ``STORAGES``
    setting; an unconfigured alias resolves to ``storages["default"]``, the
    same backend ``default_storage`` proxies, so an unconfigured consumer
    sees no change. ``ICV_SITEMAPS_STORAGE_BACKEND``, deprecated since 3.1.0,
    is removed as of 3.2.0 and is no longer read here.
    """
    from django.core.files.storage import storages

    from icv_sitemaps.conf import ICV_STORAGES_ALIAS

    return storages[ICV_STORAGES_ALIAS]
