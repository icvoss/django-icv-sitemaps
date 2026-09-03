from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IcvSitemapsConfig(AppConfig):
    name = "icv_sitemaps"
    label = "icv_sitemaps"
    verbose_name = _("ICV Sitemaps")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from . import (
            checks,  # noqa: F401, registers system checks
            handlers,  # noqa: F401, connects signal handlers
        )
        from .auto_sections import connect_auto_section_signals

        connect_auto_section_signals()
