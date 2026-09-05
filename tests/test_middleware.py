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


@pytest.fixture
def make_path_middleware():
    """Create a RedirectMiddleware whose downstream response depends on the path.

    Simulates a urlconf that resolves some paths (200) and not others (404),
    which the single-status ``make_middleware`` fixture cannot represent.
    """

    def _make(resolved_paths, resolved_status=200, unresolved_status=404):
        from django.http import HttpResponse

        def get_response(request):
            status = resolved_status if request.path in resolved_paths else unresolved_status
            return HttpResponse(status=status)

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

    def test_410_gone(self, db, rf, make_path_middleware):
        """A 410 rule is served once the urlconf has genuinely failed to
        resolve the path (see ``TestRedirectMiddlewareGoneOn404`` for the
        full status-code split introduced by #17).
        """
        RedirectRuleFactory(source_pattern="/removed/", destination="", status_code=410)

        middleware = make_path_middleware(resolved_paths=set())
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

    def test_priority_ordering_within_match_type(self, db, rf, make_middleware):
        """Priority only orders rules within the same match type.

        Both rules here are ``prefix``, so priority is the deciding factor.
        """
        RedirectRuleFactory(
            source_pattern="/path/",
            destination="/low-priority/",
            status_code=301,
            priority=10,
            match_type="prefix",
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

    def test_exact_beats_prefix_regardless_of_priority(self, db, rf, make_middleware):
        """An exact rule always wins over an overlapping prefix rule, even
        when the prefix rule has a numerically lower (better) priority.

        Fails against the pre-#24 code, which ordered purely by
        ("priority", "pk") and let the prefix rule win.
        """
        RedirectRuleFactory(
            source_pattern="/path/",
            destination="/exact-wins/",
            status_code=301,
            priority=10,
            match_type="exact",
        )
        RedirectRuleFactory(
            source_pattern="/path/",
            destination="/prefix-loses/",
            status_code=302,
            priority=1,
            match_type="prefix",
        )

        middleware = make_middleware()
        request = rf.get("/path/")
        response = middleware(request)

        assert response["Location"] == "/exact-wins/"

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


class TestRedirectMiddlewareGoneOn404:
    """Status-code split from #17: redirects still pre-empt the urlconf,

    a 410 is only served once the urlconf itself has already failed to
    resolve the path.
    """

    def test_redirect_wins_over_a_live_view(self, db, rf, make_path_middleware):
        """A 302 rule for a path the view resolves with 200 still wins.

        This pins the capability the owner decision deliberately kept: an
        operator-authored redirect beats the urlconf even when the target
        page is live. Must fail if a future change gates ALL rule
        evaluation on a 404, not just gone-rules.
        """
        RedirectRuleFactory(source_pattern="/promo/", destination="/summer-sale/", status_code=302)

        middleware = make_path_middleware(resolved_paths={"/promo/"})
        request = rf.get("/promo/")
        response = middleware(request)

        assert response.status_code == 302
        assert response["Location"] == "/summer-sale/"

    def test_gone_rule_does_not_shadow_a_live_view(self, db, rf, make_path_middleware):
        """A 410 rule for a path the view resolves with 200 loses to the 200.

        This is the actual defect: serving 410 for a path that demonstrably
        exists is self-contradicting. Must fail against pre-fix code, which
        evaluates all rules, including 410s, before get_response().
        """
        RedirectRuleFactory(source_pattern="/deleted-product/", destination="", status_code=410)

        middleware = make_path_middleware(resolved_paths={"/deleted-product/"})
        request = rf.get("/deleted-product/")
        response = middleware(request)

        assert response.status_code == 200

    def test_gone_rule_is_served_when_the_path_genuinely_404s(self, db, rf, make_path_middleware):
        """A 410 rule for a path that does not resolve is served as before.

        hit_count and last_hit_at increment and redirect_matched fires,
        exactly as they do for a live redirect today.
        """
        from icv_sitemaps.signals import redirect_matched

        rule = RedirectRuleFactory(source_pattern="/deleted-product/", destination="", status_code=410)

        received = []
        redirect_matched.connect(lambda sender, **kwargs: received.append(kwargs), weak=False)

        middleware = make_path_middleware(resolved_paths=set())
        request = rf.get("/deleted-product/")
        response = middleware(request)

        assert response.status_code == 410

        rule.refresh_from_db()
        assert rule.hit_count == 1
        assert rule.last_hit_at is not None

        assert len(received) == 1
        assert received[0]["status_code"] == 410
        assert received[0]["path"] == "/deleted-product/"

    def test_gone_match_is_not_recorded_as_a_404(self, db, rf, make_path_middleware):
        """A path answered by a gone-rule is not double-booked as a tracked 404.

        It has an answer (410), so it is not "missing" in the sense
        ``_maybe_record_404`` tracks.
        """
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE", 1.0),
            patch.object(conf_mod, "ICV_SITEMAPS_404_IGNORE_PATTERNS", []),
        ):
            RedirectRuleFactory(source_pattern="/deleted-product/", destination="", status_code=410)

            middleware = make_path_middleware(resolved_paths=set())
            request = rf.get("/deleted-product/")
            response = middleware(request)

        assert response.status_code == 410

        from icv_sitemaps.models.redirects import RedirectLog

        assert not RedirectLog.objects.filter(path="/deleted-product/").exists()

    def test_unmatched_404_is_still_tracked(self, db, rf, make_path_middleware):
        """A 404 with no matching rule at all is still recorded, as today."""
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE", 1.0),
            patch.object(conf_mod, "ICV_SITEMAPS_404_IGNORE_PATTERNS", []),
        ):
            middleware = make_path_middleware(resolved_paths=set())
            request = rf.get("/genuinely-missing/")
            response = middleware(request)

        assert response.status_code == 404

        from icv_sitemaps.models.redirects import RedirectLog

        assert RedirectLog.objects.filter(path="/genuinely-missing/").exists()


