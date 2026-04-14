"""Exception classes for icv-sitemaps."""


class IcvSitemapsError(Exception):
    """Base exception for all icv-sitemaps errors."""


class SitemapGenerationError(IcvSitemapsError):
    """Raised when sitemap generation fails."""


class StorageError(IcvSitemapsError):
    """Raised when storage operations fail."""


class PingError(IcvSitemapsError):
    """Raised when search engine ping fails."""


class RedirectError(IcvSitemapsError):
    """Raised when redirect operations fail."""
