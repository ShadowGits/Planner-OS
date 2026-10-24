# Ten-minute task reminders

PWA/web push and native Android schedule one task reminder ten minutes before start. The task name is the primary title. Android's expanded notification includes the full name, followed by timing; web push includes the full name in the body to keep long subjects available when the system truncates the heading. Telegram fallback includes the task name too.

Android uses the wine accent `#722F37`. System UI still controls the notification background and text contrast. PWA notifications have no standard background-color setting; their appearance is controlled by the browser and OS. No foreground service or media-notification workaround is used to force a background color.

The old 30/5-minute alarms are cancelled on the first setup after upgrading. A policy epoch rejects old in-flight workers, and old alarm kinds are rejected even before setup. Local alarms and native polling share `event10:<task id>` and the same delivery-date ledger, preventing the two paths from repeating the same alert. No five-minute or starting-now fallback is created. Daily brief/deadline notifications keep their existing rules.

The server checks a bounded 9–10-minute window and supports exact-minute starts and pre-midnight reminders for next-day tasks. The production Cloud Scheduler job `planner-reminders` must move from `*/5 * * * *` to `* * * * *`. After release approval, deploy the code first, then update only this job's schedule, preserving its target, authentication and time zone. No SQL migration is required; migration 0026 already permits per-event reminder kinds. Web push and native Android subscriptions remain independent, so enabling both on the same phone can produce one alert from each app.

Validation: clean release snapshot has 321 backend tests passed and one skipped, 109 PWA tests passed, and 112 Android unit tests passed. APK assembly and lint passed with zero errors. The existing MCP export coverage test was corrected to classify the UI-only project picker helper as an intentional omission, after reproducing that failure on unchanged HEAD. Tests cover the single ten-minute window, idempotency, no 30/5/start follow-up, full long task names, habits/completed-task filtering, midnight delivery dates and DST. Physical-device presentation still depends on system notification settings.

Prepared Android 1.0.20/code22, SHA256 `6c5640cddda00b85bdebb5fc91b9c283cb6a4e72aa47dcb4eff3234bd1014c8b`. Publication and latest-app folder delivery await fresh human approval. Separate Day Recovery and unrelated PWA stylesheet changes are excluded.
