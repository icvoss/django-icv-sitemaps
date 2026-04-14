"""Tests for RedirectMiddleware."""

from unittest.mock import patch

import pytest
from django.test import RequestFactory

import icv_sitemaps.conf as conf_mod
from icv_sitemaps.middleware import RedirectMiddleware
from icv_sitemaps.testing.factories import RedirectRuleFactory


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def make_middleware():
    """Create a RedirectMiddleware with a configurable get_response."""

    def _make(status_code=200):
        from django.http import HttpResponse

        def get_response(request):
            return HttpResponse(status=status_code)

        return RedirectMiddleware(get_response)

    return _make


@pytest.fixture(autouse=True)
def _enable_redirects():
    """Enable redirect middleware for all tests in this module."""
    with patch.object(conf_mod, "ICV_SITEMAPS_REDIRECT_ENABLED", True):
        yield


class TestRedirectMiddleware:
    def test_passes_through_when_disabled(self, rf, make_middleware):
        with patch.object(conf_mod, "ICV_SITEMAPS_REDIRECT_ENABLED", False):
            middleware = make_middleware()
            request = rf.get("/anything/")
            response = middleware(request)
            assert response.status_code == 200

    def test_exact_match_301(self, db, rf, make_middleware):
        RedirectRuleFactory(source_pattern="/old/", destination="/new/", status_code=301)

        middleware = make_middleware()
        request = rf.get("/old/")
        response = middleware(request)

        assert response.status_code == 301
        assert response["Location"] == "/new/"

    def test_exact_match_302(self, db, rf, make_middleware):
        RedirectRuleFactory(source_pattern="/temp/", destination="/dest/", status_code=302)

        middleware = make_middleware()
        request = rf.get("/temp/")
        response = middleware(request)

        assert response.status_code == 302
        assert response["Location"] == "/dest/"

    def test_410_gone(self, db, rf, make_middleware):
        RedirectRuleFactory(source_pattern="/removed/", destination="", status_code=410)

        middleware = make_middleware()
        request = rf.get("/removed/")
        response = middleware(request)

        assert response.status_code == 410

    def test_no_match_passes_through(self, db, rf, make_middleware):
        middleware = make_middleware()
        request = rf.get("/normal-page/")
        response = middleware(request)

        assert response.status_code == 200

    def test_preserves_query_string(self, db, rf, make_middleware):
        RedirectRuleFactory(
            source_pattern="/old/",
            destination="/new/",
            status_code=301,
            preserve_query_string=True,
        )

        middleware = make_middleware()
        request = rf.get("/old/?page=2&sort=name")
        response = middleware(request)

        assert response.status_code == 301
        assert "page=2" in response["Location"]
        assert "sort=name" in response["Location"]

    def test_does_not_preserve_query_string_when_disabled(self, db, rf, make_middleware):
        RedirectRuleFactory(
            source_pattern="/old/",
            destination="/new/",
            status_code=301,
            preserve_query_string=False,
        )

        middleware = make_middleware()
        request = rf.get("/old/?page=2")
        response = middleware(request)

        assert response["Location"] == "/new/"

    def test_increments_hit_count(self, db, rf, make_middleware):
        rule = RedirectRuleFactory(source_pattern="/counted/", destination="/dest/")

        middleware = make_middleware()
        request = rf.get("/counted/")
        middleware(request)

        rule.refresh_from_db()
        assert rule.hit_count == 1

    def test_priority_ordering(self, db, rf, make_middleware):
        RedirectRuleFactory(
            source_pattern="/path/",
            destination="/low-priority/",
            status_code=301,
            priority=10,
        )
        RedirectRuleFactory(
            source_pattern="/path/",
            destination="/high-priority/",
            status_code=302,
            priority=1,
            match_type="prefix",
        )

        middleware = make_middleware()
        request = rf.get("/path/")
        response = middleware(request)

        assert response["Location"] == "/high-priority/"

    def test_fail_open_on_error(self, db, rf, make_middleware):
        middleware = make_middleware()
        request = rf.get("/normal/")

        with patch(
            "icv_sitemaps.middleware.RedirectMiddleware._check_redirect",
            side_effect=Exception("boom"),
        ):
            response = middleware(request)

        assert response.status_code == 200


class TestRedirectMiddleware404Tracking:
    def test_tracks_404_when_enabled(self, db, rf, make_middleware):
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE", 1.0),
            patch.object(conf_mod, "ICV_SITEMAPS_404_IGNORE_PATTERNS", []),
        ):
            middleware = make_middleware(status_code=404)
            request = rf.get("/not-found/")
            response = middleware(request)

        assert response.status_code == 404

        from icv_sitemaps.models.redirects import RedirectLog

        assert RedirectLog.objects.filter(path="/not-found/").exists()

    def test_does_not_track_when_disabled(self, db, rf, make_middleware):
        with patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_ENABLED", False):
            middleware = make_middleware(status_code=404)
            request = rf.get("/not-found/")
            middleware(request)

        from icv_sitemaps.models.redirects import RedirectLog

        assert not RedirectLog.objects.exists()

    def test_ignores_static_assets(self, db, rf, make_middleware):
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE", 1.0),
            patch.object(conf_mod, "ICV_SITEMAPS_404_IGNORE_PATTERNS", [r"\.(?:css|js|png)$"]),
        ):
            middleware = make_middleware(status_code=404)
            middleware._ignore_patterns = None  # Reset compiled cache.

            request = rf.get("/static/style.css")
            middleware(request)

        from icv_sitemaps.models.redirects import RedirectLog

        assert not RedirectLog.objects.exists()
