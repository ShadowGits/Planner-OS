package dev.planneros.android

/** Both lead times replace the same task notification, while delivery kinds stay distinct. */
fun reminderNotificationTag(kind: String): String =
    if(kind.startsWith("event30:") || kind.startsWith("event5:")) "event:" + kind.substringAfter(':') else kind
fun reminderTitle(kind: String): String = when(kind) {
    "morning_brief" -> "☀️ Morning Brief"
    "evening_nudge" -> "🌙 Evening Nudge"
    "deadline_alert" -> "⚠️ Deadline Alert"
    else -> "Planner OS"
}
