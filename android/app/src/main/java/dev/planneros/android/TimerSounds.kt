package dev.planneros.android

import android.Manifest
import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

/** Event-only sounds. The per-second foreground countdown remains silent. */
object TimerSounds {
    const val START_CHANNEL="focus-start-sound"
    const val END_CHANNEL="focus-completion-sound"
    private const val START_ID=52
    private const val END_ID=53
    fun setup(c:Context){
        val attributes=AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build()
        val manager=c.getSystemService(NotificationManager::class.java)
        for((id,name,resource) in listOf(Triple(START_CHANNEL,"Timer started",R.raw.focus_start),Triple(END_CHANNEL,"Timer finished",R.raw.focus_complete))){
            manager.createNotificationChannel(NotificationChannel(id,name,NotificationManager.IMPORTANCE_DEFAULT).apply{
                setSound(Uri.parse("android.resource://${c.packageName}/raw/${c.resources.getResourceEntryName(resource)}"),attributes)
                enableVibration(false);setShowBadge(false);lockscreenVisibility=Notification.VISIBILITY_PUBLIC
            })
        }
    }
    fun clear(c:Context){val m=c.getSystemService(NotificationManager::class.java);m.cancel(START_ID);m.cancel(END_ID)}
    fun started(c:Context,s:TimerState){c.getSystemService(NotificationManager::class.java).cancel(START_ID);post(c,s,false)}
    fun completed(c:Context,s:TimerState)=post(c,s,true)
    private fun post(c:Context,s:TimerState,finished:Boolean){
        if(Build.VERSION.SDK_INT>=33&&ContextCompat.checkSelfPermission(c,Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)return
        val manager=c.getSystemService(NotificationManager::class.java)
        if(!manager.areNotificationsEnabled())return
        val open=Intent(c,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        if(finished)open.putExtra("finish_timer",s.taskId)
        val pending=PendingIntent.getActivity(c,if(finished)53 else 52,open,PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification=NotificationCompat.Builder(c,if(finished)END_CHANNEL else START_CHANNEL)
            .setSmallIcon(R.drawable.ic_notification).setContentTitle(s.title)
            .setContentText(if(finished)"Time block finished · tap to finish or continue in overtime" else "Focus timer started")
            .setContentIntent(pending).setAutoCancel(true).setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
        if(!finished)notification.setTimeoutAfter(5000)
        try{manager.notify(if(finished)END_ID else START_ID,notification.build())}catch(_:SecurityException){/* Permission changed while posting. */}
    }
}
