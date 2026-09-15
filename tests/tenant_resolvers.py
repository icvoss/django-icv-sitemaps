"""Importable ICV_SITEMAPS_TENANT_PREFIX_FUNC callables for the tenancy tests.

A real dotted path is required because ``resolve_tenant_id()`` resolves the
setting with ``django.utils.module_loading.import_string``, not a mock
injected directly, so the callables need to live somewhere genuinely
importable (mirrors ``tests/gone_resolvers.py``).
"""

from contextlib import contextmanager
from contextvars import ContextVar

rls_context_active: ContextVar[bool] = ContextVar("rls_context_active", default=False)


@contextmanager
def queryset_context(section):
    """Test-only RLS context selected through ICV_SITEMAPS_QUERYSET_CONTEXT."""
    token = rls_context_active.set(True)
    try:
        yield
    finally:
        rls_context_active.reset(token)


def raises_queryset_context(section):
    """Test that context-factory failures retain generation's normal error path."""
    raise RuntimeError("queryset context failed")


def raises(request):
    raise RuntimeError("boom")


def unsafe(request):
    return "tenant/../evil"


def acme(request):
    return "acme"


def none(request):
    return None
