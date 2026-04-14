"""Choice constants for icv-sitemaps models."""

SITEMAP_TYPE_CHOICES = [
    ("standard", "Standard"),
    ("image", "Image"),
    ("video", "Video"),
    ("news", "News"),
]

CHANGEFREQ_CHOICES = [
    ("always", "Always"),
    ("hourly", "Hourly"),
    ("daily", "Daily"),
    ("weekly", "Weekly"),
    ("monthly", "Monthly"),
    ("yearly", "Yearly"),
    ("never", "Never"),
]

DIRECTIVE_CHOICES = [
    ("allow", "Allow"),
    ("disallow", "Disallow"),
    ("crawl-delay", "Crawl-delay"),
    ("sitemap", "Sitemap"),
    ("host", "Host"),
]

RELATIONSHIP_CHOICES = [
    ("DIRECT", "Direct"),
    ("RESELLER", "Reseller"),
]

FILE_TYPE_CHOICES = [
    ("llms_txt", "llms.txt"),
    ("security_txt", "security.txt"),
    ("humans_txt", "humans.txt"),
]

GENERATION_ACTION_CHOICES = [
    ("generate_section", "Generate section"),
    ("generate_all", "Generate all"),
    ("generate_index", "Generate index"),
    ("ping", "Ping search engines"),
]

GENERATION_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("running", "Running"),
    ("success", "Success"),
    ("failed", "Failed"),
]

__all__ = [
    "SITEMAP_TYPE_CHOICES",
    "CHANGEFREQ_CHOICES",
    "DIRECTIVE_CHOICES",
    "RELATIONSHIP_CHOICES",
    "FILE_TYPE_CHOICES",
    "GENERATION_ACTION_CHOICES",
    "GENERATION_STATUS_CHOICES",
]
