package dev.planneros.android

/** A task/group can have one write in flight; unrelated tasks never share a lock. */
class MutationCoordinator {
    private val active=mutableSetOf<String>()
    @Synchronized fun begin(keys:Set<String>):Boolean {
        if(keys.any{it in active})return false
        active.addAll(keys);return true
    }
    @Synchronized fun end(keys:Set<String>){active.removeAll(keys)}
    @Synchronized fun pending(key:String)=key in active
    @Synchronized fun hasPending()=active.isNotEmpty()
}
fun mutationKeys(task:Task)=setOf(task.id,task.parent?:task.id)
fun changedTaskIds(before:Day,after:Day):Set<String> {
    val old=before.tasks.associateBy{it.id};val new=after.tasks.associateBy{it.id}
    return (old.keys+new.keys).filter{old[it]!=new[it]}.toSet()
}
/** Restore only this write's rows, never another task's newer optimistic state. */
fun rollbackTasks(before:Day,after:Day,current:Day?):Day? {
    if(current?.date!=before.date)return current
    val affected=changedTaskIds(before,after)
    return current.copy(tasks=current.tasks.filterNot{it.id in affected}+before.tasks.filter{it.id in affected})
}
/** Apply one optimistic diff to any calendar/logical day without replacing its other rows. */
fun projectChanges(view:Day,before:Day,after:Day):Day {
    val affected=changedTaskIds(before,after)
    val rows=view.tasks.filterNot{it.id in affected}.toMutableList()
    val viewDate=java.time.LocalDate.parse(view.date)
    after.tasks.filter{it.id in affected}.forEach{task->
        val slot=task.time?.let{normalizeSlot(java.time.LocalDate.parse(if(task.clockMinutes<1440)task.date?:after.date else after.date),task.clockMinutes)}
        val date=slot?.date?:task.date?.let(java.time.LocalDate::parse)?:java.time.LocalDate.parse(after.date)
        val shown=slot?.let{visibleMinute(viewDate,it)}
        if((slot==null&&date==viewDate)||shown!=null)rows.add(task.copy(time=shown?.let{"%02d:%02d".format(it/60,it%60)},date=date.toString()))
    }
    return view.copy(tasks=rows)
}
