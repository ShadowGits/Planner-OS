# Cloud cost investigation — 2026-11-25

## Evidence

Project: `planner-os-502107`. User billing report: Artifact Registry costs start
November 3; Cloud Run costs rise November 22; Cloud Storage is ₹0. Screenshot
shows approximately ₹10 on November 22 and ₹24–26/day November 23–24, including
registry storage. Actual invoice/SKU export was unavailable; do not present
catalog-based estimates as verified billed totals.

Monitoring captured November 25 09:10 UTC: October 140,256 allocated CPU seconds
and 35,218 requests; November to capture 207,457 seconds and 89,196 requests.
The nominal 180,000 CPU-second allowance was crossed around November 22
17:06 UTC, assuming the entire shared billing-account allowance was available.

Hourly monitoring buckets grouped by UTC end date (approximately daily):

| November | CPU seconds | Requests |
| --- | ---: | ---: |
| 20 | 5,688 | 1,551 |
| 21 | 6,601 | 3,302 |
| 22 | 7,449 | 4,711 |
| 23 | 9,869 | 9,502 |
| 24 | 10,486 | 8,289 |

The allowance crossing explains when CPU billing begins. It does not explain
the increased work: request and CPU usage also rose.

## Code changes near the increase

- `4a6f126` (November 22): scrolling multi-day timeline adds `showDays`, day reads
  as dates enter view, and visible-date rereads during refresh and after writes.
  `showDays` loads entering dates even if already cached, without a freshness
  check or shared in-flight request.
- `24d46e4` (November 22, deployed around 15:36 UTC): floating Mac clock adds
  its own one-minute loop calling `refreshIfStale` even after the main window
  closes. The threshold in this revision is 90 seconds. Refresh and after-write
  work also load yesterday/today/tomorrow on Mac. The clock drawing once per
  second is local and does not itself request the API. These are concrete new
  network paths consistent with the usage rise, not an endpoint-level causal
  measurement of the entire bill.
- `ad9ee4f` (November 21 UTC / November 22 IST): reminder reports/nags change
  reminder behavior and report computation. Preserve these requested features.
- `653c1d3` installed November 24 19:17 UTC adds store-owned 60-second stale
  polling on the older feature branch. It postdates the initial billing rise;
  optimization restores a 120-second minimum.

Important: the working branch initially lacked the November 22 timeline/clock
changes. Preserve them when integrating cost fixes; do not deploy an older
branch over production and silently remove functionality.

## Storage work completed

Commit `776c8f9`: deleted 258 obsolete image versions and 60 build archives;
retained the serving image (about 91 MB compressed). Applied active three-day
registry cleanup policies and bucket lifecycle rules. Live health remained
unchanged. Seven-day bucket soft-delete recovery remains enabled; an automatic
approval review rejected disabling it. Registry storage accounting can lag
deletion. Cloud Storage was ₹0 in the user's report, so archive deletion is
housekeeping rather than the source of savings.

Catalog captured November 25: CPU ₹0.002285519/allocated second beyond the free
allowance; registry ₹9.523/GiB-month beyond 0.5 GiB. Previous 6.2875 GiB image
inventory corresponds to about ₹55/month at that rate. Remaining serving image
alone is below 0.5 GiB; builds in the three-day window and shared allowances
still matter. Taxes, other services and shared-account usage are excluded.

## Change and test log

Commit `350f03c`: projected project/milestone reads, bounded reminder feed,
120-second refresh minimum, future-agent rules and query/storage regressions.
Integrated `origin/main` (`24d46e4`) to retain the latest scrolling timeline,
floating clock, nags and daily reports. Removed the clock's duplicate network
loop; the store owns refresh even without a window. Returning to a window now
respects freshness. Shared in-flight date reads are revision-scoped and cleared
on disconnect/account changes; scrolling reuses dates fetched within 120 seconds.
Ordinary edits reconcile source/destination and loaded after-midnight copies;
split-child edits keep broader reconciliation. Restored the pending-gap picker
on the current multi-day timeline.

Validation completed against isolated in-memory fixture servers, with no
production task mutations:

- iOS simulator and macOS app/UI-test builds passed using local beta SDK
  deployment-target overrides; no local signing settings included in commits.
- Five pending-gap UI tests passed on iOS and five on macOS: create, fit existing
  with details retained, search/cancel, remote completion and conflicting booking.
- Seventeen runtime refresh/query checks passed: overlapping reads coalesce,
  fresh scrolling/early polling make no requests, one reminder feed replaces
  full-day downloads, 404 retains seven-day compatibility, errors/incomplete
  feeds propagate without fallback, unrelated dates stay cached after edits,
  remote edits update memory/disk/reminders, dragging is protected, window-free
  refresh runs, and disconnect/offline behavior remains correct.
- Backend/query/storage suite: 251 tests passed.
  Habit override/move/completion behavior matches individual day reads while
  querying each habit table once for the whole week. Reminder projections retain
  completed/untimed/due-only tasks, calendar provenance and final-night spillover.
- Xcode project references, task fields, gesture hit areas and Siri registration
  checks passed. Initial UI failures were obsolete static-text selectors on the
  new timeline; tests now use the real gap buttons and platform task labels.
- Signed physical-iPhone and Mac builds also succeeded; both bundle signatures
  passed verification and retain display name `Planner OS` and bundle ID
  `dev.planneros.planner`. Prepared bundles are under
  `/tmp/planner-query-install-ios/Build/Products/Debug-iphoneos/PlannerOS.app`
  and `/tmp/planner-query-install-mac/Build/Products/Debug/PlannerOS.app`.
  These builds have not been installed and the backend changes have not been
  deployed. Deployment/push require explicit live chat approval per repo rules.

Monthly target requested by user: 60–70% of CPU/request free allowances; see
`../query_budget.md`. This is not yet a measured production result or a hard
service cap. No production CPU savings verified until deployment and updated
app installation. Existing November charges cannot be reversed by this fix.

## Approved rollout follow-up

After explicit user approval, pushed `e427cf7` to main. Build
`75edef31-03e9-4c62-a171-09cf574892c9` deployed revision
`planner-os-api-00301-494`, and health plus all three authenticated optimized
endpoints passed. Its final retention step failed before running the script:
the latest Cloud SDK image no longer has a system `python3` on PATH. Corrected
the runner to the SDK's documented bundled interpreter and added a regression.
Reference: Google's [container guide](https://github.com/GoogleCloudPlatform/cloud-sdk-docker/blob/master/docs/user_guide.md).
No planner-code rollback or extra app rebuild is needed for this runner fix.

Both app updates were installed. Mac launch and binary/signature verification
passed. iPhone installation succeeded wirelessly on retry; initial launch was
blocked because the device was locked. Final rollout events and exact statuses
are stored locally in `logs/cloud-cost-rollout-2026-11-25.jsonl` (ignored by Git
to avoid rebuilding/deploying just to record operational status).
