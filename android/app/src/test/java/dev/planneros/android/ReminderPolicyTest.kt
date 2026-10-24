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
        assertEquals("☀️ Morning Brief",reminderTitle("morning_brief"))
        assertEquals("🌙 Evening Nudge",reminderTitle("evening_nudge"))
        assertEquals("⚠️ Deadline Alert",reminderTitle("deadline_alert"))
    }
    @Test fun onlyOneAlarmUsesWorkspaceTimeZoneAndTheFullTaskTitle(){
        val title="Read probability — finish all conditional exercises"
        val alarms=taskReminderAlarms("a",title,9*60,30,"2026-09-30","Asia/Kolkata",0)
        assertEquals(1,alarms.size)
        assertEquals(Instant.parse("2026-09-30T03:20:00Z").toEpochMilli(),alarms.single().triggerMillis)
        assertEquals("2026-09-30:event10:a",alarms.single().id)
        assertEquals(title,alarms.single().title)
        assertEquals("Starts in 10 min · 09:00 · 30 min",alarms.single().body)
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
    @Test fun malformedOrUntimedBlocksCannotCreateAlarms(){
        assertTrue(taskReminderAlarms("a","Read",Int.MAX_VALUE,30,"2026-09-30","Asia/Kolkata",0).isEmpty())
        assertTrue(taskReminderAlarms("a","Read",30*60,30,"2026-09-30","Asia/Kolkata",0).isEmpty())
    }
}
