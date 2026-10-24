package dev.planneros.android

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

internal data class TaskUpdateFailure(val id:String,val generation:Long,val message:String,val detail:String)

/** Saving survives activity recreation and opening Dashboard. Errors remain until dismissed. */
internal object TaskUpdateAlerts {
    val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    val failures=MutableStateFlow<List<TaskUpdateFailure>>(emptyList())
    private val lock=Mutex()
    private fun store(c:Context)=c.getSharedPreferences("task-update-errors",Context.MODE_PRIVATE)
    private fun read(c:Context):List<TaskUpdateFailure> {
        val rows=runCatching{JSONArray(store(c).getString("errors","[]"))}.getOrDefault(JSONArray())
        return (0 until rows.length()).mapNotNull{i->runCatching{rows.getJSONObject(i).let{
            TaskUpdateFailure(it.getString("id"),it.getLong("generation"),it.getString("message"),it.optString("detail"))
        }}.getOrNull()}
    }
    private fun persist(c:Context,rows:List<TaskUpdateFailure>) {
        store(c).edit().putString("errors",JSONArray(rows.map{JSONObject().put("id",it.id).put("generation",it.generation)
            .put("message",it.message).put("detail",it.detail)}).toString()).commit()
        failures.value=rows
    }
    suspend fun restore(c:Context)=withContext(Dispatchers.IO){lock.withLock{failures.value=read(c)}}
    suspend fun dismiss(c:Context,id:String)=withContext(Dispatchers.IO){lock.withLock{
        persist(c,read(c).filterNot{it.id==id})
        c.getSystemService(NotificationManager::class.java).cancel(id,0)
    }}
    suspend fun reverted(c:Context,generation:Long,before:Day,after:Day,error:Exception)=withContext(Dispatchers.IO){lock.withLock{
        if(SecureConfig(c).generation!=generation)return@withLock
        val detail=if(error is PlannerHttpException)error.message.orEmpty() else if(error is java.io.IOException)"The server couldn't be reached. Check your connection and try again."
            else error.message?:"The server couldn't save this update."
        val failure=TaskUpdateFailure(UUID.randomUUID().toString(),generation,revertedUpdateMessage(before,after),detail)
        persist(c,listOf(failure)+read(c).filter{it.generation==generation})
        if(Build.VERSION.SDK_INT>=33&&ContextCompat.checkSelfPermission(c,Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)return@withLock
        val manager=c.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("sync-errors","Changes that couldn't be saved",NotificationManager.IMPORTANCE_DEFAULT))
        val open=PendingIntent.getActivity(c,0,Intent(c,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notice=NotificationCompat.Builder(c,"sync-errors").setSmallIcon(R.drawable.ic_notification)
            .setColor(0xFF722F37.toInt()).setContentTitle("Task change reverted").setContentText(failure.message)
            .setStyle(NotificationCompat.BigTextStyle().bigText("${failure.message}\n$detail"))
            .setContentIntent(open).setAutoCancel(true).build()
        runCatching{manager.notify(failure.id,0,notice)}
    }}
}
