# Changelog

## [Unreleased]

## [0.3.0] - 2026-04-14

### Added

- `Crawl-delay`, `Sitemap`, and `Host` directive choices for `RobotsRule` —
  these directives can now be stored in the database instead of requiring the
  `ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES` config fallback
- `add_robots_rule()` service accepts all valid robots.txt directives; path
  validation only enforced for `allow`/`disallow`

### Changed

- `RobotsRule.directive` field widened from `max_length=10` to `max_length=20`
  to accommodate `Crawl-delay` (11 chars) with headroom
- Migration `0003_alter_robotsrule_directive` generated on Django 5.2

### Fixed

- **Sitemap generation drops connection on large querysets** — replaced single
  `queryset.iterator()` with keyset pagination (`pk__gt` batching) and
  `close_old_connections()` between chunks. The old approach held a single
  server-side cursor across millions of rows, which managed Postgres providers
  (e.g. DigitalOcean) kill via SSL/idle timeouts. Each batch now issues a
  fresh short-lived query.

## [0.2.3] - 2026-03-25

### Fixed

- `SitemapSection.settings` JSONField now has `blank=True` — fixes admin form
  validation error when saving a section with an empty `{}` settings field
- Added migration `0002` for `settings` (`blank=True`) and `model_path`
  (help_text updated to `app_label.ModelName` format)

## [0.2.2] - 2026-03-25

### Changed

- **BREAKING:** `ICV_SITEMAPS_PING_ENABLED` now defaults to `False` and
  `ICV_SITEMAPS_PING_ENGINES` defaults to `[]` — Google and Bing have retired
  their sitemap ping endpoints. Projects that still need pinging must opt in
  explicitly.

### Fixed

- Resolved remaining ruff SIM117 lint violations in test suite (combined nested
  `with` statements)
- Fixed import ordering in initial migration

## [0.2.1] - 2026-03-25

### Security

- `_resolve_model()` now uses `apps.get_model()` exclusively — removed
  `import_string()` fallback that allowed arbitrary module imports
- File size check before reading sitemap files in views (prevents memory
  exhaustion on oversized files)
- Tenant ID regex validation in `_get_tenant_id()` view helper
- Newline injection prevention in `add_robots_rule()` service
- URL scheme validation in `ping_search_engines()` (rejects non-HTTP URLs)
- Replaced `assert` with `if`/`raise RuntimeError` in setup management command

### Added

- Conditional ping based on SHA-256 checksum comparison of sitemap index
- Empty section handling — writes valid empty `<urlset>` XML
- `delete_with_files` admin action for bulk section deletion with storage cleanup
- Image, video, and news sitemap XML generation tests (21 new tests)
- Management command tests (36 new tests)
- Auto-section signal tests (16 new tests)
- Security boundary tests (36 new tests)

### Fixed

- `_regenerate_index()` management command helper now imports `generate_index`
  correctly
- Setup command reads `model` config key first, falls back to `model_path`
- Ping command imports `_PING_URLS` from `services/ping.py` instead of
  duplicating URL templates
- `cleanup_orphan_files()` recurses tenant subdirectories correctly
- `model_path` standardised on `app_label.ModelName` format throughout

### Removed

- Dead `ICV_SITEMAPS_STREAMING_THRESHOLD` setting
- `httpx` dependency (was unused — pinging uses `urllib.request`)

## [0.1.2] - 2026-03-24

### Added

- Initial database migration (`0001_initial`) — previously missing from the
  package, causing `makemigrations` to detect unapplied model changes in
  consuming projects

## [0.1.1] - 2026-03-22

### Fixed

- **BREAKING (DB):** Shortened all index and constraint names to ≤30 characters
  for Oracle compatibility (`icv_sm_*` prefix convention, matching icv-search)
- `ICV_SITEMAPS_BASE_URL` now raises `ImproperlyConfigured` when empty and a
  relative URL is passed, instead of silently producing broken `<loc>` values
- `mark_section_stale()` uses a single `UPDATE` query instead of `SELECT` +
  `save()`, eliminating N+1 when called from auto-section signal handlers
- `set_discovery_file_content()` wrapped in `transaction.atomic()` with
  `select_for_update()` to prevent race conditions on concurrent writes
- `_storage_path()` rejects tenant IDs containing path-traversal sequences
  or unsafe characters (only `[\w\-]` allowed)
- `SitemapMixin.get_sitemap_queryset()` uses `_meta.get_field()` with
  `isinstance` checks for soft-delete detection instead of fragile `hasattr`
- Extracted XML namespace URIs to module-level constants (`SITEMAP_NS`,
  `IMAGE_NS`, `VIDEO_NS`, `NEWS_NS`)
- `sitemap_section_stale` signal only fires when `is_stale` state actually
  changes (no signal when section is already stale)

## [0.1.0] - 2026-03-22

### Added

- Initial release
- 6 models: SitemapSection, SitemapFile, SitemapGenerationLog, RobotsRule, AdsEntry, DiscoveryFileConfig
- SitemapMixin for declaring Django models as sitemap-includable
- XML sitemap generation (standard, image, video, news types)
- Sitemap index generation with URL-limit splitting (50,000 URLs / 50 MB per file)
- Incremental staleness tracking and selective regeneration
- Background generation via Celery tasks (optional)
- Storage backend abstraction via Django's storage framework
- robots.txt generation (database-driven rules)
- llms.txt, ads.txt, app-ads.txt, security.txt, humans.txt serving
- Search engine ping on sitemap regeneration
- Multi-tenancy support for all discovery files
- 5 management commands: setup, generate, ping, validate, stats
- Django admin for all models
- Testing utilities (factories, fixtures, helpers)
- 5 signals for sitemap lifecycle events
