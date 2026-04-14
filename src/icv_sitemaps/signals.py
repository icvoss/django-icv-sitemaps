"""Signal definitions for icv-sitemaps."""

from django.dispatch import Signal

# Fired after a sitemap section is successfully generated
# Provides: instance, url_count, file_count, duration_ms
sitemap_section_generated = Signal()

# Fired after all sections are generated
# Provides: sections, total_urls, duration_ms
sitemap_generation_complete = Signal()

# Fired after a section and its files are deleted
# Provides: instance
sitemap_section_deleted = Signal()

# Fired after search engines are pinged
# Provides: results (dict of engine → status)
sitemap_pinged = Signal()

# Fired after a section is marked stale
# Provides: instance
sitemap_section_stale = Signal()

# Fired after a redirect rule is saved (created or updated)
# Provides: instance
redirect_rule_saved = Signal()

# Fired after a redirect rule is deleted
# Provides: instance
redirect_rule_deleted = Signal()

# Fired when a redirect rule matches a request
# Provides: rule, path, status_code
redirect_matched = Signal()
