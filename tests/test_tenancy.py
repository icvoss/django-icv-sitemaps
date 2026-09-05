"""Tests for icv_sitemaps.tenancy.resolve_tenant_id (#56).

Conf names are import-time constants (see ``tests/test_storage_routing.py``
and ``tests/test_middleware.py``), so ``ICV_SITEMAPS_TENANT_PREFIX_FUNC``
must be patched on ``icv_sitemaps.conf`` directly; setting it via
``settings``/``override_settings`` is a silent no-op.
"""

from unittest.mock import MagicMock, patch

import pytest

import icv_sitemaps.conf as conf_mod
from icv_sitemaps.exceptions import TenantResolutionError
from icv_sitemaps.tenancy import resolve_tenant_id


@pytest.fixture
def request_obj():
    return MagicMock()


class TestResolveTenantId:
    def test_unset_setting_returns_empty_string(self, request_obj):
        with patch.object(conf_mod, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", ""):
            assert resolve_tenant_id(request_obj) == ""

    def test_callable_returning_none_returns_empty_string(self, request_obj):
        with patch.object(conf_mod, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", "tests.tenant_resolvers.none"):
            assert resolve_tenant_id(request_obj) == ""

    def test_callable_returning_safe_tenant_id_is_returned(self, request_obj):
        with patch.object(conf_mod, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", "tests.tenant_resolvers.acme"):
            assert resolve_tenant_id(request_obj) == "acme"

    def test_callable_returning_unsafe_value_raises(self, request_obj):
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", "tests.tenant_resolvers.unsafe"),
            pytest.raises(TenantResolutionError),
        ):
            resolve_tenant_id(request_obj)

    def test_callable_that_raises_propagates_as_tenant_resolution_error(self, request_obj):
        with patch.object(conf_mod, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", "tests.tenant_resolvers.raises"):
            with pytest.raises(TenantResolutionError) as exc_info:
                resolve_tenant_id(request_obj)

        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert str(exc_info.value.__cause__) == "boom"

    def test_bad_dotted_path_raises_tenant_resolution_error(self, request_obj):
        with (
            patch.object(conf_mod, "ICV_SITEMAPS_TENANT_PREFIX_FUNC", "tests.tenant_resolvers.does_not_exist"),
            pytest.raises(TenantResolutionError),
        ):
            resolve_tenant_id(request_obj)
