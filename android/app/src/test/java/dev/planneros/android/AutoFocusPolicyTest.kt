package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class AutoFocusPolicyTest {
    private fun ms(value:String)=Instant.parse(value).toEpochMilli()
    private fun block(id:String,start:Long,end:Long)=AutoFocusBlock(id,id,start,end,"2026-10-01")
    @Test fun timezoneConvertsWallClockToScheduledInstant(){
        val b=autoFocusBlock("a","Work",9*60,45,false,"2026-10-01","Asia/Kolkata")!!
        assertEquals(ms("2026-10-01T03:30:00Z"),b.startMillis)
        assertEquals(ms("2026-10-01T04:15:00Z"),b.endMillis)
    }
    @Test fun spilloverUsesNextCalendarDay(){
        val b=autoFocusBlock("habit:a:2026-10-02","Work",25*60,30,false,"2026-10-01","Asia/Kolkata")!!
        assertEquals(ms("2026-10-01T19:30:00Z"),b.startMillis)
    }
    @Test fun dstUsesLocalWallClock(){
        val b=autoFocusBlock("a","Work",15*60,30,false,"2026-03-08","America/New_York")!!
        assertEquals(ms("2026-03-08T19:00:00Z"),b.startMillis)
    }
    @Test fun doneInboxDraftAndMalformedBlocksAreExcluded(){
        assertNull(autoFocusBlock("a","Work",540,30,true,"2026-10-01","UTC"))
        assertNull(autoFocusBlock("a","Inbox",Int.MAX_VALUE,30,false,"2026-10-01","UTC"))
        assertNull(autoFocusBlock("draft:a","Draft",540,30,false,"2026-10-01","UTC"))
        assertNull(autoFocusBlock("a","Bad",1800,30,false,"2026-10-01","UTC"))
        assertNull(autoFocusBlock("a","Bad",540,0,false,"2026-10-01","UTC"))
    }
    @Test fun catchUpRetainsOriginalScheduledEnd(){
        val b=block("a",1000,61_000)
        assertEquals(20_000L,b.elapsed(21_000))
        assertEquals(40_000L,(b.endMillis-b.startMillis)-b.elapsed(21_000))
    }
    @Test fun latestStartWinsOverlapsRegardlessOfInputOrder(){
        val old=block("a",1000,100_000);val newer=block("b",2000,30_000)
        assertEquals(newer,autoFocusCandidate(listOf(newer,old),3000,emptySet()))
        assertEquals(newer,autoFocusCandidate(listOf(old,newer),3000,emptySet()))
    }
    @Test fun equalStartUsesStableIdTieBreak(){
        assertEquals("a",autoFocusCandidate(listOf(block("z",1000,30_000),block("a",1000,30_000)),2000,emptySet())!!.id)
    }
    @Test fun pausedOrCanceledWinnerDoesNotFallBackToOlderOverlap(){
        val old=block("a",1000,100_000);val newer=block("b",2000,30_000)
        assertNull(autoFocusCandidate(listOf(old,newer),3000,setOf(newer.occurrence)))
    }
    @Test fun expirationAndFutureBlocksNeverStart(){
        assertNull(autoFocusCandidate(listOf(block("a",1000,2000)),2000,emptySet()))
        assertNull(autoFocusCandidate(listOf(block("a",3000,5000)),2000,emptySet()))
    }
    @Test fun titleDurationEditsDoNotRestartButMovingStartCreatesNewOccurrence(){
        val b=block("a",1000,30_000)
        assertEquals(b.occurrence,b.copy(title="Edited",endMillis=60_000).occurrence)
        assertNotEquals(b.occurrence,b.copy(startMillis=2000).occurrence)
        assertNull(autoFocusCandidate(listOf(b.copy(endMillis=60_000)),2000,setOf(b.occurrence)))
        assertNotNull(autoFocusCandidate(listOf(b.copy(startMillis=2000)),3000,setOf(b.occurrence)))
    }
}
