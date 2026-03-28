"""Tests for auto-section signal wiring (icv_sitemaps.auto_sections)."""

from unittest.mock import patch

from icv_sitemaps.auto_sections import (
    _connected_signals,
    connect_auto_section_signals,
    disconnect_auto_section_signals,
)
from icv_sitemaps.testing.factories import SitemapSectionFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_registry():
    """Remove all entries from the module-level signal registry."""
    _connected_signals.clear()


# ---------------------------------------------------------------------------
# connect_auto_section_signals
# ---------------------------------------------------------------------------


class TestConnectAutoSectionSignals:
    def teardown_method(self, method):
        """Disconnect all auto-section signals after each test."""
        disconnect_auto_section_signals()
        _clear_registry()

    def test_connects_post_save_for_configured_model(self, settings):
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
            }
        }

        connect_auto_section_signals()

        save_uid = "icv_sitemaps_auto_save_articles"
        # Verify the handler is registered by checking the registry
        assert save_uid in _connected_signals

    def test_connects_post_delete_for_configured_model(self, settings):
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
            }
        }

        connect_auto_section_signals()

        delete_uid = "icv_sitemaps_auto_delete_articles"
        assert delete_uid in _connected_signals

    def test_saving_model_marks_section_stale(self, db, settings):
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
            }
        }

        SitemapSectionFactory(name="articles", is_stale=False)
        connect_auto_section_signals()

        with patch("icv_sitemaps.auto_sections._handle_post_save") as mock_handler:
            # Trigger post_save by saving a model instance
            from sitemaps_testapp.models import Article

            Article.objects.create(
                title="Auto Signal Test",
                slug="auto-signal-test",
                is_published=True,
            )

        # Handler was called — verify via mock
        mock_handler.assert_called()

    def test_saving_model_calls_mark_section_stale(self, db, settings):
        """post_save on a configured model calls mark_section_stale for its section."""
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
            }
        }

        SitemapSectionFactory(name="articles", is_stale=False)
        connect_auto_section_signals()

        with patch("icv_sitemaps.services.generation.mark_section_stale") as mock_mark_stale:
            from sitemaps_testapp.models import Article

            Article.objects.create(
                title="Mark Stale Test",
                slug="mark-stale-test",
                is_published=True,
            )

        mock_mark_stale.assert_called_with("articles", tenant_id="")

    def test_deleting_model_calls_mark_section_stale(self, db, settings):
        """post_delete on a configured model calls mark_section_stale."""
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
            }
        }

        SitemapSectionFactory(name="articles", is_stale=False)
        connect_auto_section_signals()

        from sitemaps_testapp.models import Article

        article = Article.objects.create(
            title="Delete Test",
            slug="delete-signal-test",
            is_published=True,
        )

        with patch("icv_sitemaps.services.generation.mark_section_stale") as mock_mark_stale:
            article.delete()

        mock_mark_stale.assert_called_with("articles", tenant_id="")

    def test_idempotent_connecting_does_not_duplicate_handlers(self, settings):
        """Calling connect_auto_section_signals twice registers handlers only once."""
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
            }
        }

        connect_auto_section_signals()
        connect_auto_section_signals()

        # dispatch_uid means duplicates are replaced, not appended — registry
        # should still show exactly one entry per signal/section combination.
        save_uid = "icv_sitemaps_auto_save_articles"
        delete_uid = "icv_sitemaps_auto_delete_articles"

        # Count occurrences in registry keys — must be exactly 1 each
        save_count = sum(1 for k in _connected_signals if k == save_uid)
        delete_count = sum(1 for k in _connected_signals if k == delete_uid)

        assert save_count == 1
        assert delete_count == 1

    def test_missing_model_key_logs_warning_and_skips(self, settings, caplog):
        """A section config without a 'model' key is skipped with a warning."""
        import logging

        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "no-model-section": {
                "sitemap_type": "standard",
                # 'model' key intentionally omitted
            }
        }

        with caplog.at_level(logging.WARNING, logger="icv_sitemaps.auto_sections"):
            connect_auto_section_signals()

        assert "missing 'model' key" in caplog.text

        # No handlers registered for this section
        assert "icv_sitemaps_auto_save_no-model-section" not in _connected_signals

    def test_invalid_model_path_logs_warning_and_skips(self, settings, caplog):
        """An unresolvable model path is skipped with a warning."""
        import logging

        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "bad-model-section": {
                "model": "nonexistent.DoesNotExist",
            }
        }

        with caplog.at_level(logging.WARNING, logger="icv_sitemaps.auto_sections"):
            connect_auto_section_signals()

        assert "could not resolve model" in caplog.text

        assert "icv_sitemaps_auto_save_bad-model-section" not in _connected_signals

    def test_empty_auto_sections_connects_nothing(self, settings):
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {}

        initial_registry_size = len(_connected_signals)
        connect_auto_section_signals()

        assert len(_connected_signals) == initial_registry_size

    def test_tenant_id_propagated_to_handler(self, db, settings):
        """Tenant ID from config is forwarded to mark_section_stale."""
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
                "tenant_id": "acme",
            }
        }

        connect_auto_section_signals()

        with patch("icv_sitemaps.services.generation.mark_section_stale") as mock_mark_stale:
            from sitemaps_testapp.models import Article

            Article.objects.create(
                title="Tenant Test",
                slug="tenant-auto-test",
                is_published=True,
            )

        mock_mark_stale.assert_called_with("articles", tenant_id="acme")

    def test_on_save_false_does_not_connect_post_save(self, settings):
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
                "on_save": False,
                "on_delete": True,
            }
        }

        connect_auto_section_signals()

        # post_save should NOT be registered
        assert "icv_sitemaps_auto_save_articles" not in _connected_signals
        # post_delete SHOULD be registered
        assert "icv_sitemaps_auto_delete_articles" in _connected_signals

    def test_on_delete_false_does_not_connect_post_delete(self, settings):
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
                "on_save": True,
                "on_delete": False,
            }
        }

        connect_auto_section_signals()

        # post_save SHOULD be registered
        assert "icv_sitemaps_auto_save_articles" in _connected_signals
        # post_delete should NOT be registered
        assert "icv_sitemaps_auto_delete_articles" not in _connected_signals


