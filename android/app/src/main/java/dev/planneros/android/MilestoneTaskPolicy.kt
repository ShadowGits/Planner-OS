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
