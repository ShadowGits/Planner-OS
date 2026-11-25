package dev.planneros.android

import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId

/** Kinds that belong to one task share its notification, so each nag replaces
 * the one before instead of piling up; legacy kinds are recognized for cleanup. */
private val TASK_KINDS=listOf("event10:","event30:","event5:","start:","late:","end:")
fun reminderNotificationTag(kind: String): String =
    if(TASK_KINDS.any{kind.startsWith(it)}) "event:" + kind.substringAfter(':') else kind
fun reminderTitle(kind: String): String = when(kind) {
    "morning_brief" -> "Overdue check"
    "evening_nudge" -> "Today's report"
    "deadline_alert" -> "Deadlines"
    else -> "Planner OS"
}

/** "09:30" for any minute of the planner's day, 25:30 included. */
fun reminderClock(minutes:Int):String{val m=((minutes%1440)+1440)%1440;return "%02d:%02d".format(m/60,m%60)}

/**
 * Blunt on purpose, and the same words as the iPhone (HarshReminders.swift)
 * and the server: ten minutes before, then — until it is ticked — at the
 * start, fifteen minutes in, and when it should have ended.
 */
fun reminderLeadBody(clockMinutes:Int,duration:Int)=
    "In 10 min · ${reminderClock(clockMinutes)} · $duration min. Wrap up what you're doing."

/** The follow-ups a task gets until it is ticked, as minutes after its start.
 * A short task skips "late", which would land after it had ended. */
fun reminderNags(duration:Int):List<Pair<String,Int>> =
    listOf("start" to 0)+(if(duration>20)listOf("late" to 15) else emptyList())+listOf("end" to duration.coerceAtLeast(1))

fun reminderNagText(nag:String,title:String,clockMinutes:Int,duration:Int):Pair<String,String> = when(nag){
    "start" -> "Now: $title" to "It's ${reminderClock(clockMinutes)}. You planned this. Start it."
    "late" -> "15 min late: $title" to "Still not ticked. Start it now or move it. Don't let it slide."
    else -> "Not done: $title" to "This should have been finished by ${reminderClock(clockMinutes+duration.coerceAtLeast(1))}. Tick it, or admit you skipped it."
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
        reminderLeadBody(clockMinutes,duration),trigger))
}

/**
 * The nags after the warning, until the task is ticked. Ticking cancels every
 * alarm whose id ends in the task's id (Reminders.cancelTask), so a ticked
 * task goes quiet at once. Calendar events never get these.
 */
fun taskNagAlarms(taskId:String,title:String,clockMinutes:Int,duration:Int,dayDate:String,
                  timezone:String,nowMillis:Long):List<TaskReminderAlarm> {
    if(clockMinutes !in 0 until 30*60 || duration !in 1..1440)return emptyList()
    val zone=ZoneId.of(timezone)
    val day=LocalDate.parse(dayDate).plusDays((clockMinutes/1440).toLong())
    val start=day.atTime(LocalTime.of((clockMinutes/60)%24,clockMinutes%60)).atZone(zone).toInstant().toEpochMilli()
    return reminderNags(duration).mapNotNull{(nag,after)->
        val trigger=start+after*60_000L
        if(trigger<=nowMillis)return@mapNotNull null
        val deliveryDate=Instant.ofEpochMilli(trigger).atZone(zone).toLocalDate().toString()
        val (heading,body)=reminderNagText(nag,title,clockMinutes,duration)
        TaskReminderAlarm("$deliveryDate:$nag:$taskId",deliveryDate,"$nag:$taskId",heading,body,trigger)
    }
}
