"""Importable ICV_SITEMAPS_GONE_RESOLVER callables for test_middleware.py.

A real dotted path is required because the middleware resolves the setting
with ``django.utils.module_loading.import_string``, not a mock injected
directly, so the callables need to live somewhere genuinely importable.
"""


def always_gone(request):
    return 410


def never_gone(request):
    return None


def raises(request):
    raise RuntimeError("boom")


def returns_404(request):
    return 404