# ---------------------------------------------------------------------------
# disconnect_auto_section_signals
# ---------------------------------------------------------------------------


class TestDisconnectAutoSectionSignals:
    def teardown_method(self, method):
        disconnect_auto_section_signals()
        _clear_registry()

    def test_disconnect_all_clears_registry(self, settings):
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
            }
        }

        connect_auto_section_signals()
        assert len(_connected_signals) > 0

        disconnect_auto_section_signals()

        assert len(_connected_signals) == 0

    def test_disconnect_specific_section_by_name(self, settings):
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
            }
        }

        connect_auto_section_signals()

        disconnect_auto_section_signals(section_names=["articles"])

        assert "icv_sitemaps_auto_save_articles" not in _connected_signals
        assert "icv_sitemaps_auto_delete_articles" not in _connected_signals

    def test_disconnect_is_idempotent(self, settings):
        """Calling disconnect when nothing is connected does not raise."""
        # Registry should already be empty from teardown
        disconnect_auto_section_signals()  # Should not raise

    def test_after_disconnect_save_does_not_call_mark_stale(self, db, settings):
        """Once disconnected, saving a model no longer triggers mark_section_stale."""
        settings.ICV_SITEMAPS_AUTO_SECTIONS = {
            "articles": {
                "model": "sitemaps_testapp.Article",
            }
        }

        connect_auto_section_signals()
        disconnect_auto_section_signals()

        with patch("icv_sitemaps.services.generation.mark_section_stale") as mock_mark_stale:
            from sitemaps_testapp.models import Article

            Article.objects.create(
                title="Post-Disconnect Test",
                slug="post-disconnect-test",
                is_published=True,
            )

        mock_mark_stale.assert_not_called()
