package dev.planneros.android

import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId

/** Both lead times replace the same task notification, while delivery kinds stay distinct. */
fun reminderNotificationTag(kind: String): String =
    if(kind.startsWith("event30:") || kind.startsWith("event5:")) "event:" + kind.substringAfter(':') else kind
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
    return listOf(30,5).mapNotNull { lead ->
        val trigger=start-lead*60_000L
        if(trigger<=nowMillis)null else TaskReminderAlarm("$day:event$lead:$taskId",day.toString(),
            "event$lead:$taskId","${if(lead==30) "🟡" else "🟢"} IN $lead MINUTES : $title",
            "Starts at %02d:%02d · %d min".format(clock.hour,clock.minute,duration),trigger)
    }
}