class TestTenantResolutionFailsClosed:
    """A raising tenant resolver must not evaluate the default tenant's
    redirect rules or record a 404 against another tenant's request (#56).

    The middleware's never-raises contract is unaffected: ``_check_redirect``
    and ``_maybe_record_404`` already run inside their own
    ``try/except Exception`` that logs and passes through, so a
    ``TenantResolutionError`` raised by the shared resolver reaches those
    handlers exactly like any other exception did before #56.
    """

    def test_redirect_rule_for_default_tenant_does_not_fire(self, db, rf, make_middleware):
        """Fails against pre-#56 code, which resolved the default (``""``)
        tenant on a raising resolver and matched its redirect rule."""
        RedirectRuleFactory(source_pattern="/old/", destination="/new/", tenant_id="", status_code=301)

        with patch.object(conf_mod, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", "tests.tenant_resolvers.raises"):
            middleware = make_middleware()
            request = rf.get("/old/")
            response = middleware(request)

        # Pass-through response from get_response(), not a 301 to /new/.
        assert response.status_code == 200

    def test_no_404_recorded_for_default_tenant_when_resolver_raises(self, db, rf, make_middleware):
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", "tests.tenant_resolvers.raises"),
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE", 1.0),
            patch.object(conf_mod, "ICV_SITEMAPS_404_IGNORE_PATTERNS", []),
        ):
            middleware = make_middleware(status_code=404)
            request = rf.get("/not-found/")
            response = middleware(request)

        assert response.status_code == 404

        from icv_sitemaps.models.redirects import RedirectLog

        assert not RedirectLog.objects.filter(path="/not-found/").exists()


