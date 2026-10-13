package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test
import java.time.ZonedDateTime

class TimelineWidgetPolicyTest {
    private fun task(id:String,time:String?,done:Boolean=false,minutes:Int=30)=Task(id,id,time,minutes,done,false,false,null,"2026-10-14",null,null)
    private val now=ZonedDateTime.parse("2026-10-14T09:15:00+05:30[Asia/Kolkata]")
    @Test fun timelineSortsByRealTimeWithoutMovingCompletedTasks(){
        val day=Day("2026-10-14","Asia/Kolkata",listOf(task("later","10:00"),task("earlier","08:00",true),task("now","09:00")))
        assertEquals(listOf("earlier","now","later"),widgetTimelineRows(day,now).map{it.task.id})
        assertEquals(listOf("Completed","Now","Scheduled"),widgetTimelineRows(day,now).map{it.state})
    }
    @Test fun noUnscheduledOrOptimisticPlaceholderRows(){
        val day=Day("2026-10-14","Asia/Kolkata",listOf(task("inbox",null),task("pending:1","09:00"),task("real","09:00")))
        assertEquals(listOf("real"),widgetTimelineRows(day,now).map{it.task.id})
    }
    @Test fun currentIntervalIsHalfOpenAndOverdueStartsAtEnd(){
        val day=Day("2026-10-14","Asia/Kolkata",listOf(task("task","09:00",minutes=15)))
        assertEquals("Overdue",widgetTimelineRows(day,now).single().state)
        assertFalse(widgetTimelineRows(day,now).single().current)
        assertTrue(widgetTimelineRows(day,now.minusMinutes(1)).single().current)
    }
    @Test fun tomorrowIsScheduledYesterdayIsOverdue(){
        val tasks=listOf(task("task","09:00"))
        assertEquals("Scheduled",widgetTimelineRows(Day("2026-10-15","Asia/Kolkata",tasks),now).single().state)
        assertEquals("Overdue",widgetTimelineRows(Day("2026-10-13","Asia/Kolkata",tasks),now).single().state)
    }
    @Test fun midnightRolloverKeepsLogicalDayAndDisplaysActualClock(){
        val midnight=ZonedDateTime.parse("2026-10-15T00:15:00+05:30[Asia/Kolkata]")
        val row=widgetTimelineRows(Day("2026-10-14","Asia/Kolkata",listOf(task("task","24:00"))),midnight).single()
        assertEquals("Now",row.state);assertEquals("00:00 +1",row.start);assertEquals("00:30 +1",row.end)
    }
    @Test fun endLabelWrapsWithoutPretendingTaskEndsSameDay(){
        val row=widgetTimelineRows(Day("2026-10-14","Asia/Kolkata",listOf(task("task","23:45"))),now).single()
        assertEquals("23:45",row.start);assertEquals("00:15 +1",row.end)
    }
    @Test fun widgetPendingIntentIdentitiesSeparateDayAccountWidgetAndAction(){
        val base=widgetRequestIdentity(1,2,"2026-10-14","open","t")
        assertNotEquals(base,widgetRequestIdentity(2,2,"2026-10-14","open","t"))
        assertNotEquals(base,widgetRequestIdentity(1,3,"2026-10-14","open","t"))
        assertNotEquals(base,widgetRequestIdentity(1,2,"2026-10-15","open","t"))
        assertNotEquals(base,widgetRequestIdentity(1,2,"2026-10-14","complete","t"))
        assertNotEquals(base,widgetRequestIdentity(1,2,"2026-10-14","open","other"))
    }
    @Test fun mutationRejectsDifferentAccountDeletedTaskRepeatedTapAndConcurrentWrite(){
        val task=task("task","09:00")
        assertTrue(widgetCanApply(2,2,false,task,false))
        assertFalse(widgetCanApply(1,2,false,task,false))
        assertFalse(widgetCanApply(2,2,false,null,false))
        assertFalse(widgetCanApply(2,2,true,task,false))
        assertFalse(widgetCanApply(2,2,false,task,true))
        assertFalse(widgetCanApply(2,2,false,task.copy(id="pending:1"),false))
    }
    @Test fun taskGroupCoordinatorExcludesWidgetAndForegroundConflicts(){
        val coordinator=MutationCoordinator()
        val part=task("part","09:00").copy(parent="parent")
        assertTrue(coordinator.begin(mutationKeys(part)))
        assertFalse(coordinator.begin(mutationKeys(task("parent","10:00"))))
        assertTrue(coordinator.begin(mutationKeys(task("unrelated","11:00"))))
        coordinator.end(mutationKeys(part))
        assertTrue(coordinator.begin(mutationKeys(task("parent","10:00"))))
    }
}
