"""Automatic sitemap section staleness tracking via ICV_SITEMAPS_AUTO_SECTIONS.

When ``ICV_SITEMAPS_AUTO_SECTIONS`` is configured in Django settings, this
module connects ``post_save`` and ``post_delete`` signals on each listed model
so that the corresponding ``SitemapSection`` is marked stale whenever data
changes.  Signal connection is idempotent — each handler uses a ``dispatch_uid``
so calling ``connect_auto_section_signals()`` multiple times (e.g. during
tests with ``override_settings``) will replace rather than duplicate handlers.

Mirrors the pattern established by ``icv_search.auto_index``.
"""

from __future__ import annotations

import logging
from typing import Any

from django.apps import apps
from django.db.models.signals import post_delete, post_save

logger = logging.getLogger(__name__)

# Registry of currently-connected signal handlers.
# Maps dispatch_uid → model class so the correct sender can be passed on
# disconnect (Django requires sender when connect() was called with a sender).
_connected_signals: dict[str, type] = {}


def _get_auto_sections_config() -> dict[str, dict[str, Any]]:
    """Read ``ICV_SITEMAPS_AUTO_SECTIONS`` from Django settings."""
    from django.conf import settings

    return getattr(settings, "ICV_SITEMAPS_AUTO_SECTIONS", {})


def _handle_post_save(
    sender: type,
    instance: Any,
    section_name: str,
    tenant_id: str,
    **kwargs: Any,
) -> None:
    """Post-save handler: mark the section stale when a model instance is saved."""
    from icv_sitemaps.services.generation import mark_section_stale

    try:
        mark_section_stale(section_name, tenant_id=tenant_id)
        logger.debug(
            "auto_sections: marked section %r stale after %s save (pk=%s).",
            section_name,
            sender.__name__,
            instance.pk,
        )
    except Exception:
        logger.exception(
            "auto_sections: error marking section %r stale after %s save.",
            section_name,
            sender.__name__,
        )


def _handle_post_delete(
    sender: type,
    instance: Any,
    section_name: str,
    tenant_id: str,
    **kwargs: Any,
) -> None:
    """Post-delete handler: mark the section stale when a model instance is deleted."""
    from icv_sitemaps.services.generation import mark_section_stale

    try:
        mark_section_stale(section_name, tenant_id=tenant_id)
        logger.debug(
            "auto_sections: marked section %r stale after %s delete (pk=%s).",
            section_name,
            sender.__name__,
            instance.pk,
        )
    except Exception:
        logger.exception(
            "auto_sections: error marking section %r stale after %s delete.",
            section_name,
            sender.__name__,
        )


def _disconnect_signal(signal, dispatch_uid: str) -> bool:
    """Disconnect a signal receiver by dispatch_uid, using the registry sender.

    Django requires the ``sender`` when the signal was connected with one.
    We look up the sender from ``_connected_signals`` to supply it here.

    Args:
        signal: The Django signal instance (``post_save`` or ``post_delete``).
        dispatch_uid: The dispatch UID used when connecting the receiver.

    Returns:
        ``True`` if the receiver was disconnected; ``False`` otherwise.
    """
    sender = _connected_signals.get(dispatch_uid)
    disconnected = signal.disconnect(sender=sender, dispatch_uid=dispatch_uid)
    if disconnected:
        _connected_signals.pop(dispatch_uid, None)
    return disconnected


def disconnect_auto_section_signals(section_names: list[str] | None = None) -> None:
    """Disconnect auto-section signals for the given names (or all registered).

    Useful in tests when ``override_settings`` changes the config and you need
    to clear previously-connected handlers before connecting fresh ones.

    Args:
        section_names: Specific section names to disconnect.  When ``None``,
            disconnects all entries currently tracked in the registry.
    """
    if section_names is None:
        uids = list(_connected_signals.keys())
        for uid in uids:
            if uid.startswith("icv_sitemaps_auto_save_"):
                _disconnect_signal(post_save, uid)
            else:
                _disconnect_signal(post_delete, uid)
        return

    for section_name in section_names:
        save_uid = f"icv_sitemaps_auto_save_{section_name}"
        delete_uid = f"icv_sitemaps_auto_delete_{section_name}"
        _disconnect_signal(post_save, save_uid)
        _disconnect_signal(post_delete, delete_uid)


def connect_auto_section_signals() -> None:
    """Connect post_save/post_delete signals for all models in ``ICV_SITEMAPS_AUTO_SECTIONS``.

    Called from ``IcvSitemapsConfig.ready()``.  Only connects signals for
    models that are explicitly configured — no global signal hookup.

    Uses ``dispatch_uid`` on every connection so this function is idempotent;
    calling it multiple times (e.g. during test runs with ``override_settings``)
    will replace existing handlers rather than duplicate them.

    When ``on_save`` or ``on_delete`` is ``False`` for a section, any
    previously-registered handler for that signal/section combination is
    explicitly disconnected to prevent stale handlers from prior configurations.
    """
    config = _get_auto_sections_config()
    if not config:
        return

    for section_name, section_config in config.items():
        model_path = section_config.get("model")
        if not model_path:
            logger.warning(
                "ICV_SITEMAPS_AUTO_SECTIONS[%r] missing 'model' key — skipping.",
                section_name,
            )
            continue

        # Resolve model class — accepts "app_label.ModelName" format
        try:
            parts = model_path.rsplit(".", 1)
            if len(parts) != 2:
                raise ValueError(f"Expected 'app_label.ModelName', got: {model_path!r}")
            model_class = apps.get_model(parts[0], parts[1])
        except (LookupError, ValueError):
            logger.warning(
                "ICV_SITEMAPS_AUTO_SECTIONS[%r]: could not resolve model %r — skipping.",
                section_name,
                model_path,
            )
            continue

        # Extract tenant_id from config (defaults to "")
        tenant_id = section_config.get("tenant_id", "")

        save_uid = f"icv_sitemaps_auto_save_{section_name}"
        delete_uid = f"icv_sitemaps_auto_delete_{section_name}"

        # Connect post_save when on_save=True (default)
        if section_config.get("on_save", True):

            def make_save_handler(sname: str, tid: str):
                def handler(sender: type, instance: Any, **kwargs: Any) -> None:
                    _handle_post_save(sender, instance, section_name=sname, tenant_id=tid, **kwargs)

                return handler

            post_save.connect(
                make_save_handler(section_name, tenant_id),
                sender=model_class,
                weak=False,
                dispatch_uid=save_uid,
            )
            _connected_signals[save_uid] = model_class
        else:
            # Explicitly disconnect any stale handler from a prior config
            _disconnect_signal(post_save, save_uid)

        # Connect post_delete when on_delete=True (default)
        if section_config.get("on_delete", True):

            def make_delete_handler(sname: str, tid: str):
                def handler(sender: type, instance: Any, **kwargs: Any) -> None:
                    _handle_post_delete(sender, instance, section_name=sname, tenant_id=tid, **kwargs)

                return handler

            post_delete.connect(
                make_delete_handler(section_name, tenant_id),
                sender=model_class,
                weak=False,
                dispatch_uid=delete_uid,
            )
            _connected_signals[delete_uid] = model_class
        else:
            _disconnect_signal(post_delete, delete_uid)

        logger.info(
            "auto_sections: connected signals for section %r → %s (save=%s, delete=%s).",
            section_name,
            model_path,
            section_config.get("on_save", True),
            section_config.get("on_delete", True),
        )
