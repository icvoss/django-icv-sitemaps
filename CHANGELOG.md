# Changelog

## [Unreleased]

### Fixed

- **A resolver failure in `ICV_SITEMAPS_TENANT_PREFIX_FUNC` no longer serves
  the default tenant's files** (#56). Previously, when the configured
  callable raised an exception, or returned a value that failed the
  `[\w\-]+` safety check, both the views and `RedirectMiddleware` silently
  fell back to `tenant_id=""`, the single-tenant bucket. That meant a
  transient error inside a consumer's resolver served the default tenant's
  `robots.txt`, `ads.txt`, `app-ads.txt`, `security.txt`, `humans.txt`,
  `llms.txt`, sitemap index and sitemap shards, with a 200 status and
  cacheable headers, to whichever host the request arrived on; a redirect
  rule or 404 record could likewise be evaluated against the wrong tenant.
  Now, a resolver exception or unsafe return value raises
  `icv_sitemaps.exceptions.TenantResolutionError`. In views, this propagates
  as Django's 500, the correct signal for a crawler to retry later rather
  than conclude the sitemap is gone; nothing is cached on this path. In
  `RedirectMiddleware`, which never raises to its caller, the failure is
  caught by the existing pass-through handling around redirect checking and
  404 recording, so the request reaches the underlying view unmodified
  instead of being redirected or 404-tracked under the wrong tenant.
  **Consumer impact**: any resolver that has ever raised or returned an
  unsafe value now causes affected requests to 500 instead of silently
  serving the default tenant's content.

## [3.1.0] - 2026-09-04

### Fixed

