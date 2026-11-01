package dev.planneros.android

import android.app.NotificationManager
import android.content.Context
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/**
 * Reminders have to make a noise. Android fixes a channel's sound when it is
 * first created and ignores every later change, so the silent original is
 * replaced by a new channel rather than edited.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35])
class ReminderSoundTest {
    private val app: Context get() = RuntimeEnvironment.getApplication()
    private val manager: NotificationManager
        get() = app.getSystemService(NotificationManager::class.java)

    @Test fun theReminderChannelPlaysThePackagedSound(){
        val channel=Reminders.channel(app)
        assertNotNull("reminders should have a channel",channel)
        assertEquals("android.resource://${app.packageName}/raw/task_reminder",channel!!.sound.toString())
        assertEquals("it has to arrive loudly, not silently in the shade",
            NotificationManager.IMPORTANCE_HIGH,channel.importance)
        assertTrue("and buzz",channel.shouldVibrate())
    }

    @Test fun theOldSilentChannelIsTakenAway(){
        manager.createNotificationChannel(
            android.app.NotificationChannel("reminders","Planner reminders",NotificationManager.IMPORTANCE_HIGH))
        assertNotNull(manager.getNotificationChannel("reminders"))
        Reminders.channel(app)
        assertNull("the silent channel should be gone, not left in Settings",
            manager.getNotificationChannel("reminders"))
    }

    @Test fun aSilencedChannelStopsTheReminder(){
        Reminders.channel(app)
        manager.deleteNotificationChannel(Reminders.CHANNEL)
        manager.createNotificationChannel(
            android.app.NotificationChannel(Reminders.CHANNEL,"Planner reminders",NotificationManager.IMPORTANCE_NONE))
        assertNull("a channel the user switched off is not worth posting to",Reminders.channel(app))
    }
}
