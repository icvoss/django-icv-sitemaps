"""Importable ICV_SITEMAPS_TENANT_PREFIX_FUNC callables for the tenancy tests.

A real dotted path is required because ``resolve_tenant_id()`` resolves the
setting with ``django.utils.module_loading.import_string``, not a mock
injected directly, so the callables need to live somewhere genuinely
importable (mirrors ``tests/gone_resolvers.py``).
"""


def raises(request):
    raise RuntimeError("boom")


def unsafe(request):
    return "tenant/../evil"


def acme(request):
    return "acme"


def none(request):
    return None
