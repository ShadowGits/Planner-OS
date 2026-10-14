package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

class DashboardCachePolicyTest {
    @Test fun usesItsOwnFiveMinuteWindow(){assertTrue(DashboardCachePolicy.fresh(1000,1000));assertTrue(DashboardCachePolicy.fresh(1000,300999));assertFalse(DashboardCachePolicy.fresh(1000,301000))}
    @Test fun reversedClockNeverMakesOldDashboardFresh(){assertFalse(DashboardCachePolicy.fresh(1000,999))}
    @Test fun sameAgeNeedsSameMutationRevision(){
        assertTrue(DashboardCachePolicy.fresh(1000,1100,7,7))
        assertFalse(DashboardCachePolicy.fresh(1000,1100,7,8))
        assertFalse(DashboardCachePolicy.fresh(1000,1100,-1,0))
    }
    @Test fun invalidationMakesReadableRowsStale(){assertFalse(DashboardCachePolicy.fresh(1000,1100,7,7,true))}
    @Test fun stableKeyKeepsPriorRevisionVisibleButIsolatesConnections(){
        assertEquals("3:/v2/native/dashboard?section=tasks&offset=0",DashboardCachePolicy.key(3,"/v2/native/dashboard?section=tasks&offset=0"))
        assertNotEquals(DashboardCachePolicy.key(3,"/tasks"),DashboardCachePolicy.key(4,"/tasks"))
    }
    @Test fun legacyMigrationUsesNewestRevisionForExactGenerationAndPath(){
        val path="/v2/native/dashboard?section=tasks&offset=0"
        val keys=listOf("1:7:$path","1:11:$path","2:99:$path","1:100:$path&project_id=other","1:$path","bad:1:$path")
        assertEquals(listOf("1:11:$path" to 11L,"1:7:$path" to 7L),DashboardCachePolicy.legacyKeys(keys,1,path))
        assertEquals(emptyList<Pair<String,Long>>(),DashboardCachePolicy.legacyKeys(keys,3,path))
    }
    @Test fun milestonePathPreservesProjectAndPartsWithoutChangingExistingCalls(){
        assertEquals("/v2/native/dashboard?section=tasks&offset=0",DashboardCachePolicy.path("tasks"))
        assertEquals("/v2/native/dashboard?section=tasks&offset=100&project_id=germany&on_date=2026-10-15&milestone_id=language%2Fgoal&include_parts=true",
            DashboardCachePolicy.path("tasks","germany",100,date="2026-10-15",milestone="language/goal",includeParts=true))
        assertFalse(DashboardCachePolicy.path("milestones",row="m1").contains("include_parts"))
    }
}
