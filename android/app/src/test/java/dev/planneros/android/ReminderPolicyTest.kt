package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

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
}
