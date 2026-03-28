from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IcvSitemapsConfig(AppConfig):
    name = "icv_sitemaps"
    label = "icv_sitemaps"
    verbose_name = _("ICV Sitemaps")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from . import handlers  # noqa: F401 — connect signal handlers
        from .auto_sections import connect_auto_section_signals

        connect_auto_section_signals()
