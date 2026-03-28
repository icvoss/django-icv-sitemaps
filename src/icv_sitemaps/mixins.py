"""SitemapMixin for Django models."""

from __future__ import annotations

from datetime import datetime


class SitemapMixin:
    """Declare a Django model as includable in XML sitemaps.

    Declare sitemap configuration on your model class, then use the
    icv_sitemaps service functions to generate sitemaps.

    Example::

        class Product(SitemapMixin, models.Model):
            sitemap_section_name = "products"
            sitemap_type = "standard"
            sitemap_changefreq = "weekly"
            sitemap_priority = 0.8

            name = models.CharField(max_length=200)
            slug = models.SlugField()

            def get_absolute_url(self):
                return f"/products/{self.slug}/"

    Image sitemap example::

        class Article(SitemapMixin, models.Model):
            sitemap_section_name = "articles"
            sitemap_type = "image"
            sitemap_image_field = "hero_image_url"
            sitemap_image_caption_field = "hero_image_caption"
            sitemap_image_title_field = "title"

    News sitemap example::

        class NewsPost(SitemapMixin, models.Model):
            sitemap_section_name = "news"
            sitemap_type = "news"
            sitemap_news_publication_name = "My News Site"
            sitemap_news_language = "en"
            sitemap_news_title_field = "headline"
            sitemap_news_date_field = "published_at"
    """

    # Required: logical section name matching a SitemapSection.name
    sitemap_section_name: str = ""

    # Sitemap type: standard, image, video, news
    sitemap_type: str = "standard"

    # Default values (can be overridden per-instance via get_* methods)
    sitemap_changefreq: str = "daily"
    sitemap_priority: float = 0.5

    # Image sitemap fields (when sitemap_type = "image")
    sitemap_image_field: str = ""  # Field name for image URL
    sitemap_image_caption_field: str = ""  # Field name for image caption
    sitemap_image_title_field: str = ""  # Field name for image title

    # Video sitemap fields (when sitemap_type = "video")
    sitemap_video_url_field: str = ""  # Field name for video URL
    sitemap_video_thumbnail_field: str = ""  # Field name for thumbnail URL
    sitemap_video_title_field: str = ""  # Field name for video title
    sitemap_video_description_field: str = ""  # Field name for video description
    sitemap_video_duration_field: str = ""  # Field name for duration (seconds)

    # News sitemap fields (when sitemap_type = "news")
    sitemap_news_publication_name: str = ""  # Publication name
    sitemap_news_language: str = "en"  # Publication language (ISO 639 code)
    sitemap_news_title_field: str = ""  # Field name for news title
    sitemap_news_date_field: str = ""  # Field name for publication date

    def get_sitemap_url(self) -> str:
        """Return the absolute URL for this instance.

        Defaults to calling ``get_absolute_url()``. Override to return a
        custom URL without modifying the model's canonical URL.
        """
        return self.get_absolute_url()  # type: ignore[attr-defined]

    def get_sitemap_lastmod(self) -> datetime | None:
        """Return the last-modified datetime for this instance.

        Defaults to the ``updated_at`` field when present (compatible with
        icv-core's TimestampedModel). Returns ``None`` if no timestamp is
        available — the generator will omit the ``<lastmod>`` element.
        """
        return getattr(self, "updated_at", None)

    def get_sitemap_changefreq(self) -> str:
        """Return the change frequency string for this instance.

        Override to vary the frequency per-instance (e.g. based on publish
        date or content type).
        """
        return self.sitemap_changefreq

    def get_sitemap_priority(self) -> float:
        """Return the priority (0.0–1.0) for this instance.

        Override to set per-instance priorities (e.g. featured products
        at 0.9, archived items at 0.2).
        """
        return self.sitemap_priority

    def get_sitemap_images(self) -> list[dict]:
        """Return image metadata for image sitemaps.

        Each dict may contain the following keys (all optional except ``loc``):
        - ``loc``: str — image URL (required)
        - ``caption``: str — image caption
        - ``title``: str — image title
        - ``geo_location``: str — geographic location string
        - ``license``: str — licence URL

        Returns an empty list when no image fields are configured or the
        instance has no image data.
        """
        if not self.sitemap_image_field:
            return []

        image_url = getattr(self, self.sitemap_image_field, None)
        if not image_url:
            return []

        image: dict = {"loc": image_url}

        if self.sitemap_image_caption_field:
            caption = getattr(self, self.sitemap_image_caption_field, None)
            if caption:
                image["caption"] = str(caption)

        if self.sitemap_image_title_field:
            title = getattr(self, self.sitemap_image_title_field, None)
            if title:
                image["title"] = str(title)

        return [image]

    def get_sitemap_video(self) -> dict | None:
        """Return video metadata for video sitemaps.

        The returned dict may contain the following keys:
        - ``thumbnail_loc``: str — thumbnail URL (required by Google)
        - ``title``: str — video title (required by Google)
        - ``description``: str — video description (required by Google)
        - ``content_loc``: str — video file URL
        - ``duration``: int — duration in seconds

        Returns ``None`` when no video fields are configured or the instance
        has no video data.
        """
        if not self.sitemap_video_url_field:
            return None

        video_url = getattr(self, self.sitemap_video_url_field, None)
        if not video_url:
            return None

        video: dict = {"content_loc": video_url}

        if self.sitemap_video_thumbnail_field:
            thumbnail = getattr(self, self.sitemap_video_thumbnail_field, None)
            if thumbnail:
                video["thumbnail_loc"] = str(thumbnail)

        if self.sitemap_video_title_field:
            title = getattr(self, self.sitemap_video_title_field, None)
            if title:
                video["title"] = str(title)

        if self.sitemap_video_description_field:
            description = getattr(self, self.sitemap_video_description_field, None)
            if description:
                video["description"] = str(description)

        if self.sitemap_video_duration_field:
            duration = getattr(self, self.sitemap_video_duration_field, None)
            if duration is not None:
                try:
                    video["duration"] = int(duration)
                except (TypeError, ValueError):
                    pass

        return video

    def get_sitemap_news(self) -> dict | None:
        """Return news metadata for news sitemaps.

        The returned dict contains:
        - ``publication_name``: str — publication name
        - ``language``: str — ISO 639 language code
        - ``title``: str — article title
        - ``publication_date``: datetime — publication date (must be within
          2 days for Google News; see ICV_SITEMAPS_NEWS_MAX_AGE_DAYS)

        Returns ``None`` when news fields are not configured or data is absent.
        """
        if not self.sitemap_news_title_field or not self.sitemap_news_date_field:
            return None

        title = getattr(self, self.sitemap_news_title_field, None)
        pub_date = getattr(self, self.sitemap_news_date_field, None)

        if not title or pub_date is None:
            return None

        return {
            "publication_name": self.sitemap_news_publication_name,
            "language": self.sitemap_news_language,
            "title": str(title),
            "publication_date": pub_date,
        }

    @classmethod
    def get_sitemap_queryset(cls):
        """Return the queryset used for sitemap generation.

        Automatically excludes soft-deleted records when the model has an
        ``is_deleted`` BooleanField or a ``deleted_at`` DateTimeField
        (compatible with icv-core's SoftDeleteModel).

        Override to customise filtering or add ``select_related``/
        ``prefetch_related`` for performance.
        """
        from django.db import models as django_models

        qs = cls.objects.all()  # type: ignore[attr-defined]

        # Exclude soft-deleted records using field-type detection —
        # avoids false positives from non-field attributes with the same name.
        try:
            is_deleted_field = cls._meta.get_field("is_deleted")
            if isinstance(is_deleted_field, django_models.BooleanField):
                qs = qs.filter(is_deleted=False)
        except Exception:
            pass

        try:
            deleted_at_field = cls._meta.get_field("deleted_at")
            if isinstance(deleted_at_field, django_models.DateTimeField):
                qs = qs.filter(deleted_at__isnull=True)
        except Exception:
            pass

        return qs
