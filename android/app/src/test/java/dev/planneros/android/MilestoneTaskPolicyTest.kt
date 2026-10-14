package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

class MilestoneTaskPolicyTest {
    private fun task(id:String,done:Boolean=false,date:String?=null,notes:String?=null)=Task(id,id,null,30,done,false,false,null,date,notes,"project")
    @Test fun allIncludesCompletedAndOpenAndDoesNotCollapseSameNamedTasks(){
        val a=task("a");val b=task("b",true).copy(title="a")
        assertEquals(setOf("a","b"),milestoneVisibleTasks(listOf(a,b),"All","").map{it.id}.toSet())
    }
    @Test fun filtersAndSearchAreLocalAndIncludeNotes(){
        val a=task("a",notes="Passport renewal");val b=task("b",true)
        assertEquals(listOf(a),milestoneVisibleTasks(listOf(a,b),"Open","PASSPORT"))
        assertEquals(listOf(b),milestoneVisibleTasks(listOf(a,b),"Done",""))
    }
    @Test fun datedOpenWorkComesBeforeDatelessAndCompleted(){
        val a=task("a");val b=task("b",date="2026-10-15");val c=task("c",true,date="2026-10-01")
        assertEquals(listOf(b,a,c),milestoneVisibleTasks(listOf(a,c,b),"All",""))
    }
    @Test fun healthUsesWebDriftThresholdsAndOverdueRules(){
        assertEquals("red",milestoneRating(false,1,10,false,.6))
        assertEquals("amber",milestoneRating(false,4,10,false,.6))
        assertEquals("green",milestoneRating(false,6,10,false,.6))
        assertEquals("overdue",milestoneRating(false,9,10,true,.99))
        assertEquals("complete",milestoneRating(false,10,10,true,1.0))
        assertEquals("complete",milestoneRating(true,0,10,true,1.0))
        assertEquals("no_date",milestoneRating(false,0,10,false,null))
        assertEquals("no_tasks",milestoneRating(false,0,0,true,1.0))
    }
}
