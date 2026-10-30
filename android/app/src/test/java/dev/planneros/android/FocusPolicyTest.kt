package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate
import java.time.ZonedDateTime

class FocusPolicyTest {
    // Saturday 31 October 2026, early afternoon in the workspace zone.
    private val now=ZonedDateTime.parse("2026-10-31T13:00:00+05:30[Asia/Kolkata]")
    private val today=LocalDate.parse("2026-10-31")
    private fun task(id:String,date:String?=null,time:String?=null,due:String?=null,starred:Boolean=false,priority:String?="medium",
                     milestone:String?=null,done:Boolean=false,habit:Boolean=false,minutes:Int=30)=
        Task(id,id,time,minutes,done,starred,habit,null,date,null,null,dueDate=due,milestoneId=milestone,priority=priority)

    private val milestones=mapOf(
        "shortlist" to FocusMilestone("shortlist","Shortlist finalized","2026-11-02"),
        "calculus" to FocusMilestone("calculus","Calculus refresh","2027-02-28"),
    )

    @Test fun reasonsMatchTheServerInbox(){
        assertEquals(FocusReason.DEADLINE,focusReason(task("a",date="2026-11-01",due="2026-09-30"),now))
        assertEquals(FocusReason.MISSED_SLOT,focusReason(task("b",date="2026-10-30",time="21:30"),now))
        assertEquals(FocusReason.MISSED_SLOT,focusReason(task("c",date="2026-10-31",time="09:00"),now))
        assertEquals(FocusReason.NEVER_SCHEDULED,focusReason(task("d"),now))
        assertNull("later today is not overdue",focusReason(task("e",date="2026-10-31",time="23:00"),now))
        assertNull("untimed today is today's work",focusReason(task("f",date="2026-10-31"),now))
        assertNull(focusReason(task("g",date="2026-09-30",done=true),now))
        assertNull("habits stay on the timeline",focusReason(task("h",date="2026-10-30",time="07:00",habit=true),now))
    }

    @Test fun rankingPinsThenDeadlinesThenNearMilestonesThenAge(){
        val ranked=rankOverdue(listOf(
            task("old-calculus",due="2026-09-14",milestone="calculus"),
            task("cut-list",date="2026-11-02",due="2026-10-30",milestone="shortlist"),
            task("missed",date="2026-10-03",time="18:30"),
            task("aps",date="2026-09-30",due="2026-09-20",priority="high"),
            task("idea"),
            task("workout",date="2026-10-03",time="18:30",starred=true),
        ),milestones,now).map{it.first.id}
        assertEquals(listOf("aps","workout","cut-list","old-calculus","missed","idea"),ranked)
    }

    @Test fun latenessReadsLikeTheWebCards(){
        assertEquals("41d late",lateness(task("a",due="2026-09-20"),FocusReason.DEADLINE,now))
        assertEquals("Missed Fri 30 Oct 21:30",lateness(task("b",date="2026-10-30",time="21:30"),FocusReason.MISSED_SLOT,now))
        assertEquals("Never scheduled",lateness(task("c"),FocusReason.NEVER_SCHEDULED,now))
        assertEquals("milestone in 2d",milestoneSoon(task("d",milestone="shortlist"),milestones,now))
        assertNull(milestoneSoon(task("e",milestone="calculus"),milestones,now))
    }

    @Test fun todayIsWhatIsLeftAndNotAlreadyOverdue(){
        val view=Day("2026-10-31","Asia/Kolkata",listOf(
            task("cv",date="2026-10-31",time="23:00"),
            task("missed",date="2026-10-31",time="09:00"),
            task("finished",date="2026-10-31",time="20:00",done=true),
            task("gym",date="2026-10-31",time="18:00",habit=true),
            task("anytime",date="2026-10-31"),
        ))
        val backlog=listOf(task("due-today",due="2026-10-31"),task("anytime",date="2026-10-31"),task("late",due="2026-10-01"))
        assertEquals(listOf("cv","anytime","due-today"),focusToday(view,backlog,now).map{it.id})
    }

    @Test fun movingCarriesOnlyABrokenDeadline(){
        val to=LocalDate.parse("2026-11-09")
        val broken=movedForFocus(task("a",date="2026-10-03",time="18:30",due="2026-09-20"),to,today)
        assertEquals("2026-11-09",broken.date);assertNull("lands untimed",broken.time);assertEquals("2026-11-09",broken.dueDate)
        val ahead=movedForFocus(task("b",date="2026-10-30",due="2026-11-30"),to,today)
        assertEquals("a future deadline is real; it stays","2026-11-30",ahead.dueDate)
        assertNull(movedForFocus(task("c"),to,today).dueDate)
        assertNull("a moved task is no longer overdue",focusReason(broken,now))
    }

    @Test fun quickDatesCollapseOnASaturday(){
        assertEquals(listOf("2026-10-31","2026-11-01","2026-11-02"),quickMoveDates(today).map{it.first.toString()})
        assertEquals(listOf("2026-10-28","2026-10-29","2026-10-31","2026-11-02"),quickMoveDates(LocalDate.parse("2026-10-28")).map{it.first.toString()})
    }

    @Test fun weekRowsFollowMilestoneTargets(){
        val rows=focusWeekRows(listOf(
            task("a",date="2026-10-26",milestone="calculus"),
            task("b",date="2026-11-01",milestone="shortlist"),
            task("c",date="2026-10-28"),
            task("d",date="2026-11-05",milestone="shortlist"),
            task("e",date="2026-10-29",habit=true),
        ),LocalDate.parse("2026-10-26"),milestones,emptyMap())
        assertEquals(listOf("Shortlist finalized","Calculus refresh","Other"),rows.map{it.label})
        assertEquals(listOf("b"),rows[0].cells[6].map{it.id})
        assertEquals("outside the week is left out",1,rows[0].cells.sumOf{it.size})
    }
}
