package dev.planneros.android

import java.time.LocalDate
import java.time.ZonedDateTime

/** An agenda with honest start/end labels, not a compressed time-scaled calendar. */
data class WidgetTimelineRow(val task:Task,val start:String,val end:String,val state:String,val current:Boolean)
fun widgetTimelineRows(day:Day,now:ZonedDateTime):List<WidgetTimelineRow> {
    val date=LocalDate.parse(day.date)
    val today=logicalToday(now)
    val minute=logicalNowMinute(now)
    return day.tasks.filter{it.time!=null&&it.clockMinutes in 0..1675&&!it.id.startsWith("pending:")}
        .sortedWith(compareBy<Task>{it.clockMinutes}.thenBy{it.id}).map{task->
            val end=task.clockMinutes+task.minutes
            val current=!task.done&&date==today&&minute in task.clockMinutes until end
            val state=when{
                task.done->"Completed"
                current->"Now"
                date<today||(date==today&&end<=minute)->"Overdue"
                else->"Scheduled"
            }
            WidgetTimelineRow(task,displayClock(task.clockMinutes)+(if(task.clockMinutes>=1440) " +1" else ""),displayClock(end)+(if(end>=1440) " +1" else ""),state,current)
        }
}
fun widgetRequestIdentity(widget:Int,generation:Long,date:String,action:String,task:String=""):String =
    listOf(widget.toString(),generation.toString(),date,action,task).joinToString("/")
fun widgetCanApply(expectedGeneration:Long,currentGeneration:Long,expectedDone:Boolean,task:Task?,pending:Boolean):Boolean =
    expectedGeneration==currentGeneration&&task!=null&&task.done==expectedDone&&!pending&&!task.id.startsWith("pending:")
