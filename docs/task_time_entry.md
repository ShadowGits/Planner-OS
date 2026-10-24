# 24-hour task time entry

Task creation and editing now use separate Hour and Minute controls in the PWA and Android. Hour choices are 00–23. Minute dropdowns offer five-minute steps and retain an existing exact minute; typing accepts every minute from 00 through 59. Choosing an hour initializes an empty minute to 00. Clear time explicitly returns the task to Inbox. No AM/PM conversion is required.

Both clients save the existing `HH:mm` API value. Invalid or partial fields block Save rather than silently unscheduling a task. Existing project selection, task suggestions, cached tasks and the independent timers/time-logging switch are preserved. No database migration is needed.

The PWA exposes labelled editable comboboxes. Arrow keys navigate, Enter selects, Tab leaves the field, and Escape closes the dropdown before closing the editor. The dropdown is outside the scrolling sheet to prevent clipping. The Android selectors use the project's existing Material 3 dependency and numeric keyboard.

Research: [Material picker guidance](https://m1.material.io/components/pickers.html) supports compact segmented controls for inline time entry; [W3C combobox guidance](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/) defines editable selection and keyboard behaviour; [Android time input guidance](https://developer.android.com/develop/ui/compose/components/time-pickers) supports numeric time entry alongside picking. The implementation uses compact editable selectors to satisfy the requested dropdown interaction.

Validation: 111 Android unit tests passed; lint completed with zero errors. The exact clean PWA release snapshot passed 108 tests, and the working checkout passed 111 including separate Day Recovery. A local browser fixture verified selecting 14:30, typing 14:17, submitting the unchanged API payload, and reopening the persisted time. At 320px viewport width, both fields fit and the page has no horizontal overflow. Live task data was not changed during verification.

Prepared APK: 1.0.19 / code21. SHA256 `618680a5b3f82a6433e30b64e8969e90c1a4e150f2d49913ab3a8b5c7b573dfd`. Existing signing certificate retained: `8ac77cf9c1f5a6c12035a272f13e68b1c35952a75101a7a96cce9b2cd89cfa36`.

Prepared locally; publication and delivery to the synced latest-app folder await fresh human release approval required by `.agents/AGENTS.md`. Existing Day Recovery and unrelated PWA stylesheet edits are excluded from this release.
