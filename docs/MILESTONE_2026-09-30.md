# Planner OS repair milestone — 2026-09-30

## Web/backend checkpoint

Calendar reconciliation now reads all Google event pages and all database rows,
retains the mapped canonical event when duplicates exist, uses deterministic
Google IDs for inserts, and refuses destructive reconciliation after incomplete
reads or failed writes. Permission failures no longer mean “event missing”, and
personal events cannot be adopted through an incorrect saved mapping.

Security fixes cover OAuth confirmation HTML/redirect validation, atomic token
redemption, tenant/reference isolation, project file ownership, private Drive
sharing, push endpoint restrictions, and safe service-worker caching. Atomic
OAuth redemption was verified against the existing production database without
requiring a migration. Unused vulnerable standalone FastMCP was removed; the
application uses the MCP SDK's FastMCP. Production Python dependencies are
audited and pinned in requirements.lock; the npm lockfile is updated too.

The PWA retains its Structured-style timeline, gestures, inbox, stars, split
sessions and notifications. It adds active-block navigation, day progress,
usable timeline bounds and accessible sheets, and fixes todo scheduling and
stale completion/duration state.

Validation: 253 Python tests passed (one optional dependency test skipped),
39 PWA JavaScript tests passed, and real Chrome checks passed at 320px, 390px
light/dark, and 1024px. The clean production Python dependency audit found no
known vulnerabilities. npm dependency audit, production build, TypeScript
checking and lint all pass; npm reports zero production or development
advisories and lint reports zero errors/warnings.

## Live cleanup

Audit found 7,728 events in 2026–2027, including 7,325 Planner OS-owned events.
779 blocks had duplicate copies; 5,710 excess copies were queued for removal.
Every affected block had a saved canonical mapping, which is retained. The
hourly calendar sync was paused temporarily during cleanup/deployment. Private
event backup and cleanup results are stored in the ignored .planner-os folder.

Existing Drive public-writer grants could not be fully audited: the live
project_files tracking table is unavailable and projects have no saved Drive
folder IDs. Preventive sharing fixes are implemented; unverified manual files
are not altered. scripts/harden_security.py can audit known IDs when tracking
is available.

## Android checkpoint

Native Kotlin/Compose app source is in android/, targeting Android 16 (API36).
It uses the same backend, caches day views, and provides task editing and a
persisted foreground focus timer with a draggable overlay, pause/resume and
overtime. The new /v2/native/reminders feed preserves the existing reminder
rules with per-device deduplication.

The initial installable APK compiled, passed seven timer tests, had no lint
errors, and installed/launched in an Android16 ARM emulator. The user selected
a bright-white interface with colorful pastels; that revision and final live
verification are the next checkpoint. Physical Samsung S24 Ultra validation
remains necessary for One UI background restrictions and overlay behavior.

Future APK updates must use the retained private signing key. Account keys,
SDK files and signing keys are never committed. See android/README.md for
installation and permission steps.
