package dev.planneros.android

import java.time.LocalDate
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.util.Locale

/**
 * What the Focus screen shows and in which order — the same rules as the web
 * dashboard's Focus board (Deutschland-Dash src/lib/focus.ts), so the phone and
 * the browser agree on what is most pressing.
 */
enum class FocusReason { DEADLINE, MISSED_SLOT, NEVER_SCHEDULED }

/** A milestone as far as Focus needs it: a name to show and a date to rank by. */
data class FocusMilestone(val id:String,val name:String,val targetDate:String?)

/**
 * Why a task is overdue, or null when it is not. Unlike isOverdue, an idea
 * with no date at all counts here: the backlog view is where it gets one.
 */
fun focusReason(task:Task,now:ZonedDateTime):FocusReason? {
    if(task.done||task.habit)return null
    val today=now.toLocalDate()
    if(task.dueDate?.let{LocalDate.parse(it)<today}==true)return FocusReason.DEADLINE
    if(isOverdue(task,now))return FocusReason.MISSED_SLOT
    if(task.date==null&&task.dueDate==null)return FocusReason.NEVER_SCHEDULED
    return null
}

fun isPinned(task:Task)=task.starred||task.priority=="high"

/** Work feeding a milestone this close outranks work that is merely older. */
const val MILESTONE_SOON_DAYS=14L

/** The day a task went wrong on: its deadline if that passed, else its slot. */
fun overdueSince(task:Task,reason:FocusReason?):String? =
    if(reason==FocusReason.DEADLINE)task.dueDate else task.date?:task.dueDate

/**
 * Overdue tasks, most pressing first. Priority alone cannot order them —
 * nearly everything is "medium" — so dates do the work: starred and
 * high-priority first, then broken deadlines before missed slots before
 * never-scheduled, then work for a milestone due within two weeks, then
 * oldest first.
 */
fun rankOverdue(tasks:List<Task>,milestones:Map<String,FocusMilestone>,now:ZonedDateTime):List<Pair<Task,FocusReason>> {
    val today=now.toLocalDate()
    fun soon(task:Task):Long {
        val target=task.milestoneId?.let{milestones[it]?.targetDate}?.let(LocalDate::parse)?:return Long.MAX_VALUE
        val days=ChronoUnit.DAYS.between(today,target)
        return if(days in 0..MILESTONE_SOON_DAYS)days else Long.MAX_VALUE
    }
    return tasks.mapNotNull{task->focusReason(task,now)?.let{task to it}}
        .sortedWith(compareByDescending<Pair<Task,FocusReason>>{isPinned(it.first)}
            .thenBy{it.second.ordinal}
            .thenBy{soon(it.first)}
            .thenBy{overdueSince(it.first,it.second)?:"9999-12-31"}
            .thenBy{it.first.title})
}

private val SHORT_DAY=DateTimeFormatter.ofPattern("EEE d MMM",Locale.ENGLISH)

/** How late a task is, in words that fit on a card. */
fun lateness(task:Task,reason:FocusReason,now:ZonedDateTime):String {
    if(reason==FocusReason.NEVER_SCHEDULED)return "Never scheduled"
    val since=overdueSince(task,reason)?.let(LocalDate::parse)?:return "Overdue"
    val days=ChronoUnit.DAYS.between(since,now.toLocalDate())
    if(reason==FocusReason.DEADLINE)return if(days<=0)"Due today" else "${days}d late"
    val time=task.time?.take(5)?.let{" $it"}.orEmpty()
    return if(days<=0)"Missed today$time" else "Missed ${since.format(SHORT_DAY)}$time"
}

/** "milestone in 3d" when the task's milestone is close, else null. */
fun milestoneSoon(task:Task,milestones:Map<String,FocusMilestone>,now:ZonedDateTime):String? {
    val target=task.milestoneId?.let{milestones[it]?.targetDate}?.let(LocalDate::parse)?:return null
    val days=ChronoUnit.DAYS.between(now.toLocalDate(),target)
    return when{days<0||days>MILESTONE_SOON_DAYS->null;days==0L->"milestone due today";else->"milestone in ${days}d"}
}

/**
 * What is still to do today: today's planned tasks plus untimed work the
 * backlog holds for today, minus anything already counted as overdue. Habits
 * stay on the timeline, where they are ticked.
 */
