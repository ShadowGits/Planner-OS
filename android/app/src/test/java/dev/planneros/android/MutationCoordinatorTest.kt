package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

class MutationCoordinatorTest {
    private fun task(id:String,date:String="2026-10-01",time:String?="10:00",done:Boolean=false)=Task(id,id,time,30,done,false,false,null,date,null,null)
    private fun day(vararg tasks:Task,date:String="2026-10-01")=Day(date,"Asia/Kolkata",tasks.toList())
    @Test fun unrelatedWritesContinueWhileSameTaskAndSiblingWritesWait(){
        val locks=MutationCoordinator()
        assertTrue(locks.begin(setOf("a","parent")))
        assertFalse(locks.begin(setOf("a")))
        assertFalse(locks.begin(setOf("sibling","parent")))
        assertTrue(locks.begin(setOf("b")))
        locks.end(setOf("a","parent"))
        assertTrue(locks.begin(setOf("a","parent")))
        assertTrue(locks.pending("b"))
    }
    @Test fun failedWriteRestoresOnlyItsTaskAndPreservesOtherConfirmedChange(){
        val a=task("a");val b=task("b")
        val before=day(a,b);val after=day(a.copy(done=true),b)
        val current=day(a.copy(done=true),b.copy(starred=true))
        val restored=projectChanges(current,after,before)
        assertFalse(restored.tasks.first{it.id=="a"}.done)
        assertTrue(restored.tasks.first{it.id=="b"}.starred)
    }
    @Test fun moveProjectsIntoCachedDestinationAndDisappearsFromSource(){
        val old=task("a");val unrelated=task("other",date="2026-10-02")
        val before=day(old);val after=day(old.copy(date="2026-10-02",time="11:30"))
        assertTrue(projectChanges(before,before,after).tasks.isEmpty())
        val destination=projectChanges(day(unrelated,date="2026-10-02"),before,after)
        assertEquals(setOf("a","other"),destination.tasks.map{it.id}.toSet())
        assertEquals("11:30",destination.tasks.first{it.id=="a"}.time)
    }
    @Test fun overnightCopyChangesBothViewsWithoutDuplicatingTask(){
        val original=task("a",date="2026-10-02",time="25:30")
        val before=day(original);val after=day(original.copy(starred=true))
        val next=projectChanges(day(task("a",date="2026-10-02",time="01:30"),date="2026-10-02"),before,after)
        assertEquals(1,next.tasks.size)
        assertEquals("01:30",next.tasks.single().time)
        assertTrue(next.tasks.single().starred)
    }
    @Test fun rollbackMoveRestoresSourceAndClearsDestinationOnly(){
        val a=task("a");val b=task("b",date="2026-10-02")
        val before=day(a);val after=day(a.copy(date="2026-10-02",time="12:00"))
        val target=projectChanges(day(b,date="2026-10-02"),before,after)
        assertEquals(listOf(b),projectChanges(target,after,before).tasks)
        assertEquals(listOf(a),projectChanges(day(),after,before).tasks)
    }
}
