"""Abstract base model for icv-sitemaps — standalone, no icv-core dependency."""

import uuid

from django.db import models


class BaseModel(models.Model):
    """UUID primary key with auto-managed timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# Backwards-compatible alias used by older code generated from the boilerplate.
IcvSitemapsBaseModel = BaseModel
