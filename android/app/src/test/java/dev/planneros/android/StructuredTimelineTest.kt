package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

/** The layout and states in docs/structured-ux.md. */
class StructuredTimelineTest {
    private fun task(id:String,time:String?=null,minutes:Int=30,done:Boolean=false)=Task(id,id,time,minutes,done,false,false,null,"2026-05-13",null,null)

    @Test fun freeTimeSitsBetweenTasksAndSharedEdgesShowOnce(){
        val entries=dayEntries(listOf(task("Wake Up","07:00",15),task("Yoga","07:15"),task("Coffee","08:45",15),task("Any time")))
        assertEquals(listOf("Wake Up","Yoga","gap-465","Coffee"),entries.map{it.key})
        assertFalse("Yoga starts where Wake Up ends",(entries[1] as TaskEntry).showsStart)
        assertTrue((entries[3] as TaskEntry).showsStart)
        assertEquals(60,(entries[2] as GapEntry).minutes)
    }

    @Test fun timeRunsDownThePageAtStructuredsScale(){
        assertEquals("a 15-minute task is a circle",48f,pillHeightDp(15),0f)
        assertEquals("two hours is about 190 dp",192f,pillHeightDp(120),.01f)
        assertEquals(640f,pillHeightDp(900),0f)
        assertEquals("a few minutes is a short piece of spine",16f,gapHeightDp(15),0f)
        assertEquals("free time keeps the scale",96f,gapHeightDp(60),.01f)
        assertEquals("a long window is capped",104f,gapHeightDp(600),0f)
        val entries=dayEntries(listOf(task("a","07:00",15),task("b","07:15")))
        assertEquals(56f,entryOffsetDp(entries,"b")!!,.01f)
    }

    @Test fun aPointOfTheListIsTheTimeShownThere(){
        val entries=dayEntries(listOf(task("Lunch","12:30",60),task("Blog","13:30",120),task("Coffee","15:45",15),task("Emails","16:00",30),task("Home","17:00",30)))
        for(minute in 12*60+30..18*60 step 5){
            assertEquals("round trip at ${columnClock(minute,false)}",minute,minuteAtDp(offsetForDp(minute,entries),entries))
        }
        assertEquals("above the first task, earlier at scale",12*60,minuteAtDp(-48f,entries))
        val blogTop=entryOffsetDp(entries,"Blog")!!+ROW_PADDING_DP
        assertEquals("halfway down a 2-hour capsule is an hour in",14*60+30,minuteAtDp(blogTop+96f,entries))
    }

    @Test fun capsulesFillByTime(){
        val emails=task("Emails","16:00",30)
        assertEquals(Phase.UPCOMING,phaseOf(emails,15*60))
        assertEquals(Phase.UNDERWAY,phaseOf(emails,16*60+1))
        assertEquals(.5f,progressOf(emails,16*60+15),.001f)
        assertEquals(Phase.PAST,phaseOf(emails,17*60))
        assertEquals(Phase.DONE,phaseOf(emails.copy(done=true),15*60))
        assertEquals("29m remaining",remainingText(emails,16*60+1))
        assertEquals("an earlier day has all passed",Phase.PAST,phaseOf(emails,nowOnDay(java.time.LocalDate.parse("2026-05-12"),java.time.LocalDate.parse("2026-05-13"),600)))
        assertEquals("a later day is all ahead",Phase.UPCOMING,phaseOf(emails,nowOnDay(java.time.LocalDate.parse("2026-05-14"),java.time.LocalDate.parse("2026-05-13"),600)))
    }

    @Test fun wordsMatchStructured(){
        assertEquals("7:00–7:15 AM",rangeText(420,435,true))
        assertEquals("11:30 AM–12:15 PM",rangeText(690,735,true))
        assertEquals("07:00–07:15",rangeText(420,435,false))
        assertEquals("15 min",durationWords(15));assertEquals("1 hr",durationWords(60));assertEquals("1 hr, 30 min",durationWords(90))
        assertEquals("4:15 PM",fullClock(16*60+15,true))
        assertEquals("whole hours inside a long task, as Structured's 1:30–3:30 shows 2:00 and 3:00",listOf(14*60,15*60),hourMarks(task("Blog","13:30",120)))
        assertEquals("15m",shortDuration(15));assertEquals("1h",shortDuration(60));assertEquals("1h 30m",shortDuration(90))
    }

    @Test fun coloursAreStructuredsAndStable(){
        // Same djb2 hash as the Apple app, so a task has the same colour on both.
        var hash=5381UL;"Yoga".forEach{hash=hash*33UL+it.code.toULong()}
        assertEquals((hash%8UL).toInt(),paletteIndex("Yoga",8))
    }
}
