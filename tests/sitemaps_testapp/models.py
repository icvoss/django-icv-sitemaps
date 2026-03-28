"""Test models for icv-sitemaps tests."""

from django.db import models

from icv_sitemaps.mixins import SitemapMixin


class Article(SitemapMixin, models.Model):
    """Test model for standard sitemaps."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    body = models.TextField(default="")
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    sitemap_section_name = "articles"
    sitemap_changefreq = "weekly"
    sitemap_priority = 0.7

    class Meta:
        app_label = "sitemaps_testapp"

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return f"/articles/{self.slug}/"

    @classmethod
    def get_sitemap_queryset(cls):
        return cls.objects.filter(is_published=True)


class ProductImage(SitemapMixin, models.Model):
    """Test model for image sitemaps."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    image_url = models.URLField(default="")
    caption = models.CharField(max_length=500, default="")
    updated_at = models.DateTimeField(auto_now=True)

    sitemap_section_name = "product_images"
    sitemap_type = "image"
    sitemap_image_field = "image_url"
    sitemap_image_caption_field = "caption"
    sitemap_image_title_field = "title"

    class Meta:
        app_label = "sitemaps_testapp"

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return f"/images/{self.slug}/"


class VideoItem(SitemapMixin, models.Model):
    """Test model for video sitemaps."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    video_url = models.URLField(default="")
    thumbnail_url = models.URLField(default="")
    description = models.TextField(default="")
    duration_seconds = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    sitemap_section_name = "videos"
    sitemap_type = "video"
    sitemap_video_url_field = "video_url"
    sitemap_video_thumbnail_field = "thumbnail_url"
    sitemap_video_title_field = "title"
    sitemap_video_description_field = "description"
    sitemap_video_duration_field = "duration_seconds"

    class Meta:
        app_label = "sitemaps_testapp"

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return f"/videos/{self.slug}/"


class NewsItem(SitemapMixin, models.Model):
    """Test model for news sitemaps."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    published_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    sitemap_section_name = "news"
    sitemap_type = "news"
    sitemap_news_publication_name = "Test Publication"
    sitemap_news_language = "en"
    sitemap_news_title_field = "title"
    sitemap_news_date_field = "published_at"

    class Meta:
        app_label = "sitemaps_testapp"

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return f"/news/{self.slug}/"
