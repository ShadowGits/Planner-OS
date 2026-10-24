package dev.planneros.android

/** Blank means Inbox; partial or invalid clock fields must never silently unschedule a task. */
internal fun normalizeTaskTime(value:String):String? {
    if(value.isBlank())return ""
    val parts=value.split(":")
    if(parts.size!=2||parts.any{!Regex("[0-9]{1,2}").matches(it)})return null
    val hour=parts[0].toInt();val minute=parts[1].toInt()
    if(hour !in 0..23||minute !in 0..59)return null
    return "%02d:%02d".format(java.util.Locale.ROOT,hour,minute)
}
