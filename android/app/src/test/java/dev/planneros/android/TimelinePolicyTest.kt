package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate
import java.time.ZonedDateTime

class TimelinePolicyTest {
    private val date = LocalDate.parse("2026-10-01")
    @Test fun shortAndLongBlocksEndExactlyAtTheirScheduledMinute() {
        for(duration in listOf(1,5,15,25,30,90,180)){
            val start=timelineOffsetDp(540,480)
            assertEquals(timelineOffsetDp(540+duration,480),start+timelineDurationDp(duration),0.001f)
            assertEquals(timelineDurationDp(duration)/2,timelineOffsetDp(540+duration/2,480)-start,if(duration%2==0)0.001f else 1.001f)
        }
        assertEquals(30f,timelineDurationDp(15),0.001f)
        assertEquals(30f,dragSlot(date,540,30f).clockMinute.minus(540).toFloat()*TIMELINE_DP_PER_MINUTE,0.001f)
    }
    @Test fun fiveMinuteDragSnapUsesTimeScaleInsteadOfCardTitleHeight() {
        assertEquals("09:15", dragSlot(date, 540, 29f).clock)
        assertEquals("08:55", dragSlot(date, 540, -11f).clock)
    }
    @Test fun dragClampsAboveTimelineAndNormalizesPastMidnight() {
        assertEquals(ScheduleSlot(date, 0), dragSlot(date, 10, -100f))
        assertEquals(ScheduleSlot(date.plusDays(1), 15), dragSlot(date, 1430, 50f))
    }
    @Test fun crossDayDragPreservesTimeAndSupportsPreviousDate() {
        assertEquals(ScheduleSlot(date.plusDays(1), 600), dragSlot(date, 600, 0f, 1))
        assertEquals(ScheduleSlot(date.minusDays(1), 600), dragSlot(date, 600, 0f, -1))
    }
    @Test fun smallHoursStayInTheirLogicalDayUntilFour() {
        assertEquals(1515, visibleMinute(date, ScheduleSlot(date.plusDays(1), 75)))
        assertNull(visibleMinute(date, ScheduleSlot(date.plusDays(1), 240)))
        assertEquals(date.minusDays(1), logicalToday(ZonedDateTime.parse("2026-10-01T03:59:00+05:30[Asia/Kolkata]")))
        assertEquals(date, logicalToday(ZonedDateTime.parse("2026-10-01T04:00:00+05:30[Asia/Kolkata]")))
    }
    @Test fun adjacentTasksDoNotOverlap() {
        val lanes = overlapLanes(listOf(TimeBlock("a", 540, 30), TimeBlock("b", 570, 30)))
        assertEquals(Lane(0, 1), lanes["a"]); assertEquals(Lane(0, 1), lanes["b"])
    }
    @Test fun transitiveOverlapsShareMaxColumnCountAndReuseFreeColumn() {
        val lanes = overlapLanes(listOf(TimeBlock("a", 540, 120), TimeBlock("b", 550, 30), TimeBlock("c", 560, 30), TimeBlock("d", 580, 60)))
        assertEquals(3, lanes["a"]!!.columns); assertEquals(lanes["b"]!!.column, lanes["d"]!!.column)
    }
    @Test fun scheduleUsesWholeDurationAndSkipsNestedBusyIntervals() {
        val slot = nextFreeSlot(date, date, 543, 60, listOf(TimeBlock("a", 550, 150), TimeBlock("b", 560, 10), TimeBlock("c", 710, 20)))
        assertEquals(ScheduleSlot(date, 730), slot)
    }
    @Test fun futureDayScheduleStartsAtNineAndRollsDateWhenFull() {
        assertEquals(ScheduleSlot(date.plusDays(1), 540), nextFreeSlot(date.plusDays(1), date, 900, 30, emptyList()))
        assertEquals(ScheduleSlot(date.plusDays(1), 20), nextFreeSlot(date, date, 1420, 30, listOf(TimeBlock("a", 1440, 20))))
    }
    @Test fun starvationLimitCanAlwaysUnstarAndNeverOfferPermanentSixth() {
        assertFalse(canToggleStar(false, 5, 5)); assertTrue(canToggleStar(true, 5, 5)); assertTrue(canToggleStar(false, 4, 5))
    }
    @Test fun failedMutationRollbackDoesNotReplaceNewlySelectedDay() {
        val snapshot = Day(date.toString(), "Asia/Kolkata", emptyList())
        val newDay = snapshot.copy(date = date.plusDays(1).toString())
        assertEquals(snapshot, rollbackForDate(snapshot, snapshot.copy(cached = true)))
        assertEquals(newDay, rollbackForDate(snapshot, newDay))
    }
    @Test fun durationAndMidnightLabelsRemainReadable() {
        assertEquals("1h 30m", durationLabel(90)); assertEquals("7h", durationLabel(420))
        assertEquals("00:15", displayClock(1455)); assertEquals("12:15 AM", displayClock(1455, true))
    }
    @Test fun categoryIconsMatchPlannerNamesAndDefaultDragRemainsInLogicalDay() {
        assertEquals("🇩🇪", taskEmoji("German A1")); assertEquals("📐",taskEmoji("Linear algebra"))
        assertEquals("💻",taskEmoji("Build app")); assertEquals("✍️",taskEmoji("Write journal"))
        assertEquals("📄",taskEmoji("Print transcript")); assertEquals("💰",taskEmoji("Bank payment"))
        assertEquals(ScheduleSlot(date.plusDays(1),235),dragSlot(date,1600,1000f))
    }
}
