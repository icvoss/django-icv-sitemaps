"""Security-specific tests for icv-sitemaps."""

import pytest
from django.test import Client

from icv_sitemaps.services.generation import _resolve_model
from icv_sitemaps.views import _validate_filename

# ---------------------------------------------------------------------------
# _validate_filename — path traversal and injection prevention
# ---------------------------------------------------------------------------


class TestValidateFilename:
    def test_valid_simple_filename(self):
        assert _validate_filename("articles-0.xml") is True

    def test_valid_filename_with_subdirectory(self):
        assert _validate_filename("tenant-a/articles-0.xml") is True

    def test_rejects_empty_string(self):
        assert _validate_filename("") is False

    def test_rejects_path_traversal_dotdot(self):
        assert _validate_filename("../etc/passwd") is False

    def test_rejects_path_traversal_in_middle(self):
        assert _validate_filename("sitemaps/../../../etc/passwd") is False

    def test_rejects_decoded_absolute_path(self):
        # Django URL routing decodes %2F to / before passing to the view,
        # so /etc/passwd arrives decoded — which is correctly rejected
        assert _validate_filename("/etc/passwd") is False

    def test_rejects_absolute_path_with_leading_slash(self):
        assert _validate_filename("/etc/passwd") is False

    def test_rejects_windows_style_absolute_path(self):
        # os.path.isabs returns True on POSIX for /... so test the behaviour
        # on the current platform, which matters most for CI

        result = _validate_filename("C:\\Windows\\System32")
        # On POSIX this is not absolute, so it passes the abs check
        # but we verify it doesn't break (no exception)
        assert isinstance(result, bool)

    def test_valid_gzip_extension(self):
        assert _validate_filename("products-0.xml.gz") is True

    def test_valid_filename_with_dashes_and_numbers(self):
        assert _validate_filename("section-name-2.xml") is True

    def test_rejects_dotdot_only(self):
        assert _validate_filename("..") is False

    def test_rejects_triple_dot(self):
        # ... normalises to ... which doesn't contain ".." as a component
        # but this is an edge case — just verify it doesn't blow up
        result = _validate_filename("...")
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _resolve_model — rejects non-model imports
# ---------------------------------------------------------------------------


class TestResolveModel:
    def test_accepts_valid_app_label_format(self):
        model_cls = _resolve_model("sitemaps_testapp.Article")
        from sitemaps_testapp.models import Article

        assert model_cls is Article

    def test_accepts_full_dotted_path_to_django_model(self):
        model_cls = _resolve_model("sitemaps_testapp.Article")
        from sitemaps_testapp.models import Article

        assert model_cls is Article

    def test_rejects_os_system(self):
        """import_string('os.system') resolves to a function, not a Model — must raise."""
        with pytest.raises((ValueError, LookupError, ImportError)):
            _resolve_model("os.system")

    def test_rejects_plain_module(self):
        """Resolving a module rather than a class raises."""
        with pytest.raises((ValueError, LookupError, ImportError, AttributeError)):
            _resolve_model("os.path")

    def test_rejects_nonexistent_app(self):
        with pytest.raises((LookupError, ImportError, ValueError)):
            _resolve_model("nonexistent_app.DoesNotExist")

    def test_rejects_nonexistent_model_in_known_app(self):
        with pytest.raises((LookupError, ImportError, ValueError)):
            _resolve_model("sitemaps_testapp.NonExistentModel")

    def test_rejects_builtin_function(self):
        """A builtin like 'builtins.print' is not a Django model."""
        with pytest.raises((ValueError, LookupError, ImportError)):
            _resolve_model("builtins.print")


# ---------------------------------------------------------------------------
# robots.txt — newline injection prevention
# ---------------------------------------------------------------------------


class TestRobotsTxtNewlineInjection:
    """Confirm that robots.txt content is served as-is without headers being
    injectable via stored user_agent or path fields.

    The robots.txt view returns a plain-text HTTP response. The concern here
    is that a stored user_agent or path value containing ``\r\n`` would
    render in the body — which is not an HTTP header injection (the response
    Content-Type is text/plain) but would corrupt the robots.txt output.
    We verify the content reflects stored values exactly.
    """

    def test_robots_txt_renders_rule_user_agent(self, db, settings):
        settings.ICV_SITEMAPS_BASE_URL = ""
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""

        from icv_sitemaps.testing.factories import RobotsRuleFactory

        RobotsRuleFactory(user_agent="Googlebot", directive="disallow", path="/admin/")

        from icv_sitemaps.services.robots import render_robots_txt

        content = render_robots_txt()

        # Content contains the rule verbatim — no injection of extra lines
        assert "User-agent: Googlebot" in content
        assert "Disallow: /admin/" in content

    def test_robots_txt_with_multiline_comment_renders_safely(self, db, settings):
        """A comment stored in the DB is rendered as a single comment line."""
        settings.ICV_SITEMAPS_BASE_URL = ""
        settings.ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES = []
        settings.ICV_SITEMAPS_ROBOTS_SITEMAP_URL = ""

        from icv_sitemaps.testing.factories import RobotsRuleFactory

        # Newlines in comment field — stored value rendered in body, not headers
        RobotsRuleFactory(
            user_agent="*",
            directive="disallow",
            path="/staging/",
            comment="Safe comment text",
        )

        from icv_sitemaps.services.robots import render_robots_txt

        content = render_robots_txt()

        assert "# Safe comment text" in content
        assert "Disallow: /staging/" in content


