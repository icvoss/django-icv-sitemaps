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

    ``ICV_SITEMAPS_STORAGE_BACKEND`` is deprecated (icv_sitemaps.W002) but
    still honoured when set to anything other than its default sentinel,
    for one minor version. Otherwise resolves ``ICV_STORAGES_ALIAS`` into
    the host project's ``STORAGES`` setting; an unconfigured alias resolves
    to ``storages["default"]``, the same backend ``default_storage`` proxies,
    so an unconfigured consumer sees no change.
    """
    from django.core.exceptions import ImproperlyConfigured
    from django.core.files.storage import Storage, storages
    from django.utils.module_loading import import_string

    from icv_sitemaps.conf import ICV_SITEMAPS_STORAGE_BACKEND, ICV_STORAGES_ALIAS

    backend_path = ICV_SITEMAPS_STORAGE_BACKEND
    if backend_path != "django.core.files.storage.default_storage":
        StorageClass = import_string(backend_path)
        if not (isinstance(StorageClass, type) and issubclass(StorageClass, Storage)):
            raise ImproperlyConfigured(
                f"ICV_SITEMAPS_STORAGE_BACKEND {backend_path!r} is not a Django Storage subclass."
            )
        return StorageClass()

    return storages[ICV_STORAGES_ALIAS]
