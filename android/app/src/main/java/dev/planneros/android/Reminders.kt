package dev.planneros.android

import android.Manifest
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import kotlinx.coroutines.CancellationException
import org.json.JSONArray
import org.json.JSONObject
import java.time.*
import java.util.UUID
import java.util.concurrent.TimeUnit

data class ReminderSession(val connection:Long,val epoch:String)

object Reminders {
    private val lock=Any()
    private fun prefs(c:Context)=c.getSharedPreferences("reminders",Context.MODE_PRIVATE)
    fun revision(c:Context):Long=prefs(c).getLong("schedule_revision",0L)
    fun invalidateSchedule(c:Context)=synchronized(lock){
        prefs(c).edit().putLong("schedule_revision",revision(c)+1).commit()
    }
    fun session(c:Context):ReminderSession=synchronized(lock){
        val p=prefs(c)
        val epoch=p.getString("epoch",null)?:UUID.randomUUID().toString().also{p.edit().putString("epoch",it).commit()}
        ReminderSession(SecureConfig(c).generation,epoch)
    }
    private fun matches(c:Context,expected:ReminderSession)=expected==session(c)
    fun setup(c:Context){
        val manager=WorkManager.getInstance(c)
        if(!SecureConfig(c).reminders)synchronized(lock){
            cancelAlarms(c)
            prefs(c).edit().putString("epoch",UUID.randomUUID().toString()).commit()
        }
        if(SecureConfig(c).configured&&(SecureConfig(c).reminders||AutoFocusScheduler.enabled(c))){
            val constraints=Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
            manager.enqueueUniquePeriodicWork("planner-reminders",ExistingPeriodicWorkPolicy.UPDATE,PeriodicWorkRequestBuilder<ReminderWorker>(15,TimeUnit.MINUTES).setConstraints(constraints).build())
            if(System.currentTimeMillis()-prefs(c).getLong("last_refresh",0L)>15*60*1000L)
                manager.enqueueUniqueWork("planner-refresh",ExistingWorkPolicy.KEEP,OneTimeWorkRequestBuilder<ReminderWorker>().setConstraints(constraints).build())
        }else{synchronized(lock){
            manager.cancelUniqueWork("planner-reminders");manager.cancelUniqueWork("planner-refresh");cancelAlarms(c)
            // Turning reminders off invalidates an in-flight worker even if
            // the user switches them on again before cancellation completes.
            prefs(c).edit().putString("epoch",UUID.randomUUID().toString()).commit()
        }}
    }
    private fun alarmIntent(c:Context,id:String)=Intent(c,ReminderReceiver::class.java).setAction("dev.planneros.REMINDER").setData(android.net.Uri.parse("planneros://reminder/${android.net.Uri.encode(id)}"))
    private fun pending(c:Context,id:String,flags:Int,intent:Intent=alarmIntent(c,id)):PendingIntent?=PendingIntent.getBroadcast(c,0,intent,flags or PendingIntent.FLAG_IMMUTABLE)
    fun cancelAlarms(c:Context)=synchronized(lock){
        val p=prefs(c);val manager=c.getSystemService(AlarmManager::class.java)
        p.getStringSet("alarms",emptySet()).orEmpty().forEach{id->pending(c,id,PendingIntent.FLAG_NO_CREATE)?.let{manager.cancel(it);it.cancel()}}
        p.edit().remove("alarms").putString("alarm_generation",UUID.randomUUID().toString()).commit()
    }
    fun reset(c:Context)=synchronized(lock){
        val manager=WorkManager.getInstance(c)
        manager.cancelUniqueWork("planner-reminders");manager.cancelUniqueWork("planner-refresh")
        cancelAlarms(c)
        AutoFocusScheduler.reset(c)
        // Epoch changes before the new config is saved: an old worker cannot
        // re-arm an alarm in that reset/save interval, even if its response arrived.
        prefs(c).edit().clear().putString("epoch",UUID.randomUUID().toString()).commit()
        c.getSystemService(NotificationManager::class.java).cancelAll()
    }
    fun cancelTask(c:Context,taskId:String)=synchronized(lock){
        val p=prefs(c);val ids=p.getStringSet("alarms",emptySet()).orEmpty();val manager=c.getSystemService(AlarmManager::class.java)
        val removed=ids.filter{it.endsWith(":$taskId")}.toSet()
        removed.forEach{id->pending(c,id,PendingIntent.FLAG_NO_CREATE)?.let{manager.cancel(it);it.cancel()}}
        p.edit().putStringSet("alarms",ids-removed).putLong("schedule_revision",revision(c)+1).commit()
        AutoFocusScheduler.invalidateTask(c,taskId)
        val notifications=c.getSystemService(NotificationManager::class.java)
        notifications.activeNotifications.filter{it.tag?.endsWith(":event:$taskId")==true}
            .forEach{notifications.cancel(it.tag,it.id)}
    }
    fun schedule(c:Context,day:Day,expected:ReminderSession=session(c))=synchronized(lock){
        if(!SecureConfig(c).reminders||!matches(c,expected))return@synchronized
        // The worker/UI use fresh responses; cached/offline days must never
        // resurrect deleted or completed tasks' scheduled notifications.
        if(day.cached||day.alarmRevision?.let{it!=revision(c)}==true)return@synchronized
        val now=System.currentTimeMillis()
        val alarms=day.tasks.filter{!it.done&&it.time!=null}.flatMap{task->
            taskReminderAlarms(task.id,task.title,task.clockMinutes,task.minutes,day.date,day.timezone,now)
        }
        cancelAlarms(c)
        val p=prefs(c);val generation=UUID.randomUUID().toString()
        // Store membership before setting alarms, so even an alarm firing
        // immediately is valid. Generation rejects an already-delivered old
        // broadcast with the same task ID after its time/title was edited.
        p.edit().putString("zone",day.timezone).putString("alarm_generation",generation)
            .putStringSet("alarms",alarms.map{it.id}.toSet()).commit()
        val manager=c.getSystemService(AlarmManager::class.java)
        alarms.forEach{alarm->
            val i=alarmIntent(c,alarm.id).putExtra("kind",alarm.kind).putExtra("date",alarm.date)
                .putExtra("title",alarm.title).putExtra("body",alarm.body).putExtra("alarm_generation",generation)
                .putExtra("connection_generation",expected.connection).putExtra("epoch",expected.epoch)
            val pi=pending(c,alarm.id,PendingIntent.FLAG_UPDATE_CURRENT,i)!!
            try{
                if(Build.VERSION.SDK_INT<31||manager.canScheduleExactAlarms())manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,alarm.triggerMillis,pi)
                else manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,alarm.triggerMillis,pi)
            }catch(_:SecurityException){
                // Exact alarm permission can be revoked between checking and
                // scheduling; preserve the reminder using Android's fallback.
                manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,alarm.triggerMillis,pi)
            }
        }
    }
    fun sent(c:Context,date:String):Set<String> = prefs(c).getStringSet("sent:$date",emptySet()).orEmpty().toSet()
    /** Test the real reminder channel without enabling reminders or changing delivery history. */
    fun test(c:Context):Boolean {
        if(Build.VERSION.SDK_INT>=33&&ContextCompat.checkSelfPermission(c,Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)return false
        val manager=c.getSystemService(NotificationManager::class.java)
        if(!manager.areNotificationsEnabled())return false
        manager.createNotificationChannel(NotificationChannel("reminders","Planner reminders",NotificationManager.IMPORTANCE_HIGH))
        if(manager.getNotificationChannel("reminders")?.importance==NotificationManager.IMPORTANCE_NONE)return false
        val open=PendingIntent.getActivity(c,0,Intent(c,MainActivity::class.java),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return try {
            manager.notify("planner-notification-test",62,NotificationCompat.Builder(c,"reminders")
                .setSmallIcon(R.drawable.ic_notification).setContentTitle("Planner OS notifications work")
                .setContentText("Your Android reminder channel is ready.").setAutoCancel(true).setContentIntent(open).build())
            true
        }catch(_:SecurityException){false}
    }
    fun notify(c:Context,date:String,kind:String,title:String,body:String,expected:ReminderSession=session(c),expectedRevision:Long?=null)=synchronized(lock){
        if(!SecureConfig(c).reminders||!matches(c,expected)||kind in sent(c,date)||expectedRevision?.let{it!=revision(c)}==true)return@synchronized
        if(Build.VERSION.SDK_INT>=33&&ContextCompat.checkSelfPermission(c,Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)return@synchronized
        val manager=c.getSystemService(NotificationManager::class.java)
        if(!manager.areNotificationsEnabled())return@synchronized
        manager.createNotificationChannel(NotificationChannel("reminders","Planner reminders",NotificationManager.IMPORTANCE_HIGH))
        if(manager.getNotificationChannel("reminders")?.importance==NotificationManager.IMPORTANCE_NONE)return@synchronized
        val pi=PendingIntent.getActivity(c,0,Intent(c,MainActivity::class.java),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notificationTag=reminderNotificationTag(kind)
        // A string tag avoids hash collisions replacing another task's alert.
        manager.notify("$date:$notificationTag",61,NotificationCompat.Builder(c,"reminders").setSmallIcon(R.drawable.ic_notification).setContentTitle(title).setContentText(body).setStyle(NotificationCompat.BigTextStyle().bigText(body)).setAutoCancel(true).setContentIntent(pi).build())
        val p=prefs(c)
        p.edit().putStringSet("sent:$date",sent(c,date)+kind).commit()
        val cutoff=LocalDate.parse(date).minusDays(7).toString()
        val edit=p.edit()
        p.all.keys.filter{it.startsWith("sent:")&&it.removePrefix("sent:")<cutoff}.forEach{edit.remove(it)}
        edit.apply()
    }
    fun receive(c:Context,i:Intent)=synchronized(lock){
        val id=i.data?.lastPathSegment?:return@synchronized
        val p=prefs(c)
        if(id !in p.getStringSet("alarms",emptySet()).orEmpty()||i.getStringExtra("alarm_generation")!=p.getString("alarm_generation",null))return@synchronized
        val expected=ReminderSession(i.getLongExtra("connection_generation",-1),i.getStringExtra("epoch")?:return@synchronized)
        val date=i.getStringExtra("date")?:return@synchronized;val kind=i.getStringExtra("kind")?:return@synchronized
        notify(c,date,kind,i.getStringExtra("title")?:"Planner OS",i.getStringExtra("body").orEmpty(),expected)
        // Fired IDs are retired; stale broadcasts cannot notify again even if
        // notification permission was denied and the ledger stayed untouched.
        p.edit().putStringSet("alarms",p.getStringSet("alarms",emptySet()).orEmpty()-id).commit()
    }
}
class ReminderReceiver:BroadcastReceiver(){override fun onReceive(c:Context,i:Intent){Reminders.receive(c,i)}}
class BootReceiver:BroadcastReceiver(){override fun onReceive(c:Context,i:Intent){
    if(i.action==Intent.ACTION_BOOT_COMPLETED||i.action==AlarmManager.ACTION_SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED){FocusWorkLogs.restoreNotifications(c);Reminders.cancelAlarms(c);AutoFocusScheduler.rearm(c);Reminders.setup(c)}
}}
class ReminderWorker(c:Context,p:WorkerParameters):CoroutineWorker(c,p){override suspend fun doWork():Result{
    val c=applicationContext
    if(!SecureConfig(c).configured||(!SecureConfig(c).reminders&&!AutoFocusScheduler.enabled(c)))return Result.success()
    val session=Reminders.session(c)
    val workerPrefs=c.getSharedPreferences("reminders",Context.MODE_PRIVATE)
    if(System.currentTimeMillis()-workerPrefs.getLong("last_refresh",0L) in 0 until 15*60*1000L)return Result.success()
    return try{
        val repo=PlannerRepository(c)
        val zone=c.getSharedPreferences("reminders",Context.MODE_PRIVATE).getString("zone","Asia/Kolkata")!!
        if(repo.hasPendingSnapshots())return Result.retry()
        suspend fun scheduleDay(date:LocalDate,ttl:Long)=repo.confirmedCached(date,ttl)?:repo.day(date)
        var day=scheduleDay(LocalDate.now(ZoneId.of(zone)),30*60*1000L)
        val actualDate=LocalDate.now(ZoneId.of(day.timezone))
        if(day.date!=actualDate.toString())day=scheduleDay(actualDate,30*60*1000L)
        AutoFocusScheduler.sync(c,day)
        Reminders.schedule(c,day,session)
        // Tomorrow's exact starts remain armed while the app stays closed.
        if(AutoFocusScheduler.enabled(c))AutoFocusScheduler.sync(c,scheduleDay(actualDate.plusDays(1),6*60*60*1000L))
        if(!SecureConfig(c).reminders){workerPrefs.edit().putLong("last_refresh",System.currentTimeMillis()).apply();return Result.success()}
        fun ledger(date:String)=JSONObject().put("sent_kinds",JSONArray(Reminders.sent(c,date).toList()))
        var sentDate=day.date
        val responseRevision=Reminders.revision(c)
        var data=repo.request("POST","/v2/native/reminders",ledger(sentDate)).getJSONObject("data")
        // The server's local day is authoritative. A response crossing
        // midnight must use that day's ledger, not suppress another day's kinds.
        if(data.getString("date")!=sentDate){
            sentDate=data.getString("date")
            data=repo.request("POST","/v2/native/reminders",ledger(sentDate)).getJSONObject("data")
        }
        if(data.getString("date")!=sentDate||responseRevision!=Reminders.revision(c))return Result.retry()
        val a=data.getJSONArray("reminders")
        for(index in 0 until a.length()){
            val r=a.getJSONObject(index)
            Reminders.notify(c,sentDate,r.getString("kind"),r.optString("title",reminderTitle(r.getString("kind"))),r.getString("message"),session,responseRevision)
        }
        workerPrefs.edit().putLong("last_refresh",System.currentTimeMillis()).apply()
        Result.success()
    }catch(cancelled:CancellationException){throw cancelled}catch(_:Exception){Result.retry()}
}}
