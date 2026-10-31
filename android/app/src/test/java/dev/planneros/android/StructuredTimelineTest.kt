package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

class StructuredTimelineTest {
    private fun task(id:String,time:String?=null,minutes:Int=30)=Task(id,id,time,minutes,false,false,false,null,"2026-05-13",null,null)

    @Test fun freeTimeSitsBetweenTasksAndSharedEdgesShowOnce(){
        val entries=dayEntries(listOf(task("Wake Up","07:00",15),task("Yoga","07:15"),task("Coffee","08:45",15),task("Any time")))
        assertEquals(listOf("Wake Up","Yoga","gap-465","Coffee"),entries.map{it.key})
        assertFalse("Yoga starts where Wake Up ends",(entries[1] as TaskEntry).showsStart)
        assertTrue((entries[3] as TaskEntry).showsStart)
        assertEquals(60,(entries[2] as GapEntry).minutes)
    }

    @Test fun heightsFollowDurationWithinLimits(){
        assertEquals(52f,pillHeightDp(15),0f);assertEquals(72f,pillHeightDp(30),.01f);assertEquals(216f,pillHeightDp(600),0f)
        assertEquals(34f,gapHeightDp(10),0f);assertEquals(96f,gapHeightDp(600),0f)
        val entries=dayEntries(listOf(task("a","07:00",15),task("b","07:15")))
        assertEquals(62f,entryOffsetDp(entries,"b")!!,.01f)
    }

    @Test fun labelsAndColoursAreStable(){
        assertEquals("15m",shortDuration(15));assertEquals("1h",shortDuration(60));assertEquals("1h 30m",shortDuration(90))
        // Same djb2 hash as the Apple app, so a task has the same colour on both.
        assertEquals(paletteIndex("Yoga",8),paletteIndex("Yoga",8))
        var hash=5381UL;"Yoga".forEach{hash=hash*33UL+it.code.toULong()}
        assertEquals((hash%8UL).toInt(),paletteIndex("Yoga",8))
    }
}