class TestGoneResolver:
    """ICV_SITEMAPS_GONE_RESOLVER: consumer hook for gone-resolution (#27).

    Runs only on the 404 path, only after a gone ``RedirectRule`` lookup has
    found nothing.
    """

    def test_unset_resolver_is_unchanged_behaviour(self, db, rf, make_path_middleware):
        """No setting configured: identical to pre-#27 404 handling."""
        with patch.object(conf_mod, "ICV_SITEMAPS_GONE_RESOLVER", ""):
            middleware = make_path_middleware(resolved_paths=set())
            request = rf.get("/genuinely-missing/")
            response = middleware(request)

        assert response.status_code == 404

    def test_resolver_returning_410_serves_410(self, db, rf, make_path_middleware):
        with patch.object(conf_mod, "ICV_SITEMAPS_GONE_RESOLVER", "tests.gone_resolvers.always_gone"):
            middleware = make_path_middleware(resolved_paths=set())
            request = rf.get("/deleted-product/")
            response = middleware(request)

        assert response.status_code == 410

    def test_resolver_returning_none_passes_through_to_404(self, db, rf, make_path_middleware):
        with patch.object(conf_mod, "ICV_SITEMAPS_GONE_RESOLVER", "tests.gone_resolvers.never_gone"):
            middleware = make_path_middleware(resolved_paths=set())
            request = rf.get("/genuinely-missing/")
            response = middleware(request)

        assert response.status_code == 404

    def test_resolver_that_raises_is_fail_open(self, db, rf, make_path_middleware):
        with patch.object(conf_mod, "ICV_SITEMAPS_GONE_RESOLVER", "tests.gone_resolvers.raises"):
            middleware = make_path_middleware(resolved_paths=set())
            request = rf.get("/genuinely-missing/")
            response = middleware(request)

        assert response.status_code == 404

    def test_resolver_unexpected_value_passes_through_and_warns(self, db, rf, make_path_middleware, caplog):
        with patch.object(conf_mod, "ICV_SITEMAPS_GONE_RESOLVER", "tests.gone_resolvers.returns_404"):
            middleware = make_path_middleware(resolved_paths=set())
            request = rf.get("/genuinely-missing/")
            with caplog.at_level("WARNING"):
                response = middleware(request)

        assert response.status_code == 404
        assert "unexpected value" in caplog.text

    def test_resolver_not_called_when_response_is_not_404(self, db, rf, make_path_middleware):
        with patch.object(conf_mod, "ICV_SITEMAPS_GONE_RESOLVER", "tests.gone_resolvers.raises"):
            middleware = make_path_middleware(resolved_paths={"/live-page/"})
            request = rf.get("/live-page/")
            response = middleware(request)

        assert response.status_code == 200

    def test_resolver_not_called_when_a_gone_rule_already_matched(self, db, rf, make_path_middleware):
        """Rules beat the resolver: ordering is rules first, then resolver."""
        RedirectRuleFactory(source_pattern="/deleted-product/", destination="", status_code=410)

        with patch.object(conf_mod, "ICV_SITEMAPS_GONE_RESOLVER", "tests.gone_resolvers.raises"):
            middleware = make_path_middleware(resolved_paths=set())
            request = rf.get("/deleted-product/")
            response = middleware(request)

        # If the resolver had been called it would raise and the exception
        # is not caught anywhere along this path, so a clean 410 here proves
        # the rule short-circuited before the resolver ran.
        assert response.status_code == 410

    def test_resolver_hit_does_not_also_record_a_404(self, db, rf, make_path_middleware):
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_GONE_RESOLVER", "tests.gone_resolvers.always_gone"),
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_ENABLED", True),
            patch.object(conf_mod, "ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE", 1.0),
            patch.object(conf_mod, "ICV_SITEMAPS_404_IGNORE_PATTERNS", []),
        ):
            middleware = make_path_middleware(resolved_paths=set())
            request = rf.get("/deleted-product/")
            response = middleware(request)

        assert response.status_code == 410

        from icv_sitemaps.models.redirects import RedirectLog

        assert not RedirectLog.objects.filter(path="/deleted-product/").exists()