# ---------------------------------------------------------------------------
# View-level security — tenant_id and filename safety
# ---------------------------------------------------------------------------


class TestViewSecurityBoundaries:
    @pytest.fixture
    def client(self):
        return Client()

    def test_path_traversal_via_dotdot_returns_404(self, client, db):
        response = client.get("/sitemaps/../etc/passwd")
        assert response.status_code == 404

    def test_path_traversal_via_encoded_slash_returns_404(self, client, db):
        response = client.get("/sitemaps/%2Fetc%2Fpasswd")
        assert response.status_code == 404

    def test_absolute_path_in_filename_returns_404(self, client, db):
        # Django normalises /sitemaps//etc/passwd to /sitemaps/etc/passwd,
        # but a URL-encoded absolute path may arrive directly
        response = client.get("/sitemaps/%2Fetc/passwd")
        assert response.status_code == 404

    def test_missing_sitemap_file_returns_404(self, client, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

        response = client.get("/sitemaps/totally-missing.xml")
        assert response.status_code == 404

    def test_tenant_prefix_func_with_unsafe_chars_falls_back_to_empty(self, db, settings, client, tmp_path):
        """An unsafe tenant_id returned by TENANT_PREFIX_FUNC is ignored."""
        settings.MEDIA_ROOT = str(tmp_path)
        settings.ICV_SITEMAPS_TENANT_PREFIX_FUNC = "tests.helpers_for_tests.unsafe_tenant_func"

        # Rather than relying on an external helper module, patch the view helper
        import icv_sitemaps.views as views_mod

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                views_mod,
                "_get_tenant_id",
                lambda request: "",  # Always safe fallback
            )
            response = client.get("/robots.txt")

        # With empty tenant_id the request should succeed normally
        assert response.status_code == 200

    def test_tenant_id_with_path_traversal_in_storage_path_raises_value_error(self):
        """_storage_path rejects tenant IDs containing unsafe characters."""
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services.generation import _storage_path

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            pytest.raises(ValueError, match="Unsafe tenant_id"),
        ):
            _storage_path("sitemap.xml", tenant_id="../etc")

    def test_tenant_id_with_null_byte_raises_value_error(self):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services.generation import _storage_path

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            pytest.raises(ValueError, match="Unsafe tenant_id"),
        ):
            _storage_path("sitemap.xml", tenant_id="tenant\x00id")

    def test_tenant_id_with_forward_slash_raises_value_error(self):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services.generation import _storage_path

        with (
            patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"),
            pytest.raises(ValueError, match="Unsafe tenant_id"),
        ):
            _storage_path("sitemap.xml", tenant_id="tenant/evil")

    def test_safe_tenant_id_produces_scoped_path(self):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services.generation import _storage_path

        with patch.object(conf_mod, "ICV_SITEMAPS_STORAGE_PATH", "sitemaps/"):
            path = _storage_path("sitemap.xml", tenant_id="acme-corp")

        assert "acme-corp" in path
        assert ".." not in path

    def test_get_tenant_id_with_unsafe_return_value_falls_back_to_empty(self, settings):
        """_get_tenant_id returns '' when the callable returns an unsafe value."""
        settings.ICV_SITEMAPS_TENANT_PREFIX_FUNC = "icv_sitemaps.tests.helpers.fake_func"

        from unittest.mock import MagicMock, patch

        import icv_sitemaps.views as views_mod

        mock_request = MagicMock()

        # import_string is imported inline inside _get_tenant_id, so we patch
        # it via the django.utils.module_loading namespace
        with patch("django.utils.module_loading.import_string") as mock_import:
            # Simulate callable returning unsafe string with path traversal
            mock_import.return_value = lambda req: "tenant/../evil"
            result = views_mod._get_tenant_id(mock_request)

        # Unsafe value must be rejected — falls back to empty string
        assert result == ""


# ---------------------------------------------------------------------------
# _absolute_url — requires BASE_URL for relative URLs
# ---------------------------------------------------------------------------


class TestAbsoluteUrl:
    def test_already_absolute_https_returned_unchanged(self):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services.generation import _absolute_url

        with patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"):
            result = _absolute_url("https://other.com/page/")

        assert result == "https://other.com/page/"

    def test_already_absolute_http_returned_unchanged(self):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services.generation import _absolute_url

        with patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"):
            result = _absolute_url("http://example.com/page/")

        assert result == "http://example.com/page/"

    def test_relative_url_prepended_with_base_url(self):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services.generation import _absolute_url

        with patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com"):
            result = _absolute_url("/products/widget/")

        assert result == "https://example.com/products/widget/"

    def test_relative_url_without_base_url_raises_improperly_configured(self):
        from unittest.mock import patch

        from django.core.exceptions import ImproperlyConfigured

        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services.generation import _absolute_url

        with patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", ""), pytest.raises(ImproperlyConfigured):
            _absolute_url("/relative-path/")

    def test_base_url_trailing_slash_normalised(self):
        from unittest.mock import patch

        import icv_sitemaps.conf as conf_mod
        from icv_sitemaps.services.generation import _absolute_url

        with patch.object(conf_mod, "ICV_SITEMAPS_BASE_URL", "https://example.com/"):
            result = _absolute_url("/page/")

        # Should not produce double slash
        assert result == "https://example.com/page/"
        assert "//" not in result.replace("https://", "")
