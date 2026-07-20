"""Test utility functions for static section url_provider tests.

These are importable at runtime (not just during pytest) and are called
by tests via the import_string path: tests.test_url_providers.function_name
"""


def marketing_urls():
    """Dummy url_provider callable used by tests."""
    return [
        {"loc": "/pricing/", "changefreq": "weekly", "priority": 0.8},
        {"loc": "/about/"},
    ]


def marketing_urls_single():
    """Single URL provider for precedence tests."""
    return [{"loc": "/callable-page/"}]
