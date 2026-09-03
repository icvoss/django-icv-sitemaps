import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("icv_sitemaps", "0005_sitemapsection_section_type_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sitemapfile",
            name="generated_at",
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                help_text=(
                    "When this file's content was last generated. Carried forward from "
                    "the previous row when a regeneration finds the shard's checksum "
                    "unchanged, so this reflects content changes rather than every "
                    "generation run (issue #19)."
                ),
            ),
        ),
    ]
