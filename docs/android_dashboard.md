# Android Inbox and Dashboard

Android 1.0.6 uses a single-line date header. Inbox hides the calendar strip and Top Wins, groups overdue and unscheduled work into flat rows, and shows selected-day completion. Open, Overdue and Done filters retain completion, editing and scheduling actions. Done includes completed timed tasks from the selected day.

Dashboard opens in a separate Activity. Overview, Week, Projects, Study, Books, Habits, Money and Germany use native scrolling lists and detail sheets. Every project remains accessible through Projects, with Tasks, Milestones, Monthly goals, Weekly goals, Q&A, Widgets and Files. Finance opens its funding plan directly. Week and Money summary support period navigation. Widget notes and stored tables render in the detail sheet.

Dashboard is a progress and browsing view. Web widget/table editing, uploads, Calendar connection and Drive document editing have not been ported. Files and record links open their source applications. Trackers missing from the existing database show “Tracker not set up”; this release does not create tables or apply database migrations.

Dashboard performs no preloading from Day. It owns two Android network workers, separate cache preferences, a five-minute cache lifetime, and its own loading/error state. Cached data is scoped to the connection generation and reminder schedule revision, so successful Day task changes invalidate old progress. The API uses a separate two-thread worker pool for `/v2/native/dashboard`, with tenant-scoped reads, fixed section/table allowlists and 100-row pagination. Read failures are distinguished from empty trackers.

Verification includes Android unit tests and lint, backend authentication/scoping/pagination tests, a blocked Dashboard request concurrent with a successful Day request, and emulator checks of Inbox completion, normal light mode and 320dp dark mode with 150% text. Live checks exercise every Dashboard section and Day without modifying production data.

The backend deployment is built from the committed production source plus the native Dashboard route. The separately proposed PWA day-recovery changes and migration 0033 are not part of this deployment.
