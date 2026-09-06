"""Pins the public exception surface of ``icv_sitemaps.exceptions`` (#67).

``PingError`` and ``RedirectError`` were declared but never raised anywhere
in ``src/`` and have been removed. This test asserts the exact set of
exception classes the module defines, so a class cannot be reintroduced (or
a new one added) without a deliberate update to the expected list here.
"""

import inspect

from icv_sitemaps import exceptions

EXPECTED_EXCEPTION_NAMES = {
    "IcvSitemapsError",
    "SitemapGenerationError",
    "StorageError",
    "TenantResolutionError",
}


class TestExceptionSurface:
    def test_declared_exceptions_match_expected_set(self):
        declared_names = {
            name
            for name, obj in vars(exceptions).items()
            if inspect.isclass(obj) and obj.__module__ == exceptions.__name__
        }

        assert declared_names == EXPECTED_EXCEPTION_NAMES

    def test_all_declared_exceptions_derive_from_the_common_base(self):
        for name in EXPECTED_EXCEPTION_NAMES - {"IcvSitemapsError"}:
            exception_class = getattr(exceptions, name)
            assert issubclass(exception_class, exceptions.IcvSitemapsError)
