package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class ReminderPolicyTest {
    @Test fun fiveMinuteAlertReplacesSameTasksThirtyMinuteAlert(){
        assertEquals(reminderNotificationTag("event30:abc"),reminderNotificationTag("event5:abc"))
    }
    @Test fun syntheticHabitOccurrenceIdsKeepTheirFullIdentity(){
        assertEquals("event:habit:a:2026-09-30",reminderNotificationTag("event5:habit:a:2026-09-30"))
        assertNotEquals(reminderNotificationTag("event5:habit:a:2026-09-30"),reminderNotificationTag("event5:habit:a:2026-10-01"))
    }
    @Test fun DifferentTasksDoNotReplaceEachOther(){assertNotEquals(reminderNotificationTag("event5:a"),reminderNotificationTag("event5:b"))}
    @Test fun DailyTitlesMatchExistingPushNotifications(){
        assertEquals("☀️ Morning Brief",reminderTitle("morning_brief"))
        assertEquals("🌙 Evening Nudge",reminderTitle("evening_nudge"))
        assertEquals("⚠️ Deadline Alert",reminderTitle("deadline_alert"))
    }
    @Test fun alarmsUseTheWorkspacesTimeZoneAndBothLeadTimes(){
        val alarms=taskReminderAlarms("a","Read",9*60,30,"2026-09-30","Asia/Kolkata",0)
        assertEquals(2,alarms.size)
        assertEquals(Instant.parse("2026-09-30T03:00:00Z").toEpochMilli(),alarms[0].triggerMillis)
        assertEquals(Instant.parse("2026-09-30T03:25:00Z").toEpochMilli(),alarms[1].triggerMillis)
        assertEquals("2026-09-30:event30:a",alarms[0].id)
        assertEquals("Starts at 09:00 · 30 min",alarms[0].body)
    }
    @Test fun spilloverUsesTheActualNextDaysDeliveryLedger(){
        val alarms=taskReminderAlarms("habit:a:2026-10-01","Read",25*60,30,"2026-09-30","Asia/Kolkata",0)
        assertEquals("2026-10-01",alarms[0].date)
        assertEquals("2026-10-01:event30:habit:a:2026-10-01",alarms[0].id)
        assertEquals(Instant.parse("2026-09-30T19:00:00Z").toEpochMilli(),alarms[0].triggerMillis)
    }
    @Test fun dstTransitionPreservesTheTasksWallClockTime(){
        val alarms=taskReminderAlarms("a","Read",15*60,30,"2026-03-08","America/New_York",0)
        // Midnight was EST, but the planned 15:00 block is EDT. Adding 15
        // elapsed hours to midnight would shift this reminder an hour late.
        assertEquals(Instant.parse("2026-03-08T18:30:00Z").toEpochMilli(),alarms[0].triggerMillis)
    }
    @Test fun pastLeadsAreNotRearmedAfterARefresh(){
        val now=Instant.parse("2026-09-30T03:10:00Z").toEpochMilli()
        val alarms=taskReminderAlarms("a","Read",9*60,30,"2026-09-30","Asia/Kolkata",now)
        assertEquals(listOf("event5:a"),alarms.map{it.kind})
    }
    @Test fun malformedOrUntimedBlocksCannotCreateAlarms(){
        assertTrue(taskReminderAlarms("a","Read",Int.MAX_VALUE,30,"2026-09-30","Asia/Kolkata",0).isEmpty())
        assertTrue(taskReminderAlarms("a","Read",30*60,30,"2026-09-30","Asia/Kolkata",0).isEmpty())
    }
}
