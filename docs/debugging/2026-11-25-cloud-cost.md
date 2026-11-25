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

In progress: projected project/milestone reads, bounded reminder feed,
120-second refresh minimum, future-agent rules and query/storage regressions.
Monthly target requested by user: 60–70% of CPU/request free allowances; see
`../query_budget.md`. No production CPU savings verified until deployment and
updated app installation. Add final test/commit results here before delivery.
