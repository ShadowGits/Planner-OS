package dev.planneros.android

/** Completed tasks stay accessible; text search never needs another request. */
internal fun milestoneVisibleTasks(tasks:List<Task>,filter:String,query:String):List<Task> = tasks
    .filter{when(filter){"Open"->!it.done;"Done"->it.done;else->true}}
    .filter{query.isBlank()||it.title.contains(query,true)||it.notes?.contains(query,true)==true}
    .sortedWith(compareBy<Task>{it.done}.thenBy{it.date?:"9999"}.thenBy{it.clockMinutes}.thenBy{it.title.lowercase()}.thenBy{it.id})

/** The web rates schedule drift, not raw workflow status or percentage thresholds. */
internal fun milestoneRating(explicitDone:Boolean,done:Int,total:Int,late:Boolean,elapsed:Double?):String=when{
    explicitDone->"complete";total==0->"no_tasks";done>=total->"complete";late->"overdue"
    elapsed==null->"no_date";elapsed-done.toDouble()/total>.25->"red"
    elapsed-done.toDouble()/total>.10->"amber";else->"green"
}

/** Root task dates match the server's milestone rollup; sessions do not double-count. */
internal fun milestoneTaskSpan(tasks:List<Task>):Pair<String?,String?> {
    val dates=tasks.filter{it.parent==null}.mapNotNull{task->
        val value=task.date?:task.dueDate
        value?.let{runCatching{java.time.LocalDate.parse(it).toString()}.getOrNull()}
    }
    return dates.minOrNull() to dates.maxOrNull()
}
