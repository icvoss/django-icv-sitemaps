"""Signal handlers for icv-sitemaps.

Connects post_save/post_delete signals on discovery file models to invalidate
their caches (BR-031), ensuring that views always serve fresh content after
database changes.

Connected automatically in ``IcvSitemapsConfig.ready()`` via
``from . import handlers``.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RobotsRule — invalidate robots.txt cache
# ---------------------------------------------------------------------------


@receiver(post_save, sender="icv_sitemaps.RobotsRule")
def on_robots_rule_save(sender, instance, **kwargs) -> None:
    """Invalidate the robots.txt cache when a rule is saved."""
    cache_key = f"icv_sitemaps:robots_txt:{instance.tenant_id}"
    cache.delete(cache_key)
    logger.debug("Invalidated robots.txt cache for tenant %r.", instance.tenant_id)


@receiver(post_delete, sender="icv_sitemaps.RobotsRule")
def on_robots_rule_delete(sender, instance, **kwargs) -> None:
    """Invalidate the robots.txt cache when a rule is deleted."""
    cache_key = f"icv_sitemaps:robots_txt:{instance.tenant_id}"
    cache.delete(cache_key)
    logger.debug("Invalidated robots.txt cache for tenant %r (rule deleted).", instance.tenant_id)


# ---------------------------------------------------------------------------
# AdsEntry — invalidate ads.txt and app-ads.txt caches
# ---------------------------------------------------------------------------


@receiver(post_save, sender="icv_sitemaps.AdsEntry")
def on_ads_entry_save(sender, instance, **kwargs) -> None:
    """Invalidate the ads.txt or app-ads.txt cache when an entry is saved."""
    if instance.is_app_ads:
        cache_key = f"icv_sitemaps:app_ads_txt:{instance.tenant_id}"
    else:
        cache_key = f"icv_sitemaps:ads_txt:{instance.tenant_id}"
    cache.delete(cache_key)
    logger.debug(
        "Invalidated %s cache for tenant %r.",
        "app-ads.txt" if instance.is_app_ads else "ads.txt",
        instance.tenant_id,
    )


@receiver(post_delete, sender="icv_sitemaps.AdsEntry")
def on_ads_entry_delete(sender, instance, **kwargs) -> None:
    """Invalidate the ads.txt or app-ads.txt cache when an entry is deleted."""
    if instance.is_app_ads:
        cache_key = f"icv_sitemaps:app_ads_txt:{instance.tenant_id}"
    else:
        cache_key = f"icv_sitemaps:ads_txt:{instance.tenant_id}"
    cache.delete(cache_key)
    logger.debug(
        "Invalidated %s cache for tenant %r (entry deleted).",
        "app-ads.txt" if instance.is_app_ads else "ads.txt",
        instance.tenant_id,
    )


# ---------------------------------------------------------------------------
# DiscoveryFileConfig — invalidate per-file-type caches
# ---------------------------------------------------------------------------


@receiver(post_save, sender="icv_sitemaps.DiscoveryFileConfig")
def on_discovery_config_save(sender, instance, **kwargs) -> None:
    """Invalidate the discovery file cache when its config is saved."""
    cache_key = f"icv_sitemaps:discovery:{instance.file_type}:{instance.tenant_id}"
    cache.delete(cache_key)
    logger.debug(
        "Invalidated %s cache for tenant %r.",
        instance.file_type,
        instance.tenant_id,
    )


@receiver(post_delete, sender="icv_sitemaps.DiscoveryFileConfig")
def on_discovery_config_delete(sender, instance, **kwargs) -> None:
    """Invalidate the discovery file cache when its config is deleted."""
    cache_key = f"icv_sitemaps:discovery:{instance.file_type}:{instance.tenant_id}"
    cache.delete(cache_key)
    logger.debug(
        "Invalidated %s cache for tenant %r (config deleted).",
        instance.file_type,
        instance.tenant_id,
    )
