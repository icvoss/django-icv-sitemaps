"""URL configuration for icv-sitemaps tests."""

from django.urls import include, path

urlpatterns = [
    path("", include("icv_sitemaps.urls")),
]
