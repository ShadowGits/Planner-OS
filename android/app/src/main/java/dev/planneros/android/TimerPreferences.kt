package dev.planneros.android

import android.content.Context
import androidx.compose.runtime.mutableIntStateOf

/** Device-wide master switch for timers and actual-work entry. */
internal object TimerPreferences {
    private val revision = mutableIntStateOf(0)
    fun enabled(c:Context):Boolean {
        revision.intValue // Settings changes also update every visible Compose control.
        return c.getSharedPreferences("time-tracking",Context.MODE_PRIVATE).getBoolean("enabled",true)
    }
    fun setEnabled(c:Context,value:Boolean) {
        if(enabled(c)==value)return
        check(c.getSharedPreferences("time-tracking",Context.MODE_PRIVATE).edit().putBoolean("enabled",value).commit())
        // Invalidate queued automatic intents and consume the current occurrence.
        AutoFocusScheduler.trackingChanged(c)
        if(!value){TimerStore.reset(c);FocusWorkLogs.clearNotifications(c)}
        revision.intValue++
    }
}
