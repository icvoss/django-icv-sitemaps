"""URL configuration for icv-sitemaps."""

from django.urls import path

from icv_sitemaps import views

app_name = "icv_sitemaps"

urlpatterns = [
    path("sitemap.xml", views.sitemap_index_view, name="sitemap-index"),
    path("sitemaps/<path:filename>", views.sitemap_file_view, name="sitemap-file"),
    path("robots.txt", views.robots_txt_view, name="robots-txt"),
    path("llms.txt", views.llms_txt_view, name="llms-txt"),
    path("ads.txt", views.ads_txt_view, name="ads-txt"),
    path("app-ads.txt", views.app_ads_txt_view, name="app-ads-txt"),
    path(".well-known/security.txt", views.security_txt_view, name="security-txt"),
    path("security.txt", views.security_txt_root_view, name="security-txt-root"),
    path("humans.txt", views.humans_txt_view, name="humans-txt"),
]
