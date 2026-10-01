package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test
import java.time.ZonedDateTime

class InboxPolicyTest {
    private val now=ZonedDateTime.parse("2026-10-01T12:00:00+05:30[Asia/Kolkata]")
    private fun task(id:String="a",date:String?="2026-10-01",time:String?="11:00",minutes:Int=30,done:Boolean=false,due:String?=null)=Task(id,id,time,minutes,done,false,false,null,date,null,null,dueDate=due)
    @Test fun expiredBlockJoinsInboxButOngoingDoesNot(){assertTrue(isOverdue(task(),now));assertFalse(isOverdue(task(time="11:45"),now));assertTrue(isOverdue(task(time="11:30"),now))}
    @Test fun pastDateAndDeadlineRemainOverdueEvenWithFutureSlot(){assertTrue(isOverdue(task(date="2026-09-30"),now));assertTrue(isOverdue(task(date="2026-10-03",due="2026-09-30"),now))}
    @Test fun completedAndFutureTasksDoNotJoinGlobalInbox(){assertFalse(belongsInInbox(task(done=true),now));assertFalse(belongsInInbox(task(date="2026-10-03"),now));assertTrue(belongsInInbox(task(date=null,time=null),now))}
    @Test fun undatedIdeasAreInboxWorkWithoutBeingMarkedOverdue(){val idea=task(date=null,time=null);assertTrue(belongsInInbox(idea,now));assertFalse(isOverdue(idea,now))}
    @Test fun overdueKeepsOriginalDateAndTimeAndTimeline(){val t=task(date="2026-09-30");val view=Day("2026-10-01","Asia/Kolkata",emptyList());val rows=inboxRows(view,view.copy(tasks=listOf(t)),now);assertEquals(listOf(t),rows);assertTrue(view.tasks.isEmpty())}
    @Test fun selectedVersionSuppressesStaleBacklogDone(){val t=task();val view=Day("2026-10-01","Asia/Kolkata",listOf(t.copy(done=true)));assertTrue(inboxRows(view,view.copy(tasks=listOf(t)),now).isEmpty())}
    @Test fun ordinarySelectedInboxRetainsCompletedItems(){val t=task(time=null,done=true);assertEquals(listOf(t),inboxRows(Day("2026-10-01","Asia/Kolkata",listOf(t)),null,now))}
    @Test fun reschedulingBacklogRemovesOverdueWithoutChangingUnrelated(){val t=task(date="2026-09-30");val other=task(id="b",time=null);val before=Day("2026-10-01","Asia/Kolkata",listOf(t));val after=before.copy(tasks=listOf(t.copy(date="2026-10-02",time="13:00")));val global=before.copy(tasks=listOf(t,other));assertEquals(listOf(other),applyInboxChanges(global,before,after,now).tasks);assertEquals(global.tasks.toSet(),applyInboxChanges(applyInboxChanges(global,before,after,now),after,before,now).tasks.toSet())}
    @Test fun overnightViewUsesActualDate(){val t=task(date="2026-10-01",time="25:00");val canonical=canonicalInboxTask(t,"2026-09-30");assertEquals("2026-10-01",canonical.date);assertEquals("01:00",canonical.time);assertTrue(isOverdue(canonical,now))}
    @Test fun backlogEditProjectsIntoOnlyItsScheduledDay(){val t=task(date="2026-09-30");val before=Day("2026-10-01","Asia/Kolkata",listOf(t));val after=before.copy(tasks=listOf(t.copy(starred=true)));assertTrue(projectChanges(before.copy(tasks=emptyList()),before,after).tasks.isEmpty());assertTrue(projectChanges(Day("2026-09-30","Asia/Kolkata",listOf(t)),before,after).tasks.single().starred)}
}
