package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

class PlanningContextPolicyTest {
    private val germany=PlanningProject("germany-id","Germany")
    private val life=PlanningProject("life-id","Life other than Germany")
    private fun task(id:String="a",title:String="Study German",project:String?=germany.id,date:String?=null,time:String?=null,done:Boolean=false)=
        Task(id,title,time,45,done,false,false,null,date,"Saved notes",project,milestoneId="milestone",workedSeconds=600)
    private fun context(vararg tasks:Task)=PlanningContext("2026-10-14","Asia/Kolkata",listOf(germany,life),tasks.toList(),true)
    private fun day(vararg tasks:Task)=Day("2026-10-14","Asia/Kolkata",tasks.toList())

    @Test fun projectLookupKeepsTheSameTaskIdentityAndSavedMetadata(){
        val existing=task(date="2026-11-10")
        val result=taskSuggestions(listOf(existing,task("other",project=life.id)),germany.id,"german").single()
        assertSame(existing,result)
        assertEquals("Saved notes",result.notes)
        assertEquals("milestone",result.milestoneId)
        assertEquals(600,result.workedSeconds)
        assertEquals("2026-11-10",result.date)
    }
    @Test fun suggestionsSearchWordsCaseInsensitivelyAndExcludeScheduledCompletedPendingOrOtherProjects(){
        val valid=task(title="SWAYAM study maths",date="2027-01-10")
        val rows=listOf(valid,task("scheduled",title=valid.title,time="10:00"),task("done",title=valid.title,done=true),
            task("pending:a",title=valid.title),task("life",title=valid.title,project=life.id))
        assertEquals(listOf(valid),taskSuggestions(rows,germany.id,"MATHS swayam"))
        assertTrue(taskSuggestions(rows,germany.id," ").isEmpty())
        assertTrue(taskSuggestions(rows,null,"maths").isEmpty())
    }
    @Test fun sixVisibleRowsStillKeepTheRestAvailableForScrolling(){
        val rows=List(15){task(it.toString(),"German lesson $it")}
        assertEquals(6,PlanningCachePolicy.VISIBLE_SUGGESTIONS)
        assertEquals(15,taskSuggestions(rows,germany.id,"German").size)
    }
    @Test fun newestLocalSnapshotsSuppressStaleContextRows(){
        val existing=task()
        val other=task("future",date="2027-01-01")
        val stale=context(existing,other)
        assertEquals(listOf(other),planningRows(stale,day(existing.copy(time="09:00")),day(existing)))
        assertEquals(listOf(other),planningRows(stale,day(existing.copy(done=true)),null))
    }
    @Test fun freshContextAbsenceWinsOverAnOlderGlobalInbox(){
        val stale=task()
        assertTrue(planningRows(context(),null,day(stale)).isEmpty())
        assertEquals(listOf(stale),planningRows(null,null,day(stale)))
    }
    @Test fun schedulingCompletionDeletionAndRollbackUpdateOnlyChangedSuggestions(){
        val existing=task();val future=task("future",date="2027-01-01")
        val original=context(existing,future)
        val before=day(existing)
        val after=day(existing.copy(time="10:00"))
        val changed=applyPlanningChanges(original,before,after)
        assertEquals(listOf(future),changed.tasks)
        assertEquals(setOf(existing,future),applyPlanningChanges(changed,after,before).tasks.toSet())
        assertEquals(listOf(future),applyPlanningChanges(original,before,day(existing.copy(done=true))).tasks)
        assertEquals(listOf(future),applyPlanningChanges(original,before,day()).tasks)
    }
    @Test fun projectTransferKeepsIdentityAndSwitchesSuggestionGroup(){
        val existing=task();val edited=existing.copy(projectId=life.id)
        val updated=applyPlanningChanges(context(existing),day(existing),day(edited))
        assertTrue(taskSuggestions(updated.tasks,germany.id,"German").isEmpty())
        assertEquals(listOf(edited),taskSuggestions(updated.tasks,life.id,"German"))
        assertEquals("milestone",updated.tasks.single().milestoneId)
    }
    @Test fun freshnessHasFiniteTtlAndNeverAcceptsPendingOrDirtySnapshots(){
        assertTrue(PlanningCachePolicy.fresh(1_000,1_001,false,false))
        assertFalse(PlanningCachePolicy.fresh(1_000,1_000+PlanningCachePolicy.FRESH_MS,false,false))
        assertFalse(PlanningCachePolicy.fresh(1_000,999,false,false))
        assertFalse(PlanningCachePolicy.fresh(1_000,1_001,true,false))
        assertFalse(PlanningCachePolicy.fresh(1_000,1_001,false,true))
    }
    @Test fun accountSwitchAndMutationRaceNeverReplaceCachedPlanningData(){
        assertTrue(PlanningCachePolicy.acceptRefresh(3,3,10,10,false))
        assertFalse(PlanningCachePolicy.acceptRefresh(3,4,10,10,false))
        assertFalse(PlanningCachePolicy.acceptRefresh(3,3,10,11,false))
        assertFalse(PlanningCachePolicy.acceptRefresh(3,3,10,10,true))
    }
    @Test fun migratedCachedTasksStayInCanonicalProjectAndKeepMilestoneHistory(){
        val legacy=task(project="study-id")
        val aliases=mapOf("study-id" to germany.id,"fitness-id" to life.id)
        val current=context(legacy).copy(projectAliases=aliases)
        val rows=planningRows(current,day(legacy),null)
        assertEquals(germany.id,rows.single().projectId)
        assertEquals("milestone",rows.single().milestoneId)
        assertEquals(600,rows.single().workedSeconds)
        assertEquals("Saved notes",rows.single().notes)
        assertEquals(listOf(rows.single()),taskSuggestions(rows,germany.id,"German"))
        assertEquals(life.id,resolvePlanningProject("fitness-id",aliases))
        assertEquals(germany.id,applyPlanningChanges(current,day(legacy),day(legacy.copy(title="German lesson"))).tasks.single().projectId)
    }
    @Test fun cachedNullAssignmentUsesKnownFreshContextProject(){
        val fresh=task(project=life.id)
        val old=fresh.copy(projectId=null)
        assertEquals(life.id,planningRows(context(fresh),day(old),null).single().projectId)
        assertEquals(life.id,canonicalPlanningTask(old,emptyMap(),life.id).projectId)
    }
    @Test fun untouchedLegacyProjectDoesNotGetPatchedBackBeforeAliasRefresh(){
        assertFalse(shouldPatchPlanningProject("study-id","study-id",false))
        assertFalse(shouldPatchPlanningProject(germany.id,germany.id,false))
        assertFalse(shouldPatchPlanningProject(germany.id,null,false))
        assertTrue(shouldPatchPlanningProject("study-id",germany.id,false))
        assertTrue(shouldPatchPlanningProject(germany.id,life.id,true))
        assertTrue(shouldPatchPlanningProject(germany.id,germany.id,true))
    }
    @Test fun aliasCyclesAndUnknownIdsNeverSilentlyChangeAssignment(){
        assertEquals("a",resolvePlanningProject("a",mapOf("a" to "b","b" to "a")))
        assertEquals("legacy",resolvePlanningProject("legacy",emptyMap()))
        assertNull(resolvePlanningProject(null,mapOf("a" to germany.id)))
    }
    @Test fun consolidatedProjectsAreTheOnlyChoicesEvenWithStaleDashboardProjects(){
        val legacy=PlanningProject("legacy","Study")
        assertEquals(listOf(germany,life),pickerProjects(listOf(life,legacy,germany)))
        assertEquals(listOf(germany,life),pickerProjects(listOf(life,legacy,germany),legacy.id))
        assertTrue(pickerProjects(listOf(legacy)).isEmpty())
        assertEquals(listOf(germany),pickerProjects(listOf(legacy,germany),legacy.id))
    }
}
