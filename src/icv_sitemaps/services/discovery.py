"""Discovery file service functions (llms.txt, security.txt, humans.txt)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import transaction

if TYPE_CHECKING:
    from icv_sitemaps.models import DiscoveryFileConfig

logger = logging.getLogger(__name__)


def get_discovery_file_content(file_type: str, *, tenant_id: str = "") -> str | None:
    """Return the content of a discovery file.

    Covers ``llms_txt``, ``security_txt``, and ``humans_txt``.

    Args:
        file_type: One of ``"llms_txt"``, ``"security_txt"``, ``"humans_txt"``.
        tenant_id: Tenant identifier.  Empty string for single-tenant use.

    Returns:
        File content string, or ``None`` if no active config exists.
    """
    from icv_sitemaps.models.discovery import DiscoveryFileConfig

    try:
        config = DiscoveryFileConfig.objects.get(
            file_type=file_type,
            tenant_id=tenant_id,
            is_active=True,
        )
    except DiscoveryFileConfig.DoesNotExist:
        return None

    return config.content


def set_discovery_file_content(
    file_type: str,
    content: str,
    *,
    tenant_id: str = "",
    user: Any = None,
) -> DiscoveryFileConfig:
    """Create or update a discovery file's content.

    Uses ``update_or_create`` so the operation is idempotent.  Invalidates
    the discovery file cache for the given tenant after saving.

    Args:
        file_type: One of ``"llms_txt"``, "security_txt"``, ``"humans_txt"``.
        content: Raw content to serve at the file's canonical URL.
        tenant_id: Tenant identifier.
        user: The user performing the update (stored as ``last_modified_by``).

    Returns:
        The created or updated ``DiscoveryFileConfig`` instance.
    """
    from django.core.cache import cache

    from icv_sitemaps.models.discovery import DiscoveryFileConfig

    defaults: dict[str, Any] = {"content": content, "is_active": True}
    if user is not None:
        defaults["last_modified_by"] = user

    with transaction.atomic():
        config, _ = DiscoveryFileConfig.objects.select_for_update().get_or_create(
            file_type=file_type,
            tenant_id=tenant_id,
            defaults=defaults,
        )
        if not _:
            # Existing row — update it within the lock.
            for attr, value in defaults.items():
                setattr(config, attr, value)
            config.save(update_fields=list(defaults.keys()))

    cache_key = f"icv_sitemaps:discovery:{file_type}:{tenant_id}"
    cache.delete(cache_key)

    return config
