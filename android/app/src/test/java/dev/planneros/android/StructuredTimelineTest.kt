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

    @Test fun theNowBarShowsWhereverNowFalls(){
        val entries=dayEntries(listOf(task("Coffee","15:45",15),task("Emails","16:00",30),task("Home","17:00",30)))
        assertEquals("inside a task, at its place",offsetForDp(16*60+10,entries),nowBarDp(16*60+10,entries)!!,.01f)
        assertEquals("in free time",offsetForDp(16*60+40,entries),nowBarDp(16*60+40,entries)!!,.01f)
        assertEquals("before the first task, just above it",-12f,nowBarDp(6*60,entries)!!,.01f)
        val bottom=entries.sumOf{entryHeightDp(it).toDouble()}.toFloat()
        assertEquals("after the last task, just below it",bottom+20f,nowBarDp(23*60,entries)!!,.01f)
        assertNull("not on another day",nowBarDp(-1,entries))
        assertNull(nowBarDp(Int.MAX_VALUE,entries))
    }

    @Test fun aHeldTaskCanGoUntilFourInTheMorning(){
        val entries=dayEntries(listOf(task("Dinner","20:00",60),task("Read","21:30",45)))
        val bottom=entries.sumOf{entryHeightDp(it).toDouble()}.toFloat()
        assertEquals("the end of the day's tasks",22*60+15,lastEnd(entries))
        assertEquals("as on the old timeline, the latest start is 27:55",27*60+55,LAST_START)
        assertEquals("room to then at scale, plus the held capsule",(LAST_START-(22*60+15))*1.6f+pillHeightDp(60),nightRoomDp(entries,60),.01f)
        assertEquals("faint hours from the next whole hour to 04:00",listOf(23*60,24*60,25*60,26*60,27*60,28*60),nightHours(entries))
        assertEquals("01:30 the next morning is reachable",25*60+30,minuteAtDp(bottom+(25*60+30-(22*60+15))*1.6f,entries))
        assertEquals("27:55 is the latest start",LAST_START,minuteAtDp(bottom+5000f,entries))
        assertEquals("an hour too close to the last task is left out",listOf(24*60,25*60,26*60,27*60,28*60),nightHours(dayEntries(listOf(task("Late","22:50",15)))))
        assertEquals(0f,nightRoomDp(emptyList(),30),0f)
        val day=java.time.LocalDate.parse("2026-05-13")
        assertEquals("a drop at 25:30 is 01:30 the next date",ScheduleSlot(day.plusDays(1),90),normalizeSlot(day,25*60+30))
        assertEquals("and the landing outline still shows on this day",25*60+30,visibleMinute(day,normalizeSlot(day,25*60+30)))
        val held=task("Read","21:30",45)
        val after=replaceTask(Day(day.toString(),"Asia/Kolkata",listOf(held)),held.copy(time="01:30",date=day.plusDays(1).toString()))
        val shown=projectChanges(Day(day.toString(),"Asia/Kolkata",listOf(held)),Day(day.toString(),"Asia/Kolkata",listOf(held)),after).tasks.single()
        assertEquals("on screen it stays at the end of this day, as the server lists it","25:30",shown.time)
    }

    @Test fun oldTimelineDetailsAreKept(){
        val part=Task("p","Essay","10:00",60,false,false,false,"parent","2026-05-13",null,null,parentTitle="Essay",partIndex=2,partCount=3)
        assertEquals("Part 2/3",partText(part))
        assertNull(partText(task("Solo","10:00")))
        val worked=Task("w","Study","10:00",60,false,false,false,null,"2026-05-13",null,null,workedSeconds=25*60)
        assertEquals("${workDuration(25*60)} worked · ${workDuration(35*60)} left",workedText(worked))
        assertEquals("${workDuration(25*60)} worked",workedText(worked.copy(done=true)))
        val a=task("a","09:00").copy(starred=true);val b=task("b","10:00").copy(starred=true,done=true)
        assertEquals("Top Wins · 1 of 2",winsTitle(listOf(a,b)))
        assertEquals("Day won",winsTitle(listOf(a.copy(done=true),b)))
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
