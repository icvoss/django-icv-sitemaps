"""Regression tests for issue #60.

``_iter_section_entries()`` must never call ``close_old_connections()``
while the queryset's connection is inside an atomic block it does not own,
and must only call it on the same ``_GC_INTERVAL`` cadence as the periodic
``gc.collect()`` pass.

``tests/settings.py`` uses an in-memory sqlite database, whose
``connection.close()`` is a no-op for that backend, so the closed-connection
symptom from the issue (every later query in the transaction raising
``OperationalError``) is not directly observable here. The only observable
in this test module is *whether ``close_old_connections()`` is called at
all*, and how many times, which is exactly the discriminator the fix
changes: patched via ``django.db.close_old_connections`` (the name looked
up function-locally inside ``_iter_section_entries``, not a name imported
into the ``generation`` module).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.db import connection

from icv_sitemaps.services.generation import _GC_INTERVAL, _iter_section_entries
from sitemaps_testapp.models import Article


def _make_articles(count: int) -> None:
    for i in range(count):
        Article.objects.create(title=f"Article {i}", slug=f"article-{i}")


def _drain(**kwargs) -> None:
    """Exhaust the generator fully; the close-connection call happens per chunk."""
    for _ in _iter_section_entries(**kwargs):
        pass


def _iter_kwargs(*, batch_size: int) -> dict:
    return {
        "queryset": Article.objects.all(),
        "section": None,
        "sitemap_type": "standard",
        "base_url_setting": "https://example.com",
        "cutoff": None,
        "model_class": Article,
        "batch_size": batch_size,
    }


@pytest.mark.django_db
def test_never_closes_connection_inside_caller_owned_transaction(db):
    """The plain ``db`` fixture wraps the test body in one outer atomic() block.

    This is the exact shape of the issue: pytest-django's per-test
    transaction must survive generation untouched.
    """
    assert connection.in_atomic_block is True

    _make_articles(25)

    with patch("django.db.close_old_connections") as spy:
        _drain(**_iter_kwargs(batch_size=1))

    spy.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_closes_connection_periodically_outside_a_transaction():
    """Outside any wrapping transaction, the periodic refresh does fire.

    25 rows at batch_size=1 makes 25 chunks; the refresh is gated on the
    same ``_GC_INTERVAL`` cadence as ``gc.collect()``, so it fires
    ``25 // _GC_INTERVAL`` times.
    """
    assert connection.in_atomic_block is False

    _make_articles(25)

    with patch("django.db.close_old_connections") as spy:
        _drain(**_iter_kwargs(batch_size=1))

    expected_calls = 25 // _GC_INTERVAL
    assert spy.call_count == expected_calls


@pytest.mark.django_db(transaction=True)
def test_never_closes_connection_below_the_gc_interval():
    """Below one full _GC_INTERVAL of chunks, the refresh never fires."""
    assert connection.in_atomic_block is False

    row_count = 5
    assert row_count < _GC_INTERVAL

    _make_articles(row_count)

    with patch("django.db.close_old_connections") as spy:
        _drain(**_iter_kwargs(batch_size=1))

    spy.assert_not_called()
