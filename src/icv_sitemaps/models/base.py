"""Abstract base model for icv-sitemaps — standalone, no icv-core dependency."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class BaseModel(models.Model):
    """UUID primary key with auto-managed timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# Backwards-compatible alias used by older code generated from the boilerplate.
IcvSitemapsBaseModel = BaseModel


def sync_tenant_key(instance: models.Model) -> None:
    """Keep a model's tenant_id string in sync with its tenant_ref FK (issue #50).

    Called from each tenant-keyed model's clean() and save(). Does nothing
    when tenant_ref is unset. When set, derives str(instance.tenant_ref_id):
    a blank tenant_id is populated from it; a populated tenant_id that
    disagrees with it raises ValidationError rather than being silently
    overwritten (fail closed).
    """
    tenant_ref_id = instance.tenant_ref_id
    if tenant_ref_id is None:
        return

    derived = str(tenant_ref_id)
    if instance.tenant_id == "":
        instance.tenant_id = derived
    elif instance.tenant_id != derived:
        raise ValidationError(
            {
                "tenant_id": _("tenant_id %(tenant_id)r does not match tenant_ref %(tenant_ref)r.")
                % {"tenant_id": instance.tenant_id, "tenant_ref": derived}
            }
        )