fun focusToday(todayView:Day?,backlogRows:List<Task>,now:ZonedDateTime):List<Task> {
    // The view is the app's logical today, which runs to 04:00, so its tasks are
    // taken as they are rather than re-filtered by the calendar date.
    val seen=mutableSetOf<String>()
    return (todayView?.tasks.orEmpty()+backlogRows)
        .filter{!it.done&&!it.habit&&focusReason(it,now)==null&&seen.add(it.id)}
        .sortedWith(compareBy<Task>{it.time==null}.thenBy{it.clockMinutes}.thenByDescending{isPinned(it)}.thenBy{it.title})
}

/** One-tap move targets: today, tomorrow, the coming Saturday, next Monday. */
fun quickMoveDates(today:LocalDate):List<Pair<LocalDate,String>> {
    val saturday=today.plusDays(((6-today.dayOfWeek.value)+7L)%7)
    val monday=today.plusDays(((8-today.dayOfWeek.value)%7).toLong().let{if(it==0L)7L else it})
    return listOf(today to "Today",today.plusDays(1) to "Tomorrow",
        saturday to saturday.format(SHORT_DAY),monday to monday.format(SHORT_DAY))
        .distinctBy{it.first}
}

data class FocusWeekRow(val key:String,val label:String,val sublabel:String?,val milestone:FocusMilestone?,val cells:List<List<Task>>)

/**
 * The week as rows of seven: one row per milestone, or per project for tasks
 * with none, soonest milestone target first.
 */
fun focusWeekRows(items:List<Task>,weekStart:LocalDate,milestones:Map<String,FocusMilestone>,projectNames:Map<String,String>):List<FocusWeekRow> {
    data class Bucket(val key:String,val label:String,val sublabel:String?,val milestone:FocusMilestone?,val cells:List<MutableList<Task>>)
    val rows=linkedMapOf<String,Bucket>()
    for(task in items){
        if(task.habit)continue
        val day=(task.date?:task.dueDate)?.let(LocalDate::parse)?:continue
        val column=ChronoUnit.DAYS.between(weekStart,day).toInt()
        if(column !in 0..6)continue
        val milestone=task.milestoneId?.let{milestones[it]}
        val (key,label,sublabel)=when{
            task.milestoneId!=null->Triple("m:${task.milestoneId}",milestone?.name?:"Milestone",task.projectId?.let{projectNames[it]})
            task.projectId!=null->Triple("p:${task.projectId}",projectNames[task.projectId]?:"Project","No milestone")
            else->Triple("none","Other","No project")
        }
        rows.getOrPut(key){Bucket(key,label,sublabel,milestone,List(7){mutableListOf()})}.cells[column].add(task)
    }
    fun rank(key:String)=when{key.startsWith("m:")->0;key.startsWith("p:")->1;else->2}
    return rows.values
        .sortedWith(compareBy<Bucket>{rank(it.key)}.thenBy{it.milestone?.targetDate?:"9999-12-31"}.thenBy{it.label})
        .map{b->FocusWeekRow(b.key,b.label,b.sublabel,b.milestone,b.cells.map{cell->cell.sortedWith(compareBy<Task>{it.clockMinutes}.thenBy{it.title})})}
}

/**
 * The same task after a Focus move: planned for the day with no time, so it
 * lands in that day's unscheduled list. A deadline already broken moves with
 * it, as the server does; one still ahead stays.
 */
fun movedForFocus(task:Task,to:LocalDate,today:LocalDate):Task {
    val due=task.dueDate?.let(LocalDate::parse)
    val newDue=if(due!=null&&due<today)to else due
    return task.copy(date=to.toString(),time=null,dueDate=newDue?.toString())
}

/** "\"Shortlist finalized\" now due 9 Nov (was 2 Nov)" for each milestone a move pushed out. */
fun milestoneNotes(data:org.json.JSONObject):List<String> {
    val rows=data.optJSONArray("milestones_extended")?:return emptyList()
    val day=DateTimeFormatter.ofPattern("d MMM",Locale.ENGLISH)
    return List(rows.length()){rows.getJSONObject(it)}.map{m->
        "\"${m.optString("name")}\" now due ${LocalDate.parse(m.getString("to")).format(day)} (was ${LocalDate.parse(m.getString("from")).format(day)})"
    }
}
