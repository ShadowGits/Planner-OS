package dev.planneros.android

import android.content.Context
import android.content.Intent
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.CancellationException
import androidx.work.*
import java.util.concurrent.TimeUnit

/** A durable outbox: a timer can end offline without losing its exact seconds. */
internal object FocusWorkLogs {
    private val lock=Any()
    private val sync=Mutex()
    @Volatile var foreground=0
    @Volatile var promptOpen=false
    private fun prefs(c:Context)=c.getSharedPreferences("work-outbox",Context.MODE_PRIVATE)
    fun entries(c:Context):List<JSONObject> = synchronized(lock){
        val data=runCatching{JSONArray(prefs(c).getString("entries","[]"))}.getOrDefault(JSONArray())
        (0 until data.length()).mapNotNull{data.optJSONObject(it)}.filter{it.optLong("generation")==SecureConfig(c).generation}
    }
    private fun write(c:Context,rows:List<JSONObject>){check(prefs(c).edit().putString("entries",JSONArray(rows).toString()).commit()){"Time couldn't be saved on this device. Keep this timer open."}}
    fun capture(c:Context,s:TimerState,mandatory:Boolean):JSONObject = synchronized(lock){
        entries(c).find{it.optString("id")==s.sessionId}?.let{return@synchronized it}
        val elapsed=s.elapsed(SystemClock.elapsedRealtime(),System.currentTimeMillis(),TimerStore.boot(c))
        val row=JSONObject().put("id",s.sessionId).put("task_ref",s.taskId).put("title",s.title)
            .put("generation",SecureConfig(c).generation).put("seconds",WorkLogPolicy.elapsedSeconds(if(mandatory)s.durationMs else elapsed))
            .put("mandatory",mandatory).put("needs_input",mandatory)
        if(!mandatory)row.put("body",JSONObject().put("request_id",s.sessionId).put("seconds",row.getInt("seconds")).put("source","timer").put("finish",true))
        write(c,entries(c)+row);if(!mandatory)scheduleSync(c);row
    }
    fun prepare(c:Context,id:String,task:String,title:String,body:JSONObject,mandatory:Boolean){synchronized(lock){
        val rows=entries(c);val existing=rows.find{it.optString("id")==id}
        // After an uncertain response, resend the identical body and save id.
        val row=existing?:JSONObject().put("id",id).put("task_ref",task).put("title",title).put("generation",SecureConfig(c).generation).put("mandatory",mandatory)
        if(!row.has("body"))row.put("body",body).put("seconds",body.getInt("seconds"))
        row.put("needs_input",false);write(c,rows.filterNot{it.optString("id")==id}+row)
        scheduleSync(c)
    }}
    suspend fun submit(c:Context,row:JSONObject):JSONObject=sync.withLock{
        val repo=PlannerRepository(c)
        check(row.optLong("generation")==repo.config.generation){"Connection changed. This entry belongs to the previous connection."}
        val result=repo.request("POST","/v2/day/tasks/${java.net.URLEncoder.encode(row.getString("task_ref"),"UTF-8")}/work",row.getJSONObject("body")).getJSONObject("data")
        synchronized(lock){write(c,entries(c).filterNot{it.optString("id")==row.optString("id")})}
        Reminders.invalidateSchedule(c)
        TimerSounds.clearWork(c,row.getString("id"))
        result
    }
    suspend fun syncReady(c:Context):Boolean {for(row in entries(c).filter{it.has("body")}){try{submit(c,row)}catch(e:CancellationException){throw e}catch(_:Exception){return false}};return true}
    private fun scheduleSync(c:Context){WorkManager.getInstance(c).enqueueUniqueWork("actual-work-sync",ExistingWorkPolicy.APPEND_OR_REPLACE,OneTimeWorkRequestBuilder<WorkLogSyncWorker>().setInitialDelay(30,TimeUnit.SECONDS).setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build())}
    fun next(c:Context)=entries(c).firstOrNull{it.optBoolean("mandatory")}
    fun restoreNotifications(c:Context){
        val manager=c.getSystemService(android.app.NotificationManager::class.java)
        val active=manager.activeNotifications.map{it.id}.toSet()
        entries(c).filter{it.optBoolean("mandatory")}.forEach{row->
            if(TimerSounds.workId(row.getString("id")) !in active)TimerSounds.completed(c,TimerState(row.getString("task_ref"),row.getString("title"),1,sessionId=row.getString("id")),true)
        }
    }
    fun clearNotifications(c:Context){entries(c).forEach{TimerSounds.clearWork(c,it.getString("id"))}}
    fun allowEditing(c:Context,id:String){synchronized(lock){val rows=entries(c);rows.find{it.optString("id")==id}?.apply{remove("body");put("needs_input",true)};write(c,rows)}}
    fun open(c:Context,task:String,id:String?=null){
        if(promptOpen)return
        val pendingId=id?:entries(c).firstOrNull{it.optString("task_ref")==task}?.optString("id")
        promptOpen=true
        try{c.startActivity(Intent(c,WorkLogActivity::class.java).putExtra("task_ref",task).putExtra("work_id",pendingId).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP))}catch(e:Exception){promptOpen=false;throw e}
    }
    fun prompt(c:Context){if(!promptOpen&&foreground>0)next(c)?.let{open(c,it.getString("task_ref"),it.getString("id"))}}
    fun finishTimer(c:Context,s:TimerState):Boolean {
        val elapsed=s.elapsed(SystemClock.elapsedRealtime(),System.currentTimeMillis(),TimerStore.boot(c))
        val mandatory=WorkLogPolicy.requiresActualEntry(s,elapsed)
        capture(c,s,mandatory)
        TimerStore.action(c,"STOP",s.sessionId)
        if(mandatory)open(c,s.taskId,s.sessionId)
        return mandatory
    }
}

class WorkLogSyncWorker(c:Context,p:WorkerParameters):CoroutineWorker(c,p){
    override suspend fun doWork()=if(FocusWorkLogs.syncReady(applicationContext))Result.success()else Result.retry()
}
