# Preserve both local feature sets

The cost rollout initially installed a build missing newer uncommitted Apple
features from `.claude/worktrees/charming-williamson-b7222d`. This was a regression,
not an authorized feature removal. The user explicitly requested merging both.

The original checkout remains untouched. A byte-for-byte snapshot and source
hash manifest were saved under `/tmp/planner-preserve-worktree-snapshot` before
integration. Do not clean, reset, stage or commit that source checkout.

Restored its compact floating clock, shrink/expand controls, saved size, vacancy
and next-task display, drag-anywhere behavior, pinned Top Wins, gap presentation
and five-minute gap actions, empty-day messages, pull refresh, status-bar
navigation, untimed-task menus, current/next-task navigation, first-task date
navigation, viewport stabilization, gesture timing and duration/work labels.
Copied its existing policy and kept-feature UI regressions.

Preserved the cost changes: one store-owned network loop, 120-second minimum
automatic refresh, fresh/coalesced date reads, scoped after-edit reconciliation,
project/milestone projections, bounded reminder feed, strict read failures,
background refresh and three-day image retention. The clock's older private
network loop is intentionally replaced by the shared loop; its UI is restored.

Pending-gap integration uses the restored gap's actual end and five-minute
rounded start to open the existing task sheet and pending picker. The picker
still moves the original task and revalidates completion and occupied space.

Dedicated Mac UI tests exercise actual shrink/expand and drag-from-tick behavior.
Only those tests enable the clock panel while using the in-memory test server;
ordinary UI tests keep the panel hidden. Tests restore the initial clock size
and position. Production clock preferences remain in the existing defaults keys.

Verification results and install evidence will be appended after the combined
tests finish. No local Xcode signing or unrelated Day Recovery files belong in
this change.

## Verification and user-directed rollout

- iOS: 20 combined UI tests passed (15 kept-feature, 5 pending-gap).
- Mac: all 10 kept-feature and all 5 pending-gap UI tests passed.
- Policy and pending-slot rule checks passed using isolated test storage.
- All 17 background/request-count checks and 14 cost/storage regressions passed.
- Signed physical-iPhone and Mac builds compiled successfully.
- Dedicated clock dragging passed with the original clock implementation. The
  newly added position-preservation check failed; this is not a fully green
  clock suite. User explicitly instructed deploying first and leaving that
  check pending. Experimental resize changes were reverted to preserve the
  original compact-clock implementation. Do not claim the position check passed.
- Source checkout hashes remained unchanged throughout integration. Local Xcode
  signing and unrelated unfinished Day Recovery files remain excluded.