- **`ICV_SITEMAPS_STORAGE_BACKEND` is now honoured everywhere, not only by
  generation** (#52). Previously only file generation read the configured
  storage backend; every other storage access (the sitemap index and shard
  views, the orphan-file pruning task, and both the `icv_sitemaps_setup` and
  `icv_sitemaps_validate` management commands) imported Django's
  `default_storage` directly. A project pointing storage at something other
  than the default (S3, for example) got files written to that backend but
  served, pruned and validated against the default backend instead, so
  requests for a generated sitemap 404'd. All storage access now goes
  through a single resolution point (`icv_sitemaps.storage.get_storage()`),
  so views, pruning and both commands read the same storage generation
  writes to.

### Added

- **Three fleet-global settings** (ADR-037): `ICV_STORAGES_ALIAS`,
  `ICV_CACHES_ALIAS` and `ICV_AUTH_USER_MODEL`. Each mirrors a Django-native
  concern (`STORAGES`, `CACHES`, `AUTH_USER_MODEL`) with an ICV-prefixed
  override that falls back to stock Django behaviour when unset, so a
  project that configures nothing sees no change. `ICV_STORAGES_ALIAS`
  selects which alias in `STORAGES` icv-sitemaps writes generated files to;
  `ICV_CACHES_ALIAS` selects which alias in `CACHES` icv-sitemaps caches
  through; `ICV_AUTH_USER_MODEL` selects which user model the
  `DiscoveryFileConfig.last_modified_by` foreign key targets.
- `icv_sitemaps.W002` system check, warning when the deprecated
  `ICV_SITEMAPS_STORAGE_BACKEND` is set.

### Deprecated

- `ICV_SITEMAPS_STORAGE_BACKEND` in favour of `ICV_STORAGES_ALIAS` (ADR-037).
  Still honoured when set; a `manage.py check` now warns via
  `icv_sitemaps.W002`. Removed in the next minor release.

## [3.0.0] - 2026-09-03

### Added

- **BREAKING:** **Conditional requests and `Cache-Control` on every sitemap and
  discovery-file view** (#32, #33). Every response from
  `sitemap_index_view`, `sitemap_file_view`, `robots_txt_view`,
  `llms_txt_view`, `ads_txt_view`, `app_ads_txt_view`, `security_txt_view`
  and `humans_txt_view` now carries a strong `ETag` (a SHA-256 hash of the
  served bytes) and honours `If-None-Match` with a bodyless 304, so a
  crawler polling on a schedule gets a cheap 304 instead of re-transferring
  an unchanged sitemap or discovery file on every request.
  `sitemap_file_view` additionally emits `Last-Modified` (and honours
  `If-Modified-Since`) when a `SitemapFile` row exists for the served
  storage path, read from that row's genuine, persisted `generated_at`;
  every other view omits `Last-Modified` rather than fabricate one, since
  none has an equivalent single-row timestamp to reach for (the sitemap
  index and every rendered discovery file either have no backing row or
  aggregate several rows with no single "this changed last" value). Every
  response also carries `Cache-Control`, communicating the freshness
  opinion `ICV_SITEMAPS_CACHE_TIMEOUT` already expressed server-side to
  crawlers, CDNs, and reverse proxies for the first time. A response
  served from the documented render-failure fallback in `robots_txt_view`,
  `ads_txt_view`, and `app_ads_txt_view` is deliberately excluded from
  both: an empty robots.txt or ads.txt body produced by a rendering
  failure must never be told to a client or an intermediate cache as
  validated, unchanged, or safe to reuse, which would otherwise turn a
  transient failure into a much longer-lived one.

- **`ICV_SITEMAPS_HTTP_CACHE_CONTROL`** (#33), overriding or disabling the
  `Cache-Control` header above. Empty string (the default) derives
  `"public, max-age=<ICV_SITEMAPS_CACHE_TIMEOUT>"`. The literal value
  `"none"` omits the header entirely. Any other non-empty string is sent
  verbatim, for an operator who wants a directive this package does not
  model (`stale-while-revalidate`, `s-maxage`, `must-revalidate`, and so
  on) without a code change.

- **`invalidate_robots_cache`, `invalidate_ads_cache`, `invalidate_discovery_cache`**
  (#37), extracted and exported alongside `invalidate_redirect_cache` (#29):
  `RobotsRule`, `AdsEntry` and `DiscoveryFileConfig` shared the same
  `bulk_create` staleness gap #29 fixed for `RedirectRule`. Cache
  invalidation for these three models previously happened only via
  `post_save`/`post_delete` signal handlers, which Django's `bulk_create`
  never fires, leaving a stale render served until
  `ICV_SITEMAPS_CACHE_TIMEOUT` (default 3600 seconds) expires even though
  the rows already exist in the database. `handlers.py` and
  `add_robots_rule`/`add_ads_entry`/`set_discovery_file_content` now call
  these named functions instead of rebuilding cache-key strings inline; the
  keys are unchanged. `invalidate_ads_cache` takes an `is_app_ads` keyword,
  since `AdsEntry` maps to two distinct cache keys; `invalidate_discovery_cache`
  takes `file_type` as a required positional argument, since
  `DiscoveryFileConfig` is keyed per file type. See the README for the
  raw-`bulk_create` caveat for each of the three models. No bulk-safe
  creator equivalent to `bulk_create_redirects` is added for these three:
  none has a high-volume machine-generated write pattern comparable to the
  redirect tombstone workflow that motivated it.

- A Django system check (`icv_sitemaps.W001`) warning when
  `ICV_SITEMAPS_BASE_URL` is empty (#34). Sitemap `<loc>` elements must be
  absolute URLs; with the setting unset, `generate_index` silently emitted
  a root-relative path, which is invalid per the sitemap protocol, while
  `ping_search_engines` and `icv_sitemaps_ping` already surfaced the
  problem on their own paths. The check now surfaces it on every
  `manage.py` invocation too. It is a `Warning`, not an `Error`, and is not
  gated on whether a `SitemapSection` is configured: the setting is
  genuinely optional for a consumer who only serves robots.txt or ads.txt,
  and a check that queries the database to decide severity would be a
  startup-breakage risk during migrations, fresh installs, and
  `collectstatic`.

### Fixed

- **`generate_index()` never checked the sitemap index itself against the
  sitemap protocol's own limits** (#36). Section shards are already
  capped at 50,000 URLs and 50 MiB via `ICV_SITEMAPS_MAX_URLS_PER_FILE`
  and `ICV_SITEMAPS_MAX_FILE_SIZE_BYTES`, but the index that lists those
  shards had no equivalent check: it selected every `SitemapFile` row for
  the tenant and appended one `<sitemap>` element per row with no bound.
  No realistic tenant reaches the 50,000-entry cap (each entry represents
  a whole shard of up to 50,000 URLs), and the byte cap, while nearer, is
  still remote for the small, hand-built index document. The real defect
  was an unbounded loop with nothing to catch it silently drifting past a
  protocol limit rather than any specific tenant being at risk today.
  `generate_index()` now counts the candidate `SitemapFile` rows and
  measures the actual serialised, uncompressed XML bytes before writing,
  raising `SitemapGenerationError` (and logging at `error` level) naming
  whichever cap was exceeded, rather than writing a sitemap index a
  crawler would reject.

- **Missing PEP 561 `py.typed` marker** (#39). The package ships fully
  annotated source but no `py.typed` file, so PEP 561 requires a type
  checker running in a consuming project to ignore the annotations
  entirely and treat every import from `icv_sitemaps` as `Any`. Added the
  marker and a `[tool.setuptools.package-data]` declaration so it is
  actually packaged in the wheel; a consumer's `mypy` or `pyright` run can
  now see this package's types.

## [2.0.0] - 2026-09-03

### Added

- **`bulk_create_redirects`** (#29), a bulk-safe alternative to a consumer
  calling `RedirectRule.objects.bulk_create(...)` directly. Django's
  `bulk_create` emits no `post_save` signal, so `prefix` and `regex`
  redirect rules written that way are invisible to the cached rule list
  (`get_cached_redirect_rules`) until `ICV_SITEMAPS_REDIRECT_CACHE_TIMEOUT`
  (default 300 seconds) expires, even though the row already exists in the
  database and `check_redirect` should be serving it. Exact-match rules are
  not affected: `check_redirect` always resolves an exact match with a
  direct database query, never from the cache, since #16. `bulk_create_redirects`
  takes the same row format as `bulk_import_redirects`, validates each row
  with the same rules as `add_redirect`, writes with a single
  `bulk_create(ignore_conflicts=True)` call, and invalidates the cache once
  at the end rather than per row. It is insert-only (no per-row update), so
  its summary dict has no `updated` key: `{"created": int, "errors":
  list[dict]}`. A row colliding with an existing exact-match rule on
  `(source_pattern, tenant_id)` is silently skipped rather than raising.
  `invalidate_redirect_cache` is now also exported from
  `icv_sitemaps.services`, so a consumer who writes `RedirectRule` rows
  with a raw `bulk_create` some other way still has a documented, public
  way to invalidate the cache themselves afterwards; see the README for the
  raw-`bulk_create` caveat.

- **`ICV_SITEMAPS_GONE_RESOLVER`** (#27), a consumer hook for gone-resolution
  on the 404 path. A dotted path to a callable taking the request and
  returning `410` or `None`, resolved the same way as
  `ICV_SITEMAPS_TENANT_PREFIX_FUNC` and called from `RedirectMiddleware`
  only when the response is a 404 and no gone `RedirectRule` matched, so a
  hand-authored rule still wins. Lets a consumer answer "is this path
  deliberately gone?" from their own data (for example a soft-delete flag)
  without materialising a `RedirectRule` row per deleted object. Any return
  value other than `410` or `None` is logged as a warning and treated as
  `None`; a raising callable is caught, logged, and fails open to the
  normal 404 response.

- **Django 6.1 added to the CI test matrix** and declared via the
  `Framework :: Django :: 6.1` classifier.

### Fixed

- **`check_redirect` scanned every active rule in Python on every request**
  (#16). This made `RedirectRule` impractical for machine-generated
  exact-match rules, such as a job that creates a 410 "gone" tombstone for
  each deleted catalogue item: the cached rule list, and the linear scan
  over it, both grew with the number of exact rules, adding real latency to
  every request once the rule count reached the tens or hundreds of
  thousands, even for paths that matched nothing.

  An exact match is now resolved by a single direct database query
  (`match_type="exact"`, `source_pattern=<path>`, scoped by `tenant_id`)
  before the cached list is ever built or read, so its cost no longer
  depends on how many exact rules exist. This needs no new index:
  `source_pattern` already carries `db_index=True`, which serves this
  query on every supported database backend. Exact rules are also no
  longer included in the cached prefix/regex list, so a cache that would
  have held 200,000 exact rules now holds none of them. Because the cached
  payload's meaning changed, its key moved from
  `icv_sitemaps:redirects:v2:<tenant_id>` to
  `icv_sitemaps:redirects:v3:<tenant_id>`; a stale v2 entry from a
  pre-upgrade process is simply ignored and the list is rebuilt under the
  new shape on next read, no action needed. `check_redirect`'s documented
  precedence (exact beats prefix beats regex, `priority` only orders
  within a match type) and its `status_codes` filter (#17) are unchanged;
  the exact-match query applies `status_codes` itself, so a 410-only exact
  rule still cannot pre-empt a live view before the urlconf runs.

- **BREAKING:** **A 410 rule could shadow a live view** (#17). `RedirectMiddleware` now
  splits redirect evaluation by status code: a 301/302/307/308 rule is still
  evaluated before `get_response()` and wins over the urlconf exactly as
  before, no behaviour change there. A 410 rule is now evaluated only when
  the response from `get_response()` is a 404. Previously a 410 rule was
  evaluated ahead of the urlconf like any other rule, so a stale "gone" rule
  for a path a view now legitimately serves at 200 would incorrectly answer
  with 410 instead. A consumer whose 410 rule currently shadows a live URL
  will start getting the live page's 200 response instead of a 410; a 410
  rule for a path that genuinely does not resolve is served exactly as
  before, including `hit_count`/`last_hit_at` tracking and the
  `redirect_matched` signal. A path answered by a matching gone-rule is not
  additionally recorded by the 404 tracker, since it now has an answer
  rather than being missing. `check_redirect` gained a keyword-only
  `status_codes` parameter to support this; the default (`None`) preserves
  today's behaviour for existing callers.

- **BREAKING:** **Redirect rules were not evaluated in the documented order** (#24).
  `check_redirect`'s docstring has always said rules are evaluated "exact
  matches first, then prefix, then regex", but `get_cached_redirect_rules`
  only ordered by `priority` and never took `match_type` into account. In
  practice, a broad `prefix` rule at a lower `priority` number beat a more
  specific `exact` rule at a higher one, contradicting the documented
  contract. Redirect rules are now ordered by match type first (`exact`,
  then `prefix`, then `regex`), then by `priority` within that match type,
  then by primary key as a stable tiebreaker.

  **This is a behaviour change** for any site with overlapping rules of
  different match types: an `exact` rule now always wins over an
  overlapping `prefix` or `regex` rule, regardless of `priority`, and a
  `prefix` rule always wins over an overlapping `regex` rule. If you tuned
  `priority` numbers to force a `prefix` or `regex` rule to win over an
  `exact` rule for the same path, that workaround no longer applies; the
  `exact` rule wins now, matching what the docstring always promised.
  `priority` still controls ordering between rules of the *same* match
  type, so most single-match-type setups are unaffected. This also fixes
  the 410-tombstone case from #16: an `exact` rule for a deleted URL now
  reliably beats a broad `prefix` rule that would otherwise have redirected
  it away from a 410 response.

  The redirect rule cache key gained a version segment
  (`icv_sitemaps:redirects:v2:<tenant_id>`) so that a stale cache entry
  populated by a pre-#24 process (holding the old priority-only ordering)
  cannot be served after upgrade; it is simply missed and rebuilt with the
  new ordering on first read.
- **An unreachable cache backend could turn a read into a 500 and a write
  into a failed save** (#9). The issue as filed named two unguarded
  `cache.get`/`cache.set` calls in `views.py`; an audit of the whole
  package found 26 call sites, not two, and the worst were not in views at
  all. All 26 are now fixed. `/robots.txt`, `/llms.txt`, `/ads.txt`,
  `/app-ads.txt`, `/.well-known/security.txt` and `/humans.txt` (6 views,
  12 calls) previously raised straight out of the view when the cache
  backend raised on read or write, for example
  `django_redis.cache.RedisCache` with no `IGNORE_EXCEPTIONS` against an
  unreachable Redis. Worse, the `post_save`/`post_delete` signal handlers
  that invalidate those caches when a `RobotsRule`, `AdsEntry`,
  `DiscoveryFileConfig` or `RedirectRule` changes (8 calls in
  `handlers.py`) called `cache.delete()` unguarded too, so an unreachable
  cache backend made *saving any of those models raise*, in the admin and
  in any other consumer code path, a write-side failure the original
  report never mentioned. The same pattern was also present in
  `get_cached_redirect_rules`/`invalidate_redirect_cache`
  (`services/redirects.py`, 3 calls) and in the cache invalidation done by
  `add_robots_rule()`, `add_ads_entry()` and `set_discovery_file_content()`
  (`services/robots.py`, `services/ads.py`, `services/discovery.py`, 1
  call each). The cache is now treated as an optimisation, never a
  dependency, via a new internal `icv_sitemaps.cache` module: a failed
  `get` is treated as a cache miss (the view regenerates the content), a
  failed `set` is swallowed (the value is simply not cached), and a
  failed `delete` is logged at `WARNING` (not swallowed quietly, since it
  leaves stale content served for up to the configured cache timeout,
  which is a correctness problem rather than a performance one). Also
  fixed in the same views: `robots_txt_view`, `ads_txt_view` and
  `app_ads_txt_view` already caught a rendering failure and fell back to
  an empty body, but then cached that empty string for the full timeout;
  for `/robots.txt` an empty body means "allow everything", the opposite
  of a restrictive ruleset that failed to render. A render failure is
  still served (as an empty body) but is no longer cached. Out of scope:
  `sitemap_index_view`'s storage calls are already wrapped in a broad
  `except Exception` ending in `Http404` and were not touched; the
  genuinely unguarded storage escapes are in `generate_section` and
  `delete_section` (commands/tasks, not views) and are left for a
  follow-up.

- **ads.txt and app-ads.txt output was injectable via a stored newline**
  (#18). `render_ads_txt` interpolated `AdsEntry.domain`, `publisher_id`,
  `certification_id` and `comment` into output lines with no CR/LF
  handling, so a value containing a newline injected extra records into
  the rendered file. Defended at both the write boundary and the render
  boundary, because a bad row can reach the renderer regardless of how it
  got there (a database populated before this fix, or any write path that
  bypasses application-level checks). On write, `add_ads_entry()` rejects
  a newline in `domain`, `publisher_id`, `certification_id`, `comment`,
  and now also any string passed through its documented `**kwargs`
  passthrough, with a `ValueError`, matching the existing behaviour of
  `add_robots_rule()`. Because `add_ads_entry()` is only one way to create
  an `AdsEntry` (admin saves, `AdsEntry.objects.create()` and
  `bulk_create()` all bypassed it), the same check is now also enforced on
  the model itself: `domain`, `publisher_id`, `certification_id` and
  `comment` each carry a `RegexValidator`, and `AdsEntry.clean()` raises a
  `ValidationError` naming the offending field. A migration
  (`0007_ads_entry_newline_validators`) adds the new field validators. On
  render, `render_ads_txt()` now checks each entry's fields before
  emitting its line: a row with an embedded newline is skipped (not
  stripped, which would silently turn a forged record into a differently
  shaped, valid-looking one) and a warning is logged naming the entry so
  an operator can find and fix it.

- **BREAKING:** **Empty ads.txt / app-ads.txt served a zero-byte body** (#22). IAB
  ads.txt v1.1 s3.2.1 deprecated the empty-file method for declaring "no
  authorised sellers": it "should be ignored by consuming systems after
  March 1, 2020". `render_ads_txt()` now emits the IAB placeholder record
  (`placeholder.example.com, placeholder, DIRECT, placeholder`) when there
  are no active entries for the tenant and file variant, for both ads.txt
  and app-ads.txt. Set the new `ICV_SITEMAPS_ADS_TXT_EMPTY_PLACEHOLDER`
  setting to `False` to restore the previous empty-body behaviour.

- **BREAKING:** **security.txt accepted any content, including a blank file,
  with neither of RFC 9116's mandatory fields enforced** (#20).
  `DiscoveryFileConfig.content` was an opaque `TextField` and
  `set_discovery_file_content()` did no validation and did not dispatch on
  `file_type`. Saving `file_type="security_txt"` content now requires at
  least one `Contact` field (RFC 9116 s2.5.3) and exactly one `Expires`
  field (RFC 9116 s2.5.5) whose value is a well-formed RFC 3339 timestamp;
  a violation raises a `ValueError` naming the problem, and the write is
  rejected rather than saved. `llms_txt` and `humans_txt` content is
  unaffected: no standard mandates their shape, so they are not validated.
  Expiry is not checked at read time and signing (`Signature`, an RFC 9116
  SHOULD, not a MUST) is not implemented; both are out of scope for this
  fix.

- **The sitemap index's `<lastmod>` reported when a shard was last
  generated, not when its content last changed** (#19). `SitemapFile`
  rows are deleted and recreated on every run, and `generated_at` was
  `auto_now_add=True`, so the index timestamp advanced to "now" on every
  regeneration, including the daily forced `regenerate_all_sitemaps` run,
  even when nothing in the shard had changed. Search engines only trust
  `lastmod` when it is consistently accurate, so this made the signal
  worthless or actively misleading. `generate_section()` now compares
  each regenerated shard's checksum against the previous row for the same
  `(section, sequence)`, computed before the delete-and-recreate; when the
  checksum is unchanged the prior `generated_at` is carried forward,
  otherwise it is stamped with the current time as before. A shard whose
  sequence number is reused for genuinely different content (for example
  a section that shrinks and reflows its shards) is not affected, since
  its checksum will differ. Per-URL `lastmod` in section sitemaps was
  already correct (sourced from the model's `updated_at`) and is
  unchanged. `SitemapFile.generated_at` changed from `auto_now_add=True`
  to an explicitly settable `DateTimeField` (migration
  `0006_alter_sitemapfile_generated_at`) so the carried-forward value is
  not silently overwritten on create.
- **BREAKING:** **`robots.txt` now emits rules in RFC 9309 longest-match
  order, not author-declared order** (#21). Within each `User-agent` group, `Allow`
  and `Disallow` rules are sorted by descending path-pattern length, with
  `Allow` winning an exact-length tie, matching what every conforming
  crawler already does when it parses the file. This changes emitted
  output only for rule sets where the `order` field and longest match
  already disagreed; in that exact situation the previous output was not
  what a crawler would apply, so this is a correctness fix rather than a
  behaviour change for rule sets without overlapping paths. `order` still
  has a real job: it is now the tiebreaker between rules of equal
  specificity, and `RobotsRule.order`'s help text has been reworded to
  describe that (a new migration, `0008_alter_robotsrule_order`, ships the
  `help_text` change).

- **User-agent groups now fold case-insensitively** (#21), per RFC 9309's
  requirement that the product token is case-insensitive and that multiple
  groups matching one user agent be combined into one. `Googlebot` and
  `googlebot` rules previously rendered as two separate `User-agent`
  blocks; they now render as a single group, under the first-seen
  spelling.

### Upgrading from 1.0.0

This is a major version because five fixes change behaviour for an existing
consumer with no code change on their side. Nothing in the package's own API
signatures is incompatible: `check_redirect` gained a keyword-only argument
with a default that preserves its previous behaviour, and every other public
function keeps its signature. What changed is that invalid input is now
rejected and non-conformant output corrected, which is visible to anyone
relying on the previous behaviour.

Read these five before upgrading.

1. **A `security.txt` write that was previously accepted may now raise**
   (#20). `set_discovery_file_content()` with `file_type="security_txt"`
   now requires at least one `Contact` field and exactly one `Expires`
   field holding a valid RFC 3339 timestamp, and raises `ValueError`
   otherwise. If you write security.txt content programmatically, check it
   satisfies both before upgrading, or catch the `ValueError`. Existing
   rows already in the database are not validated retroactively and are
   served as they are; only new writes are checked. `llms_txt` and
   `humans_txt` are unaffected.

2. **A path that returned 410 may now return 200** (#17). A 410 rule is
   now evaluated only after the urlconf has failed to resolve the path, so
   a stale "gone" rule no longer shadows a URL a view legitimately serves.
   If you were relying on a 410 rule to take a live page out of service,
   that no longer works: deactivate or delete the view's route instead.
   A 410 rule for a path that genuinely does not resolve behaves exactly
   as before.

3. **A different redirect rule may now win** (#24). Match type now takes
   precedence over `priority`: an exact rule always beats a prefix rule,
   which always beats a regex rule, and `priority` only orders rules
   within one match type. Previously `priority` alone decided, so a broad
   low-priority prefix rule could beat a specific exact rule. If you tuned
   `priority` values to work around the old ordering, re-check them.

4. **robots.txt output ordering changed** (#21). Within each `User-agent`
   group, rules are now emitted in RFC 9309 longest-match order rather
   than author-declared order, and groups whose user-agent tokens differ
   only by case are folded into one. The set of rules is unchanged and
   conformant crawlers apply longest-match regardless of order, so this
   should not change what any crawler does. It will change your rendered
   robots.txt byte-for-byte, which matters if you assert on its exact text
   or diff it in a deploy check.

5. **An empty ads.txt or app-ads.txt now serves a placeholder record**
   (#22) rather than a zero-byte body, per IAB ads.txt v1.1 s3.2.1, which
   deprecated the empty-file method of declaring "no authorised sellers".
   The body becomes `placeholder.example.com, placeholder, DIRECT,
   placeholder`. Set `ICV_SITEMAPS_ADS_TXT_EMPTY_PLACEHOLDER = False` to
   restore the previous empty-body behaviour.

Two further changes are safe but worth knowing about:

- **The redirect rule cache key moved from `v2` to `v3`** (#16) because the
  cached payload no longer contains exact-match rules. No action is needed:
  a stale `v2` entry is ignored and the list is rebuilt under the new shape
  on first read. If you invalidate the cache by key from outside the
  package, update the key.
- **No migration is required.** Nothing in this release changes the
  database schema. The last schema change was
  `0008_alter_robotsrule_order` in 1.0.0.

## [1.0.0] - 2026-08-09

### Fixed

- `icv_sitemaps_generate` did not forward `--force` to the generation
  service (#6). `_run_generation()` called `generate_section(section)`
  without the `force` keyword, so `generate_section()`'s own staleness
  guard fired regardless of what the command line asked for: a forced run
  against a section that was already up to date printed a success summary
  and regenerated nothing. Affected both `--section NAME --force` and
  `--all --force` (the previously-published test covering `--force` only
  asserted on log text, which the bug did not change, so it did not catch
  this). `force` is now forwarded through `_generate_section()` to
  `_run_generation()` to the service call.

- **A failed sitemap replacement upload no longer deletes the previous
  published file** (#5, BR-006). Publishing deleted the file at the final
  storage path and only then re-uploaded from the staged copy, unconditionally:
  a staged upload that failed, or landed truncated or corrupt, was promoted
  anyway, destroying the last known-good sitemap for no working replacement.
  The docstring's atomicity claim ("write to a temporary path, then rename")
  was also inaccurate: generic Django `Storage` has no rename primitive. The
  new strategy depends on what the storage backend actually supports: a
  backend that overwrites in place (S3 with `AWS_S3_FILE_OVERWRITE=True`,
  `FileSystemStorage(allow_overwrite=True)`) gets a single `save()` with no
  delete-then-save window at all; a generic backend stages and verifies
  (existence and size) the new content at `path + ".tmp"` before ever
  deleting the previous file, so a failed or corrupt staged upload leaves
  the previous file completely untouched. Applies to both section files
  and the sitemap index. A narrow window between the final delete and save
  remains an inherent limitation of generic `Storage` on backends that do
  not overwrite; this is no longer claimed to be fully atomic there, only
  that a failed *upload* cannot destroy the previous file.

### Upgrading from 0.7.x

Consumers jumping straight from 0.7.x to 1.0.0 apply the following schema
change, introduced in the intermediate 0.8.0 release and easy to miss
without reading that entry:

- `0005_sitemapsection_section_type_and_more` (0.8.0): adds
  `SitemapSection.section_type` and widens `model_path` to
  blank-by-default.

This change is safe to apply: `section_type` carries a default
(`"model"`), so existing rows need no backfilling, and `model_path` only
widens (from required to blank-by-default), so no existing value is
narrowed or rejected.

## [0.8.0] - 2026-07-19

### Added

- Static-URL section type (#2): `SitemapSection.section_type` (`model` or
  `static`, default `model`). A `static` section sources its `<loc>` URLs
  from `settings["url_provider"]` (a dotted path to a no-argument callable
  returning entry dicts, resolved via `import_string`) or an inline
  `settings["urls"]` list, rather than a Django queryset. `url_provider`
  takes precedence when both are present. Covers pages with no model
  behind them (homepage, pricing, marketing landing pages).
- `create_section()` accepts `urls` and `url_provider` keyword arguments to
  create a static section programmatically; mutually exclusive with
  `model_class`.
- `ICV_SITEMAPS_AUTO_SECTIONS` entries accept `"section_type": "static"`
  with no `model` key; `icv_sitemaps_setup` creates these without
  resolving a model, and `connect_auto_section_signals()` skips them
  silently (a static section has no model to hang `post_save`/
  `post_delete` on).
- `StaticSitemapSectionFactory` in `icv_sitemaps.testing`.
- Migration `0005_sitemapsection_section_type_and_more` adds `section_type`
  and widens `model_path` to blank-by-default.

### Changed

- `SitemapSection.model_path` is now blank-by-default (`default=""`,
  `blank=True`) instead of required, since static sections have no model
  path. `SitemapSection.clean()` enforces the `section_type`/`model_path`
  relationship: a `model` section requires `model_path`; a `static`
  section forbids it.
- `_generate_streaming`/`_generate_buffered` now take an entries iterable
  directly rather than building it internally from a queryset, so both
  model-backed and static sections reuse the same writer, sharding, gzip,
  and index code unchanged.

## [0.7.0] - 2026-07-09

### Added

- Squashed migration `0001_squashed_0004_redirectlog_redirectrule` replacing 0001 to 0004. Existing
  databases that applied the original series are unaffected (Django
  no-ops through the `replaces` list); fresh installs apply the single
  squashed migration. The replaced originals remain in the package and
  will be removed in the next major release once all installations have
  passed the squash point.

### Changed

- Minimum Django is now 5.2 (was 5.0). Django 5.2 and 6.0 are the
  supported and CI-tested versions.
- Packaging: the build backend now requires setuptools 77+ (PEP 639
  SPDX licence metadata) and no longer lists wheel; project URLs point
  at the icvoss GitHub organisation.

## [0.6.1] - 2026-07-01

### Fixed

- Pre-gzipped `.gz` sitemap files are no longer served with a
  `Content-Encoding: gzip` header. They are now served as an opaque gzip
  download (`Content-Type: application/gzip`) with no `Content-Encoding`
  header, per Google's documented approach for gzipped sitemaps.

  Setting `Content-Encoding: gzip` on a `.gz` entity marks the body as
  *transport*-compressed, so a fetcher inflates it once at the HTTP layer.
  Small sitemaps decoded fine, but large product sitemaps (~1.5 MB
  compressed inflating to ~24 MB, a ~16x ratio) tripped Googlebot's
  transport-decompression safety cap and returned "Couldn't fetch", while
  smaller sitemaps in the same index (brands, categories, merchants) read
  successfully. Serving the `.gz` as an opaque file lets Google decompress
  it as a sitemap (no transport-inflation cap), and the 50,000-URL /
  ~23 MB products files parse correctly. Affects the sitemap index view and
  the individual sitemap file view.

## [0.6.0] - 2026-06-24

### Fixed

- `generate_section` no longer masks generation failures. A storage upload
  error (or any exception during generation/persistence) previously propagated
  out leaving the `SitemapGenerationLog` stuck in `running`: no failure
  recorded, no signal, and the section never marked fresh. Generation is now
  wrapped so the log is marked `failed` with the error detail, a new
  `sitemap_section_generation_failed` signal is emitted (provides `instance`,
  `error`, `detail`), and the exception is re-raised so callers and Celery see
  it.
- The "Create 410 Gone rule from selected 404s" admin action no longer
  silently swallows per-row failures (`except Exception: pass`). Each failed
  conversion is now logged at `WARNING` and the operator is shown a
  warning-level message with the failure count, instead of only a success
  count that hid the failures.

### Added

- `sitemap_section_generation_failed` signal: fired when section generation
  fails.

## [0.5.1] - 2026-04-16

### Fixed

- **Memory leak on large sections**: Django model instances form
  reference cycles (`_state`, descriptor caches, deferred attrs) that
  CPython's generational GC promotes to gen-2. On multi-million-row
  sections these zombie cycles accumulated faster than gen-2 collection
  ran, causing monotonic RSS growth (observed 10.8 GB on a 2.4M-row
  products section). Fixed by:
  - explicitly `del`-ing the chunk list after extracting entries, so
    5000 model instances + their prefetch caches are released before
    the next DB fetch instead of lingering in the generator frame
  - calling `gc.collect()` every 10 chunks (~50K rows) to flush
    ref-cycles promoted to gen-2 before they pile up
  - calling `reset_queries()` each chunk to prevent any residual
    query-log growth (safe even when `DEBUG=False`)

## [0.5.0] - 2026-04-16

### Performance

- **Streaming XML writer**: `generate_section()` now serialises entries
  directly to a local temp file as they are extracted, instead of
  accumulating up to `ICV_SITEMAPS_MAX_URLS_PER_FILE` dicts in memory and
  building an ElementTree at flush time. Per-section peak memory drops
  from ~1.4 GB to between ~50 and 100 MB on 50K-URL shards, and per-file generation
  time is flat instead of degrading as the run progresses. The finalised
  temp file is uploaded once to the configured storage backend at file
  boundary, preserving atomic-swap semantics and working uniformly across
  local FS and remote (S3, Spaces, GCS) backends.
- Per-entry byte renderers replace the ElementTree-based builders,
  removing per-row object overhead.

### Added

- `ICV_SITEMAPS_STREAMING_WRITER` setting (default `True`). Set to
  `False` to fall back to the buffered code path if needed; both paths
  produce equivalent output.

### Fixed

- Image and video sitemaps no longer emit duplicate `xmlns:image` /
  `xmlns:video` declarations on the root `<urlset>` element. The
  streaming writer hand-writes the header, avoiding ElementTree's
  `register_namespace()` interaction that caused the duplicate attr.
- All XML output is now explicitly escaped via `xml.sax.saxutils.escape`
  at render time.

## [0.4.2] - 2026-04-14

### Fixed

- All views now accept `HEAD` requests: replaced `@require_GET` with
  `@require_http_methods(["GET", "HEAD"])` on all 8 view functions.
  `HEAD` is required by the HTTP spec wherever `GET` is accepted, and
  monitoring tools and crawlers commonly use it.

## [0.4.1] - 2026-04-14

### Fixed

- `RedirectRuleAdmin`: added `list_display_links` to fix Django admin check
  error when `priority` is both first in `list_display` and in `list_editable`
- Ruff format and lint compliance for all new files

## [0.4.0] - 2026-04-14

### Added

- **Redirect and 410 management**: database-driven URL redirects with
  `RedirectRule` model supporting exact, prefix, and regex matching, priority
  ordering, expiry, hit tracking, and multi-tenant scoping
- **404 tracking**: `RedirectLog` model aggregates recurring 404 paths with
  hit counts and top referrers for redirect intelligence
- **RedirectMiddleware**: opt-in middleware (`ICV_SITEMAPS_REDIRECT_ENABLED`)
  evaluates redirect rules before URL resolution, serves 301/302/307/308/410
  responses, and tracks 404s with configurable sampling and ignore patterns
- Redirect rule cache with signal-based invalidation (5-minute TTL)
- `add_redirect()`, `check_redirect()`, `bulk_import_redirects()`,
  `record_404()`, `get_top_404s()` service functions
- `redirect_rule_saved`, `redirect_rule_deleted`, `redirect_matched` signals
  for cross-package integration (e.g. WAF, taxonomy move tracking)
- `RedirectRuleAdmin` with priority, hit count, and status filtering;
  `RedirectLogAdmin` (read-only) with "Create 410 Gone" admin action
- `icv_sitemaps_redirects` management command: list, import/export CSV,
  prune expired rules, show top 404s
- `cleanup_expired_redirects` and `cleanup_redirect_logs` Celery tasks
- `RedirectRuleFactory` and `RedirectLogFactory` test factories
- 5 new settings: `ICV_SITEMAPS_REDIRECT_ENABLED`,
  `ICV_SITEMAPS_REDIRECT_CACHE_TIMEOUT`, `ICV_SITEMAPS_404_TRACKING_ENABLED`,
  `ICV_SITEMAPS_404_TRACKING_SAMPLE_RATE`, `ICV_SITEMAPS_404_IGNORE_PATTERNS`
- Migration `0004` generated on Django 5.2
- 49 new tests (263 total)

## [0.3.0] - 2026-04-14

### Added

- `Crawl-delay`, `Sitemap`, and `Host` directive choices for `RobotsRule`:
  these directives can now be stored in the database instead of requiring the
  `ICV_SITEMAPS_ROBOTS_EXTRA_DIRECTIVES` config fallback
- `add_robots_rule()` service accepts all valid robots.txt directives; path
  validation only enforced for `allow`/`disallow`

### Changed

- `RobotsRule.directive` field widened from `max_length=10` to `max_length=20`
  to accommodate `Crawl-delay` (11 chars) with headroom
- Migration `0003_alter_robotsrule_directive` generated on Django 5.2

### Fixed

- **Sitemap generation drops connection on large querysets**: replaced single
  `queryset.iterator()` with keyset pagination (`pk__gt` batching) and
  `close_old_connections()` between chunks. The old approach held a single
  server-side cursor across millions of rows, which managed Postgres providers
  (e.g. DigitalOcean) kill via SSL/idle timeouts. Each batch now issues a
  fresh short-lived query.

## [0.2.3] - 2026-03-25

### Fixed

- `SitemapSection.settings` JSONField now has `blank=True`: fixes admin form
  validation error when saving a section with an empty `{}` settings field
- Added migration `0002` for `settings` (`blank=True`) and `model_path`
  (help_text updated to `app_label.ModelName` format)

## [0.2.2] - 2026-03-25

### Changed

- **BREAKING:** `ICV_SITEMAPS_PING_ENABLED` now defaults to `False` and
  `ICV_SITEMAPS_PING_ENGINES` defaults to `[]`; Google and Bing have retired
  their sitemap ping endpoints. Projects that still need pinging must opt in
  explicitly.

### Fixed

- Resolved remaining ruff SIM117 lint violations in test suite (combined nested
  `with` statements)
- Fixed import ordering in initial migration

## [0.2.1] - 2026-03-25

### Security

- `_resolve_model()` now uses `apps.get_model()` exclusively; removed
  `import_string()` fallback that allowed arbitrary module imports
- File size check before reading sitemap files in views (prevents memory
  exhaustion on oversized files)
- Tenant ID regex validation in `_get_tenant_id()` view helper
- Newline injection prevention in `add_robots_rule()` service
- URL scheme validation in `ping_search_engines()` (rejects non-HTTP URLs)
- Replaced `assert` with `if`/`raise RuntimeError` in setup management command

### Added

- Conditional ping based on SHA-256 checksum comparison of sitemap index
- Empty section handling: writes valid empty `<urlset>` XML
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
- `httpx` dependency (was unused; pinging uses `urllib.request`)

## [0.1.2] - 2026-03-24

### Added

- Initial database migration (`0001_initial`): previously missing from the
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
