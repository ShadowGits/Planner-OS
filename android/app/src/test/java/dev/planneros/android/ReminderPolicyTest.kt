package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class ReminderPolicyTest {
    @Test fun oneTaskKeepsAStableTagAcrossThePolicyUpgrade(){
        assertEquals("event:abc",reminderNotificationTag("event10:abc"))
        assertEquals(reminderNotificationTag("event30:abc"),reminderNotificationTag("event10:abc"))
        assertEquals(reminderNotificationTag("event5:abc"),reminderNotificationTag("event10:abc"))
    }
    @Test fun syntheticHabitOccurrenceIdsKeepTheirFullIdentity(){
        assertEquals("event:habit:a:2026-09-30",reminderNotificationTag("event10:habit:a:2026-09-30"))
        assertNotEquals(reminderNotificationTag("event10:habit:a:2026-09-30"),reminderNotificationTag("event10:habit:a:2026-10-01"))
    }
    @Test fun differentTasksDoNotReplaceEachOther(){assertNotEquals(reminderNotificationTag("event10:a"),reminderNotificationTag("event10:b"))}
    @Test fun dailyTitlesRemainAvailable(){
        assertEquals("Overdue check",reminderTitle("morning_brief"))
        assertEquals("Today's report",reminderTitle("evening_nudge"))
        assertEquals("Deadlines",reminderTitle("deadline_alert"))
    }
    @Test fun onlyOneAlarmUsesWorkspaceTimeZoneAndTheFullTaskTitle(){
        val title="Read probability — finish all conditional exercises"
        val alarms=taskReminderAlarms("a",title,9*60,30,"2026-09-30","Asia/Kolkata",0)
        assertEquals(1,alarms.size)
        assertEquals(Instant.parse("2026-09-30T03:20:00Z").toEpochMilli(),alarms.single().triggerMillis)
        assertEquals("2026-09-30:event10:a",alarms.single().id)
        assertEquals(title,alarms.single().title)
        assertEquals("In 10 min · 09:00 · 30 min. Wrap up what you're doing.",alarms.single().body)
    }
    @Test fun spilloverUsesTheActualNextDaysDeliveryLedger(){
        val alarms=taskReminderAlarms("habit:a:2026-10-01","Read",25*60,30,"2026-09-30","Asia/Kolkata",0)
        assertEquals("2026-10-01",alarms.single().date)
        assertEquals("2026-10-01:event10:habit:a:2026-10-01",alarms.single().id)
        assertEquals(Instant.parse("2026-09-30T19:20:00Z").toEpochMilli(),alarms.single().triggerMillis)
    }
    @Test fun midnightReminderUsesItsDeliveryDateSoTheFeedCannotDuplicateIt(){
        val alarm=taskReminderAlarms("a","Night study",5,30,"2026-10-01","Asia/Kolkata",0).single()
        assertEquals("2026-09-30",alarm.date)
        assertEquals(Instant.parse("2026-09-30T18:25:00Z").toEpochMilli(),alarm.triggerMillis)
    }
    @Test fun dstTransitionPreservesTheTasksWallClockTime(){
        val alarm=taskReminderAlarms("a","Read",15*60,30,"2026-03-08","America/New_York",0).single()
        assertEquals(Instant.parse("2026-03-08T18:50:00Z").toEpochMilli(),alarm.triggerMillis)
    }
    @Test fun pastTenMinuteLeadDoesNotCreateAFiveMinuteFallback(){
        val now=Instant.parse("2026-09-30T03:21:00Z").toEpochMilli()
        assertTrue(taskReminderAlarms("a","Read",9*60,30,"2026-09-30","Asia/Kolkata",now).isEmpty())
    }
    @Test fun untilTickedATaskIsNaggedAtItsStartFifteenInAndItsEnd(){
        val nags=taskNagAlarms("gym","Gym",17*60+30,90,"2026-10-31","Asia/Kolkata",0)
        assertEquals(listOf("start:gym","late:gym","end:gym"),nags.map{it.kind})
        assertEquals(listOf("Now: Gym","15 min late: Gym","Not done: Gym"),nags.map{it.title})
        assertEquals("It's 17:30. You planned this. Start it.",nags[0].body)
        assertEquals("Still not ticked. Start it now or move it. Don't let it slide.",nags[1].body)
        assertEquals("This should have been finished by 19:00. Tick it, or admit you skipped it.",nags[2].body)
        assertEquals(Instant.parse("2026-10-31T12:00:00Z").toEpochMilli(),nags[0].triggerMillis)
        assertEquals(Instant.parse("2026-10-31T12:15:00Z").toEpochMilli(),nags[1].triggerMillis)
        assertEquals(Instant.parse("2026-10-31T13:30:00Z").toEpochMilli(),nags[2].triggerMillis)
    }
    @Test fun aShortTaskSkipsFifteenInWhichWouldLandAfterItEnded(){
        assertEquals(listOf("start:a","end:a"),taskNagAlarms("a","Call",9*60,15,"2026-10-31","Asia/Kolkata",0).map{it.kind})
    }
    @Test fun onlyTheNagsStillToComeAreArmed(){
        val now=Instant.parse("2026-10-31T12:05:00Z").toEpochMilli()
        assertEquals(listOf("late:gym","end:gym"),taskNagAlarms("gym","Gym",17*60+30,90,"2026-10-31","Asia/Kolkata",now).map{it.kind})
    }
    @Test fun everyNagShareTheTasksNotificationSoTheyReplaceNotPileUp(){
        listOf("start:gym","late:gym","end:gym","event10:gym").forEach{assertEquals("event:gym",reminderNotificationTag(it))}
    }
    @Test fun tickingCancelsEveryNagBecauseTheirIdsEndInTheTasksId(){
        taskNagAlarms("gym","Gym",17*60+30,90,"2026-10-31","Asia/Kolkata",0).forEach{assertTrue(it.id.endsWith(":gym"))}
    }
    @Test fun aNagAfterMidnightIsDeliveredOnItsRealDate(){
        val end=taskNagAlarms("o","Office",21*60,390,"2026-10-31","Asia/Kolkata",0).last()
        assertEquals("2026-11-01",end.date)
        assertEquals("This should have been finished by 03:30. Tick it, or admit you skipped it.",end.body)
    }
    @Test fun malformedOrUntimedBlocksCannotCreateAlarms(){
        assertTrue(taskNagAlarms("a","Read",30*60,30,"2026-09-30","Asia/Kolkata",0).isEmpty())
        assertTrue(taskReminderAlarms("a","Read",Int.MAX_VALUE,30,"2026-09-30","Asia/Kolkata",0).isEmpty())
        assertTrue(taskReminderAlarms("a","Read",30*60,30,"2026-09-30","Asia/Kolkata",0).isEmpty())
    }
}
