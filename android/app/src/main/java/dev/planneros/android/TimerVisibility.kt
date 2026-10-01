package dev.planneros.android

import android.app.Notification
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings

/** Read-only diagnostics. Samsung controls its Now Bar and global lock-screen settings. */
internal object TimerVisibility {
    fun status(c:Context,notificationsAllowed:Boolean):String {
        if(!notificationsAllowed)return "Timer cards blocked: allow Planner OS notifications."
        val manager=c.getSystemService(NotificationManager::class.java)
        val channel=manager.getNotificationChannel(TimerService.FOCUS_CHANNEL)
        val channelStatus=when {
            channel?.importance==NotificationManager.IMPORTANCE_NONE->"Timer channel blocked."
            channel?.lockscreenVisibility==Notification.VISIBILITY_SECRET->"Timer channel hidden on lock screen."
            channel?.lockscreenVisibility==Notification.VISIBILITY_PRIVATE->"Timer task name hidden on lock screen."
            channel!=null&&channel.importance<NotificationManager.IMPORTANCE_DEFAULT->"Timer channel is silent; check lock-screen visibility."
            channel==null->"Start a timer to create its lock-screen card."
            else->"Timer card enabled."
        }
        if(Build.VERSION.SDK_INT<36)return channelStatus
        // Reflection keeps devices with early/vendor Android 16 implementations compatible.
        val promoted=runCatching{NotificationManager::class.java.getMethod("canPostPromotedNotifications").invoke(manager) as Boolean}.getOrNull()
        return channelStatus+when(promoted){
            true->" Live timer access allowed; Samsung chooses where it appears."
            false->" Live timer access blocked; allow Live timer updates below."
            null->" This system does not expose Live timer access status."
        }
    }
    fun openAppSettings(c:Context){
        val intent=Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE,c.packageName)
        if(!launch(c,intent))launch(c,Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:${c.packageName}")))
    }
    fun openChannelSettings(c:Context){
        val intent=Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE,c.packageName).putExtra(Settings.EXTRA_CHANNEL_ID,TimerService.FOCUS_CHANNEL)
        if(!launch(c,intent))openAppSettings(c)
    }
    fun openLiveSettings(c:Context){
        // Official API 36 Settings.ACTION_APP_NOTIFICATION_PROMOTION_SETTINGS value.
        val intent=Intent("android.settings.APP_NOTIFICATION_PROMOTION_SETTINGS").putExtra(Settings.EXTRA_APP_PACKAGE,c.packageName)
        if(Build.VERSION.SDK_INT<36||!launch(c,intent))openAppSettings(c)
    }
    private fun launch(c:Context,intent:Intent)=runCatching{c.startActivity(intent);true}.getOrDefault(false)
}
