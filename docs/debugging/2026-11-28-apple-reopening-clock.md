# Floating clock visibility and reopening at the current time

## Requests and observed state

The user reported the Mac floating clock had disappeared and requested that
both Mac and iPhone open at the current time instead of their last timeline
position. The preceding deployment (`4eaf3e4`) changed only server habit-save
handling, tests and its investigation; it did not replace the Apple app.

The installed Mac app was the November 25 build, bundle
`dev.planneros.planner`, display name `Planner OS`, internal build 2.
Window metadata showed its compact clock still running at Quartz bounds
`x=1004, y=-218, width=268, height=40`. The laptop display was
`x=0...1280, y=0...832`; the external display started at `x=1280` and extended
up to `y=-68`. The clock intersected neither display despite being marked
onscreen by WindowServer. No screen pixels, private tasks or credentials were
captured. Reading the app's protected preferences was denied by macOS; no
privacy setting was changed to bypass it.

Gracefully reopened the existing installed app, without replacing it or
resetting preferences. After its exit completed, a second launch was needed
because the first launch returned Apple Event error -609. The compact clock
then appeared on the external display at `x=2924, y=-38, width=268, height=40`.

## Implementation

- The Mac clock now checks full containment within a display's visible area
  when updating. Display configuration, app activation and wake notifications
  invoke that same local update. Valid positions and the visibility/compact
  preferences remain intact; no network loop was added.
- Preserved the existing clock appearance, hosting view, compact toggle,
  anchored-resize implementation and drag behavior. An experiment with hosting
  sizing options did not resolve the previously known 88-point resize drift
  assertion and was reverted; it is excluded from the update.
- Opening the main view and returning to the app request today's actual clock
  minute. iPhone waits for a real background/foreground transition; Mac uses
  its app activation notification, because scene-phase handling alone failed
  the app-switching UI regression. The existing Now button still targets the
  current/next task, and selected-date navigation remains available during use.
- An editor, milestone sheet, delete confirmation or active drag prevents the
  reopening action from disrupting the current operation. The chosen list
  preference is retained. Ordinary tab changes retain their existing behavior.
- Existing refresh freshness/coalescing and the store-owned 120-second network
  budget remain unchanged. This update does not certify monthly cloud usage.

## Preservation and verification setup

Inspected all available Git worktrees and their uncommitted changes. The
preserved checkout's timeline scroll implementation matches this checkout;
other source differences include already-integrated cost and kept-feature
changes. This fix edits the current implementation in place; it does not
replace those files from an older checkout. Local Xcode signing and unrelated
unfinished Day Recovery files are excluded from commits.

Built simulator and Mac UI tests from a temporary project with bundle prefix
`dev.planneros.currenttimetests`. The test app is separate from the installed
user app. Fake-data server port 8879 is reserved for UI tests and port 8880
for the independent refresh harness; test resets never target production.
The debug-only offscreen fixture is gated on an actual UI-test connection.

The user explicitly objected to repeated screen takeovers during preparation.
All screen-control tests are stopped. Finish code, noninteractive checks and
signed builds in the background, then use at most one final approved screen
session. Do not resume GUI tests piecemeal. No updated Apple app has been
installed yet.

## Validation completed without further screen control

- Final iOS simulator and macOS `build-for-testing`: succeeded. These commands
  compile the test bundles but do not run them or open either app.
- Actual Mac and iPhone development-signed builds: succeeded. Verified both
  signatures with `codesign --verify --deep --strict`, unchanged bundle
  `dev.planneros.planner`, display name `Planner OS`, internal build 2, and the
  same signing team as the installed Mac app. Nothing was installed.
- Cost/query and image-retention regressions: 14 passed.
- Policy and pending-slot rule harnesses: all checks passed.
- Independent refresh harness: all 17 checks passed, including the real
  store-owned timer, shared/coalesced reads, freshness, bounded reminder feed,
  old-server fallback, failure handling and drag/disconnect protections.
- Xcode project references, task-field checks, gesture checks, and
  `git diff --check`: passed.

Earlier focused Mac UI runs verified recovery from an offscreen fixture,
preservation of compact preference across relaunch, dragging from the clock's
tick without completing its task, opening at now, preserving an open editor,
and (after the native activation callback was added) returning at now after
switching apps. This does not establish final iPhone UI behavior.

The existing resize-position assertion still failed with the same 88-point
horizontal drift documented on November 25. It failed before this update's
resize experiment and was not repaired by the experiment. The experiment and
temporary geometry prints/delays were removed; the existing host and resize
implementation remain intact. Do not describe this suite as fully passing.

Final iOS UI verification and full kept-feature/pending-gap/floating-clock
suite reruns are reserved for the single final screen session requested by
the user. They have not run against the final builds. Do not claim everything
is tested or install automatically during background preparation. Ask for live
deployment approval under `.agents/AGENTS.md` when ready for that session.

Prepared artifacts and local logs:

- `/tmp/planner-current-time-prepared-builds.json`: verified artifact metadata
  and source hashes; no credentials.
- `/tmp/planner-current-time-install-mac/Build/Products/Debug/PlannerOS.app`
- `/tmp/planner-current-time-install-ios/Build/Products/Debug-iphoneos/PlannerOS.app`
- `/tmp/planner-current-time-mac-final-build.log`
- `/tmp/planner-current-time-ios-final-build.log`
- `/tmp/planner-current-time-install-mac-build.log`
- `/tmp/planner-current-time-install-ios-build.log`

No Git push or cloud deployment is part of this Apple preparation. Publishing
Apple-only changes through the current main trigger would unnecessarily start
another backend build; request publication separately if it is wanted.
