package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

class DayCachePolicyTest {
    private fun task(id:String="a",date:String?="2026-10-24",time:String?="10:00")=
        Task(id,"Study German",time,180,false,false,false,null,date,"notes","project",milestoneId="milestone")
    private fun day(vararg tasks:Task,date:String="2026-10-24")=Day(date,"Asia/Kolkata",tasks.toList(),cached=true)

    @Test fun savedDayRemainsReadableWithoutAnInFlightRequestOrFreshnessGate(){
        val saved=day(task())
        assertEquals(saved,DayCachePolicy.saved(saved.date,saved,emptyList()))
        assertNull(DayCachePolicy.saved("2026-10-25",null,emptyList()))
    }
    @Test fun movingToAnUnvisitedDayImmediatelyCreatesItsLocalPage(){
        val before=day(task());val moved=task(date="2026-11-02",time="12:15")
        val after=before.copy(tasks=listOf(moved))
        val pages=DayCachePolicy.project(mapOf(before.date to before),before,after)
        assertTrue(pages.getValue(before.date).tasks.isEmpty())
        assertEquals(listOf(moved),pages.getValue("2026-11-02").tasks)
        assertTrue(pages.getValue("2026-11-02").cached)
    }
    @Test fun unvisitedUnscheduledDestinationUsesTheTasksDate(){
        val before=day();val task=task(date="2026-12-01",time=null)
        val pages=DayCachePolicy.project(emptyMap(),before,before.copy(tasks=listOf(task)))
        assertEquals(listOf(task),pages.getValue("2026-12-01").tasks)
        assertTrue(pages.getValue(before.date).tasks.isEmpty())
    }
    @Test fun beforeFourCreatesBothCalendarAndLogicalDayCopies(){
        val before=day();val event=task(date="2026-10-25",time="01:30")
        val pages=DayCachePolicy.project(emptyMap(),before,before.copy(tasks=listOf(event)))
        assertEquals("25:30",pages.getValue("2026-10-24").tasks.single().time)
        assertEquals("01:30",pages.getValue("2026-10-25").tasks.single().time)
        assertEquals(event.id,pages.getValue("2026-10-25").tasks.single().id)
    }
    @Test fun failedMoveRevertsBothDaysAndKeepsAnotherTasksSuccessfulEdit(){
        val a=task();val b=task("b",date="2026-10-25")
        val before=day(a);val after=day(a.copy(date="2026-10-25"))
        var pages=DayCachePolicy.project(mapOf(before.date to before,"2026-10-25" to day(b,date="2026-10-25")),before,after)
        val otherBefore=pages.getValue("2026-10-25")
        pages=DayCachePolicy.project(pages,otherBefore,replaceTask(otherBefore,b.copy(done=true)))
        pages=DayCachePolicy.project(pages,after,before)
        assertEquals(listOf(a),pages.getValue(before.date).tasks)
        assertEquals(listOf(b.copy(done=true)),pages.getValue("2026-10-25").tasks)
    }
    @Test fun pendingDayCanBeShownBeforePersistenceCompletes(){
        val before=day(task());val after=day(task(date="2026-10-28"))
        val local=DayCachePolicy.saved("2026-10-28",null,listOf(before to after))
        assertEquals(after.tasks,local?.tasks)
    }
    @Test fun serverIdReplacesTemporaryTaskAcrossEveryCopy(){
        val before=day();val temporary=task("pending:create",date="2026-10-25",time="01:30")
        var pages=DayCachePolicy.project(emptyMap(),before,day(temporary))
        pages=DayCachePolicy.project(pages,day(temporary),day(temporary.copy(id="real-id")))
        for(page in pages.values){
            assertFalse(page.tasks.any{it.id.startsWith("pending:")})
            assertEquals(listOf("real-id"),page.tasks.map{it.id})
        }
    }
    @Test fun rejectedCreateDisappearsFromAllCopiesWithoutErasingOtherEvents(){
        val other=task("other");val before=day(other)
        val after=day(other,task("pending:create",date="2026-10-25",time="01:30"))
        val pages=DayCachePolicy.project(DayCachePolicy.project(mapOf(before.date to before),before,after),after,before)
        assertEquals(listOf(other),pages.getValue(before.date).tasks)
        assertTrue(pages.getValue("2026-10-25").tasks.isEmpty())
    }
    @Test fun overnightCompletionUpdatesBothCopies(){
        val event=task(time="25:30",date="2026-10-25")
        val before=day(event);val after=day(event.copy(done=true))
        val pages=DayCachePolicy.project(mapOf(before.date to before),before,after)
        assertTrue(pages.getValue("2026-10-24").tasks.single().done)
        assertTrue(pages.getValue("2026-10-25").tasks.single().done)
    }
    @Test fun splitPreviewAppearsImmediatelyAndPreservesPreviouslyLoggedWork(){
        val original=task(time="23:30").copy(workedSeconds=5400,plannedSeconds=10800)
        val preview=splitTaskPreview(original,"2026-10-24","test")
        val worked=preview.single{it.done};val first=preview.first{!it.done};val second=preview.last()
        assertEquals(5400,worked.workedSeconds)
        assertEquals(0,worked.remainingSeconds)
        assertEquals("2026-10-25",first.date)
        assertEquals("01:00",first.time)
        assertEquals(2700,first.remainingSeconds)
        assertEquals(2700,second.remainingSeconds)
        assertNull(second.time)
        assertTrue(preview.all{it.parent==original.id&&it.projectId==original.projectId&&it.milestoneId==original.milestoneId})
    }
    @Test fun splittingAnUnscheduledChildKeepsItsFirstIdentityAndExactOddSecondBudgets(){
        val original=task(time=null).copy(parent="root",plannedSeconds=5,workedSeconds=0)
        val preview=splitTaskPreview(original,"2026-10-24","test")
        assertEquals(original.id,preview.first().id)
        assertEquals(listOf(3,2),preview.map{it.remainingSeconds})
        assertTrue(preview.all{it.time==null&&it.parent=="root"})
    }
    @Test fun failedDeletionNotificationRetainsTheFullOriginalTaskName(){
        val original=task().copy(title="Germany documents — long name with passport and application details")
        val message=revertedUpdateMessage(day(original),day())
        assertTrue(message.contains(original.title))
        assertTrue(message.contains("change reverted"))
        assertTrue(message.contains("restored"))
    }
}
