package dev.planneros.android

import java.time.LocalDate

/** Cache age controls revalidation, never whether a saved day may be displayed. */
internal object DayCachePolicy {
    fun project(pages:Map<String,Day>,before:Day,after:Day):Map<String,Day> {
        val views=pages.toMutableMap()
        views.putIfAbsent(before.date,before)
        val changed=changedTaskIds(before,after)
        // A destination may never have been opened. Keep the local event there too,
        // including its previous logical-day copy before 04:00.
        (before.tasks+after.tasks).filter{it.id in changed}.forEach{task->
            val owner=if(task in after.tasks)after else before
            val base=LocalDate.parse(if(task.time==null||task.clockMinutes<1440)task.date?:owner.date else owner.date)
            val slot=task.time?.let{normalizeSlot(base,task.clockMinutes)}
            val date=slot?.date?:base
            views.putIfAbsent(date.toString(),Day(date.toString(),owner.timezone,emptyList(),cached=true))
            if(slot!=null&&slot.clockMinute<LOGICAL_DAY_CUTOFF){
                val previous=date.minusDays(1).toString()
                views.putIfAbsent(previous,Day(previous,owner.timezone,emptyList(),cached=true))
            }
        }
        return views.mapValues{(_,view)->projectChanges(view,before,after)}
    }

    fun saved(date:String,cached:Day?,pending:List<Pair<Day,Day>>,timezone:String="Asia/Kolkata"):Day? {
        val projected=pending.fold(mapOf(date to (cached?:Day(date,timezone,emptyList(),cached=true)))){pages,(before,after)->project(pages,before,after)}[date]
        return projected?.takeIf{cached!=null||it.tasks.isNotEmpty()}
    }
}

/** Preview the same two work budgets used by planner_split_task; real IDs arrive later. */
internal fun splitTaskPreview(task:Task,viewDate:String,token:String):List<Task> {
    val firstSeconds=(task.remainingSeconds+1)/2
    val secondSeconds=task.remainingSeconds/2
    require(firstSeconds>0&&secondSeconds>0)
    val parent=task.parent?:task.id
    val shared=task.copy(parent=parent,parentTitle=task.parentTitle?:task.title,partIndex=null,partCount=null,workedSeconds=0)
    val shifted=if(task.workedSeconds>0&&task.time!=null&&task.date!=null){
        val base=LocalDate.parse(if(task.clockMinutes<1440)task.date else viewDate)
        normalizeSlot(base,task.clockMinutes+(task.workedSeconds+59)/60)
    }else null
    val first=shared.copy(id=if(task.parent!=null&&task.workedSeconds==0)task.id else "pending:$token:first",
        minutes=(firstSeconds+59)/60,plannedSeconds=firstSeconds,
        date=shifted?.date?.toString()?:task.date,time=shifted?.clock?:task.time)
    val second=shared.copy(id="pending:$token:second",time=null,minutes=(secondSeconds+59)/60,plannedSeconds=secondSeconds)
    val worked=if(task.workedSeconds>0)task.copy(id=if(task.parent==null)"pending:$token:worked"else task.id,
        parent=parent,done=true,starred=false,minutes=(task.workedSeconds+59)/60,plannedSeconds=task.workedSeconds)else null
    return listOfNotNull(worked,first,second)
}

internal class DayRefreshSuperseded:IllegalStateException("The plan changed during refresh.")

internal fun revertedUpdateMessage(before:Day,after:Day):String {
    val changed=changedTaskIds(before,after)
    val task=(after.tasks+before.tasks).firstOrNull{it.id in changed}
    return if(task==null)"Change reverted. Your previous plan has been restored."
        else "“${task.title}” — change reverted. Your previous task has been restored."
}
