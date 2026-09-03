"""Discovery file service functions (llms.txt, security.txt, humans.txt)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.db import transaction

if TYPE_CHECKING:
    from icv_sitemaps.models import DiscoveryFileConfig

logger = logging.getLogger(__name__)


def _validate_security_txt(content: str) -> None:
    """Validate ``content`` against RFC 9116's two mandatory fields.

    RFC 9116 s2.5.3 requires at least one ``Contact`` field. RFC 9116
    s2.5.5 requires exactly one ``Expires`` field, an RFC 3339 timestamp.
    Signing (``Signature``, s2.3) is a SHOULD, not a MUST, and is
    deliberately not validated here.

    Args:
        content: Raw security.txt content to validate.

    Raises:
        ValueError: If no ``Contact`` field is present, if ``Expires`` is
            missing, duplicated, or not a well-formed RFC 3339 timestamp.
    """
    contact_count = 0
    expires_values: list[str] = []

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        field, _sep, value = stripped.partition(":")
        if field == "Contact":
            contact_count += 1
        elif field == "Expires":
            expires_values.append(value.strip())

    if contact_count < 1:
        raise ValueError("security.txt requires at least one 'Contact' field (RFC 9116 s2.5.3).")

    if len(expires_values) != 1:
        raise ValueError(
            f"security.txt requires exactly one 'Expires' field (RFC 9116 s2.5.5), found {len(expires_values)}."
        )

    expires_raw = expires_values[0]
    # datetime.fromisoformat (Python 3.11+) accepts a trailing 'Z' as UTC,
    # which covers the common RFC 3339 form.
    try:
        datetime.fromisoformat(expires_raw)
    except ValueError as exc:
        raise ValueError(
            f"security.txt 'Expires' field must be a valid RFC 3339 timestamp, got: {expires_raw!r}."
        ) from exc


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

    Raises:
        ValueError: If ``file_type`` is ``"security_txt"`` and ``content``
            does not satisfy RFC 9116's mandatory ``Contact`` and
            ``Expires`` fields. ``llms_txt`` and ``humans_txt`` content is
            not validated, as no standard mandates their shape.
    """
    from django.core.cache import cache

    from icv_sitemaps.models.discovery import DiscoveryFileConfig

    if file_type == "security_txt":
        _validate_security_txt(content)

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
