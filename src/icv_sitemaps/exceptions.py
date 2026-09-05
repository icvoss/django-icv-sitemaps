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


class TenantResolutionError(IcvSitemapsError):
    """Raised when ``ICV_SITEMAPS_TENANT_PREFIX_FUNC`` cannot resolve a tenant.

    Raised when the configured callable itself raises, or when it returns a
    truthy value that does not match ``[\\w\\-]+``. Views let this propagate
    as Django's 500: a resolver that cannot tell which tenant is asking has
    no correct tenant's files to serve, so it must refuse rather than fall
    back to the single-tenant (``""``) bucket. The middleware never lets
    this reach a caller: it is caught by the existing outer ``except``
    blocks around redirect checking and 404 recording, which pass the
    request through.
    """
