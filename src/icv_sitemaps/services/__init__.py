"""Service layer for icv-sitemaps.

All public service functions are re-exported here so consuming code can import
from ``icv_sitemaps.services`` without knowing the internal module layout.
"""

from icv_sitemaps.services.ads import (
    add_ads_entry,
    render_ads_txt,
)
from icv_sitemaps.services.discovery import (
    get_discovery_file_content,
    set_discovery_file_content,
)
from icv_sitemaps.services.generation import (
    generate_all_sections,
    generate_index,
    generate_section,
    get_generation_stats,
    mark_section_stale,
)
from icv_sitemaps.services.ping import ping_search_engines
from icv_sitemaps.services.redirects import (
    add_redirect,
    bulk_import_redirects,
    check_redirect,
    get_top_404s,
    record_404,
)
from icv_sitemaps.services.robots import (
    add_robots_rule,
    get_robots_rules,
    render_robots_txt,
)
from icv_sitemaps.services.sections import (
    create_section,
    delete_section,
)

__all__ = [
    # Generation
    "generate_section",
    "generate_all_sections",
    "generate_index",
    "mark_section_stale",
    "get_generation_stats",
    # Section management
    "create_section",
    "delete_section",
    # Ping
    "ping_search_engines",
    # Robots
    "render_robots_txt",
    "add_robots_rule",
    "get_robots_rules",
    # Ads
    "render_ads_txt",
    "add_ads_entry",
    # Discovery files
    "get_discovery_file_content",
    "set_discovery_file_content",
    # Redirects
    "check_redirect",
    "add_redirect",
    "bulk_import_redirects",
    "record_404",
    "get_top_404s",
]
