package dev.planneros.android

import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId

/** One ten-minute alert per task; legacy kinds are recognized only for upgrade cleanup. */
fun reminderNotificationTag(kind: String): String =
    if(kind.startsWith("event10:") || kind.startsWith("event30:") || kind.startsWith("event5:")) "event:" + kind.substringAfter(':') else kind
fun reminderTitle(kind: String): String = when(kind) {
    "morning_brief" -> "☀️ Morning Brief"
    "evening_nudge" -> "🌙 Evening Nudge"
    "deadline_alert" -> "⚠️ Deadline Alert"
    else -> "Planner OS"
}

data class TaskReminderAlarm(val id:String,val date:String,val kind:String,val title:String,
                             val body:String,val triggerMillis:Long)

/** Clock values denote local wall times, including the next day's spillover. */
fun taskReminderAlarms(taskId:String,title:String,clockMinutes:Int,duration:Int,dayDate:String,
                       timezone:String,nowMillis:Long):List<TaskReminderAlarm> {
    if(clockMinutes !in 0 until 30*60 || duration !in 1..1440)return emptyList()
    val day=LocalDate.parse(dayDate).plusDays((clockMinutes/1440).toLong())
    val clock=LocalTime.of((clockMinutes/60)%24,clockMinutes%60)
    val start=day.atTime(clock).atZone(ZoneId.of(timezone)).toInstant().toEpochMilli()
    val trigger=start-10*60_000L
    if(trigger<=nowMillis)return emptyList()
    val deliveryDate=Instant.ofEpochMilli(trigger).atZone(ZoneId.of(timezone)).toLocalDate().toString()
    return listOf(TaskReminderAlarm("$deliveryDate:event10:$taskId",deliveryDate,"event10:$taskId",title,
        "Starts in 10 min · %02d:%02d · %d min".format(clock.hour,clock.minute,duration),trigger))
}
