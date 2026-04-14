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

REDIRECT_MATCH_TYPE_CHOICES = [
    ("exact", "Exact"),
    ("prefix", "Prefix"),
    ("regex", "Regex"),
]

REDIRECT_STATUS_CODE_CHOICES = [
    (301, "301 Moved Permanently"),
    (302, "302 Found"),
    (307, "307 Temporary Redirect"),
    (308, "308 Permanent Redirect"),
    (410, "410 Gone"),
]

REDIRECT_SOURCE_CHOICES = [
    ("admin", "Admin"),
    ("auto", "Auto"),
    ("signal", "Signal"),
    ("import", "Import"),
]

__all__ = [
    "SITEMAP_TYPE_CHOICES",
    "CHANGEFREQ_CHOICES",
    "DIRECTIVE_CHOICES",
    "RELATIONSHIP_CHOICES",
    "FILE_TYPE_CHOICES",
    "GENERATION_ACTION_CHOICES",
    "GENERATION_STATUS_CHOICES",
    "REDIRECT_MATCH_TYPE_CHOICES",
    "REDIRECT_STATUS_CODE_CHOICES",
    "REDIRECT_SOURCE_CHOICES",
]
