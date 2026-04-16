"""
Package-level settings with defaults.

All settings are namespaced under ICV_SITEMAPS_* and accessed via this module.
"""

from django.conf import settings

# Dotted path to Django storage backend for generated files
ICV_SITEMAPS_STORAGE_BACKEND: str = getattr(
    settings, "ICV_SITEMAPS_STORAGE_BACKEND", "django.core.files.storage.default_storage"
)

# Base path within the storage backend for sitemap files
ICV_SITEMAPS_STORAGE_PATH: str = getattr(settings, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/")

# Base URL for sitemap URLs (e.g. "https://example.com"). Required for absolute URLs.
ICV_SITEMAPS_BASE_URL: str = getattr(settings, "ICV_SITEMAPS_BASE_URL", "")

# Maximum URLs per sitemap file (protocol limit: 50,000)
ICV_SITEMAPS_MAX_URLS_PER_FILE: int = getattr(settings, "ICV_SITEMAPS_MAX_URLS_PER_FILE", 50000)

# Maximum sitemap file size in bytes (protocol limit: 50 MB)
ICV_SITEMAPS_MAX_FILE_SIZE_BYTES: int = getattr(settings, "ICV_SITEMAPS_MAX_FILE_SIZE_BYTES", 52428800)

# Queryset iteration batch size during generation
ICV_SITEMAPS_BATCH_SIZE: int = getattr(settings, "ICV_SITEMAPS_BATCH_SIZE", 5000)

# Compress generated sitemap files with gzip
ICV_SITEMAPS_GZIP: bool = getattr(settings, "ICV_SITEMAPS_GZIP", True)

# Use the streaming XML writer to bound per-section memory regardless of
# entry count. When True, entries are serialised directly to a local temp
# file at extraction time instead of accumulated in a list. When False,
# falls back to the buffered builder (ElementTree-style accumulation).
# The streaming writer is the default and recommended for large sections.
ICV_SITEMAPS_STREAMING_WRITER: bool = getattr(settings, "ICV_SITEMAPS_STREAMING_WRITER", True)

# Search engines to ping after regeneration.
# Google and Bing retired their ping endpoints; default is now empty.
ICV_SITEMAPS_PING_ENGINES: list = getattr(settings, "ICV_SITEMAPS_PING_ENGINES", [])

# Enable/disable search engine pinging (disabled by default — most engines
# no longer support the ping protocol).
ICV_SITEMAPS_PING_ENABLED: bool = getattr(settings, "ICV_SITEMAPS_PING_ENABLED", False)

# Auto-register model sections (like ICV_SEARCH_AUTO_INDEX)
ICV_SITEMAPS_AUTO_SECTIONS: dict = getattr(settings, "ICV_SITEMAPS_AUTO_SECTIONS", {})

# Additional raw lines appended to robots.txt
ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES: list = getattr(settings, "ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES", [])

# Override the sitemap URL in robots.txt (auto-detected if empty)
ICV_SITEMAPS_ROBOTS_SITEMAP_URL: str = getattr(settings, "ICV_SITEMAPS_ROBOTS_SITEMAP_URL", "")

# Cache TTL in seconds for rendered discovery files
ICV_SITEMAPS_CACHE_TIMEOUT: int = getattr(settings, "ICV_SITEMAPS_CACHE_TIMEOUT", 3600)

# Dotted path to tenant prefix callable
ICV_SITEMAPS_TENANT_PREFIX_FUNC: str = getattr(settings, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", "")

# Use Celery for background generation
ICV_SITEMAPS_ASYNC_GENERATION: bool = getattr(settings, "ICV_SITEMAPS_ASYNC_GENERATION", True)

# Maximum age for news sitemap entries (Google requires < 2 days)
ICV_SITEMAPS_NEWS_MAX_AGE_DAYS: int = getattr(settings, "ICV_SITEMAPS_NEWS_MAX_AGE_DAYS", 2)

# ---------------------------------------------------------------------------
# Redirect settings
# ---------------------------------------------------------------------------

# Enable redirect middleware evaluation (opt-in)
ICV_SITEMAPS_REDIRECT_ENABLED: bool = getattr(settings, "ICV_SITEMAPS_REDIRECT_ENABLED", False)

# Cache TTL in seconds for redirect rule lookups
ICV_SITEMAPS_REDIRECT_CACHE_TIMEOUT: int = getattr(settings, "ICV_SITEMAPS_REDIRECT_CACHE_TIMEOUT", 300)

# Enable 404 tracking in the redirect middleware
ICV_SITEMAPS_404_TRACKING_ENABLED: bool = getattr(settings, "ICV_SITEMAPS_404_TRACKING_ENABLED", False)

# Fraction of 404s to track (0.0–1.0). Lower values reduce DB writes under load.
ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE: float = getattr(settings, "ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE", 1.0)

# Regex patterns for paths to ignore when tracking 404s (static assets, etc.)
ICV_SITEMAPS_404_IGNORE_PATTERNS: list = getattr(
    settings,
    "ICV_SITEMAPS_404_IGNORE_PATTERNS",
    [r"\.(?:css|js|ico|png|jpg|jpeg|gif|svg|woff2?|ttf|eot|map)$"],
)
