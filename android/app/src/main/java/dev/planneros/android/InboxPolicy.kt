package dev.planneros.android

import java.time.LocalDate
import java.time.ZonedDateTime

/** API Inbox rows use calendar dates; logical-day rows can use 24:xx–27:xx. */
fun canonicalInboxTask(task:Task,viewDate:String):Task {
    if(task.time==null)return task
    val base=LocalDate.parse(if(task.clockMinutes<1440)task.date?:viewDate else viewDate)
    val slot=normalizeSlot(base,task.clockMinutes)
    return task.copy(date=slot.date.toString(),time=slot.clock)
}
fun isOverdue(task:Task,now:ZonedDateTime):Boolean {
    if(task.done)return false
    val today=now.toLocalDate()
    if(task.dueDate?.let{LocalDate.parse(it)<today}==true)return true
    val scheduled=task.date?.let(LocalDate::parse)
    if(scheduled!=null&&scheduled<today)return true
    if(scheduled==today&&task.time!=null)return task.clockMinutes+task.minutes<=now.hour*60+now.minute
    return false // An undated idea belongs in Inbox, but has no missed deadline.
}
fun belongsInInbox(task:Task,now:ZonedDateTime):Boolean = !task.done &&
    (isOverdue(task,now)||(task.time==null&&(task.date==null||LocalDate.parse(task.date)<=now.toLocalDate())))
/** Use selected-day versions to suppress stale backlog copies after an optimistic edit. */
fun inboxRows(view:Day?,backlog:Day?,now:ZonedDateTime):List<Task> {
    val rows=backlog?.tasks.orEmpty().filter{belongsInInbox(it,now)}.associateBy{it.id}.toMutableMap()
    view?.tasks?.forEach{raw->
        rows.remove(raw.id)
        val task=canonicalInboxTask(raw,view.date)
        if(raw.time==null||belongsInInbox(task,now))rows[task.id]=task
    }
    return rows.values.sortedWith(compareByDescending<Task>{isOverdue(it,now)}.thenByDescending{it.starred}.thenBy{it.done}.thenBy{it.date.orEmpty()}.thenBy{it.title})
}
/** Keep global backlog projection separate from selected-day projection. */
fun applyInboxChanges(backlog:Day,before:Day,after:Day,now:ZonedDateTime):Day {
    val changed=changedTaskIds(before,after)
    val rows=backlog.tasks.filterNot{it.id in changed}.toMutableList()
    after.tasks.filter{it.id in changed}.forEach{raw->
        val task=canonicalInboxTask(raw,after.date)
        if(belongsInInbox(task,now))rows.add(task)
    }
    return backlog.copy(tasks=rows)
}
