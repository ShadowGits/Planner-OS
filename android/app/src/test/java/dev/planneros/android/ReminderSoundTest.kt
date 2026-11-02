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

    @Test fun theReportNamesWhatIsKeepingItQuiet(){
        // Android 13 and later will not post anything without this, and the
        // report says so first — which is right, but not what is under test.
        org.robolectric.shadows.ShadowApplication.getInstance()
            .grantPermissions(android.Manifest.permission.POST_NOTIFICATIONS)
        SecureConfig(app).reminders=true
        Reminders.channel(app)
        assertTrue("a working setup should say so, said: ${Reminders.soundReport(app)}",
            Reminders.soundReport(app).startsWith("Ready"))

        // Silenced by the user in Android Settings.
        manager.deleteNotificationChannel(Reminders.CHANNEL)
        manager.createNotificationChannel(android.app.NotificationChannel(
            Reminders.CHANNEL,"Planner reminders",NotificationManager.IMPORTANCE_LOW))
        assertTrue("silent channel: ${Reminders.soundReport(app)}",
            Reminders.soundReport(app).contains("Silent"))

        // Blocked altogether.
        manager.deleteNotificationChannel(Reminders.CHANNEL)
        manager.createNotificationChannel(android.app.NotificationChannel(
            Reminders.CHANNEL,"Planner reminders",NotificationManager.IMPORTANCE_NONE))
        assertTrue("blocked channel: ${Reminders.soundReport(app)}",
            Reminders.soundReport(app).contains("blocked"))

        // The app is not the one sending them, which is its own answer.
        SecureConfig(app).reminders=false
        assertTrue("reminders off: ${Reminders.soundReport(app)}",
            Reminders.soundReport(app).contains("web app or Telegram"))
    }

    @Test fun theChannelAndThePlayerAgreeOnTheSameFile(){
        val channel=Reminders.channel(app)
        assertEquals("the button plays exactly what the channel plays",
            channel!!.sound.toString(),Reminders.soundUri(app))
    }

    @Test fun aSilencedChannelStopsTheReminder(){
        Reminders.channel(app)
        manager.deleteNotificationChannel(Reminders.CHANNEL)
        manager.createNotificationChannel(
            android.app.NotificationChannel(Reminders.CHANNEL,"Planner reminders",NotificationManager.IMPORTANCE_NONE))
        assertNull("a channel the user switched off is not worth posting to",Reminders.channel(app))
    }
}
