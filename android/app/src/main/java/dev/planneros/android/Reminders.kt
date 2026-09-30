package dev.planneros.android

import android.Manifest
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import org.json.JSONArray
import org.json.JSONObject
import java.time.*
import java.util.concurrent.TimeUnit

object Reminders {
    private val lock=Any()
    fun setup(c:Context){
        val manager=WorkManager.getInstance(c)
        if(SecureConfig(c).reminders){
            val constraints=Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
            manager.enqueueUniquePeriodicWork("planner-reminders",ExistingPeriodicWorkPolicy.UPDATE,PeriodicWorkRequestBuilder<ReminderWorker>(15,TimeUnit.MINUTES).setConstraints(constraints).build())
            manager.enqueueUniqueWork("planner-refresh",ExistingWorkPolicy.KEEP,OneTimeWorkRequestBuilder<ReminderWorker>().setConstraints(constraints).build())
        }else{manager.cancelUniqueWork("planner-reminders");manager.cancelUniqueWork("planner-refresh");cancelAlarms(c)}
    }
    private fun alarmIntent(c:Context,id:String)=Intent(c,ReminderReceiver::class.java).setAction("dev.planneros.REMINDER").setData(android.net.Uri.parse("planneros://reminder/${android.net.Uri.encode(id)}"))
    private fun pending(c:Context,id:String,flags:Int,intent:Intent=alarmIntent(c,id)):PendingIntent?=PendingIntent.getBroadcast(c,0,intent,flags or PendingIntent.FLAG_IMMUTABLE)
    fun cancelAlarms(c:Context){val prefs=c.getSharedPreferences("reminders",Context.MODE_PRIVATE);val manager=c.getSystemService(AlarmManager::class.java);prefs.getStringSet("alarms",emptySet()).orEmpty().forEach{id->pending(c,id,PendingIntent.FLAG_NO_CREATE)?.let{manager.cancel(it);it.cancel()}};prefs.edit().remove("alarms").apply()}
    fun schedule(c:Context,day:Day){
        if(!SecureConfig(c).reminders)return
        cancelAlarms(c)
        val prefs=c.getSharedPreferences("reminders",Context.MODE_PRIVATE)
        prefs.edit().putString("zone",day.timezone).apply()
        val manager=c.getSystemService(AlarmManager::class.java);val ids=mutableSetOf<String>();val now=System.currentTimeMillis()
        for(task in day.tasks.filter{!it.done&&it.time!=null}){
            val minutes=task.clockMinutes
            val startLocal=LocalDate.parse(day.date).atStartOfDay(ZoneId.of(day.timezone)).plusMinutes(minutes.toLong())
            val alarmDate=startLocal.toLocalDate().toString()
            val start=startLocal.toInstant().toEpochMilli()
            for(lead in listOf(30,5)){
                val trigger=start-lead*60_000L;if(trigger<=now)continue
                val id="$alarmDate:event$lead:${task.id}";ids.add(id)
                val clock="%02d:%02d".format((minutes/60)%24,minutes%60)
                val i=alarmIntent(c,id).putExtra("kind","event$lead:${task.id}").putExtra("date",alarmDate).putExtra("title","${if(lead==30) "🟡" else "🟢"} IN $lead MINUTES : ${task.title}").putExtra("body","Starts at $clock · ${task.minutes} min")
                val pi=pending(c,id,PendingIntent.FLAG_UPDATE_CURRENT,i)!!
                if(Build.VERSION.SDK_INT<31||manager.canScheduleExactAlarms())manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,trigger,pi)
                else manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,trigger,pi)
            }
        }
        prefs.edit().putStringSet("alarms",ids).apply()
    }
    fun sent(c:Context,date:String):Set<String> = c.getSharedPreferences("reminders",Context.MODE_PRIVATE).getStringSet("sent:$date",emptySet()).orEmpty()
    fun notify(c:Context,date:String,kind:String,title:String,body:String){synchronized(lock){
        if(!SecureConfig(c).reminders||kind in sent(c,date))return
        if(Build.VERSION.SDK_INT>=33&&ContextCompat.checkSelfPermission(c,Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)return
        val manager=c.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("reminders","Planner reminders",NotificationManager.IMPORTANCE_HIGH))
        val pi=PendingIntent.getActivity(c,0,Intent(c,MainActivity::class.java),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notificationTag=reminderNotificationTag(kind)
        manager.notify(("$date:$notificationTag").hashCode(),NotificationCompat.Builder(c,"reminders").setSmallIcon(R.drawable.ic_notification).setContentTitle(title).setContentText(body).setStyle(NotificationCompat.BigTextStyle().bigText(body)).setAutoCancel(true).setContentIntent(pi).build())
        val p=c.getSharedPreferences("reminders",Context.MODE_PRIVATE)
        p.edit().putStringSet("sent:$date",sent(c,date)+kind).apply()
        // A rolling week is enough to deduplicate retries; retain no permanent reminder history.
        p.all.keys.filter{it.startsWith("sent:")&&it.removePrefix("sent:")<LocalDate.parse(date).minusDays(7).toString()}.forEach{p.edit().remove(it).apply()}
    }}
}
class ReminderReceiver:BroadcastReceiver(){override fun onReceive(c:Context,i:Intent){
    // Canceled or replaced alarms cannot notify after a task edit.
    val id=i.data?.lastPathSegment?:return
    if(id !in c.getSharedPreferences("reminders",Context.MODE_PRIVATE).getStringSet("alarms",emptySet()).orEmpty())return
    Reminders.notify(c,i.getStringExtra("date")?:return,i.getStringExtra("kind")?:return,i.getStringExtra("title")?:"Planner OS",i.getStringExtra("body").orEmpty())
}}
class BootReceiver:BroadcastReceiver(){override fun onReceive(c:Context,i:Intent){if(i.action==Intent.ACTION_BOOT_COMPLETED)Reminders.setup(c)}}
class ReminderWorker(c:Context,p:WorkerParameters):CoroutineWorker(c,p){override suspend fun doWork():Result{
    if(!SecureConfig(applicationContext).reminders)return Result.success()
    return try{
        val repo=PlannerRepository(applicationContext)
        val zone=applicationContext.getSharedPreferences("reminders",Context.MODE_PRIVATE).getString("zone","Asia/Kolkata")!!
        val date=LocalDate.now(ZoneId.of(zone));val day=repo.day(date);Reminders.schedule(applicationContext,day)
        val body=JSONObject().put("sent_kinds",JSONArray(Reminders.sent(applicationContext,day.date).toList()))
        val data=repo.request("POST","/v2/native/reminders",body).getJSONObject("data")
        val a=data.getJSONArray("reminders")
        for(index in 0 until a.length()){val r=a.getJSONObject(index);Reminders.notify(applicationContext,data.getString("date"),r.getString("kind"),r.optString("title",reminderTitle(r.getString("kind"))),r.getString("message"))}
        Result.success()
    }catch(_:Exception){Result.retry()}
}}
