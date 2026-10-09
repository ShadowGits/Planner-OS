package dev.planneros.android

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Automatic focus has its own epoch: stopping today's timer must not cancel tomorrow's alarm. */
object AutoFocusScheduler {
    private val lock=Any()
    private fun prefs(c:Context)=c.getSharedPreferences("auto-focus",Context.MODE_PRIVATE)
    fun enabled(c:Context)=prefs(c).getBoolean("enabled",true)
    fun backgroundAvailable(c:Context)=Build.VERSION.SDK_INT<31||c.getSystemService(AlarmManager::class.java).canScheduleExactAlarms()
    private fun blocks(c:Context):List<AutoFocusBlock> = runCatching {
        val a=JSONArray(prefs(c).getString("blocks","[]"))
        List(a.length()){index->val j=a.getJSONObject(index);AutoFocusBlock(j.getString("id"),j.getString("title"),j.getLong("start"),j.getLong("end"),j.getString("date"))}
    }.getOrDefault(emptyList())
    private fun write(c:Context,blocks:List<AutoFocusBlock>){
        val a=JSONArray()
        blocks.forEach{a.put(JSONObject().put("id",it.id).put("title",it.title).put("start",it.startMillis).put("end",it.endMillis).put("date",it.originDate))}
        prefs(c).edit().putString("blocks",a.toString()).commit()
    }
    private fun alarmIntent(c:Context,occurrence:String)=Intent(c,AutoFocusReceiver::class.java)
        .setAction("dev.planneros.AUTO_FOCUS").setData(Uri.parse("planneros://auto-focus/${Uri.encode(occurrence)}"))
    private fun pending(c:Context,occurrence:String,flags:Int,i:Intent=alarmIntent(c,occurrence))=
        PendingIntent.getBroadcast(c,0,i,flags or PendingIntent.FLAG_IMMUTABLE)
    private fun cancelAlarms(c:Context,rotate:Boolean=true){
        val p=prefs(c);val manager=c.getSystemService(AlarmManager::class.java)
        p.getStringSet("alarms",emptySet()).orEmpty().forEach{token->pending(c,token,PendingIntent.FLAG_NO_CREATE)?.let{manager.cancel(it);it.cancel()}}
        val edit=p.edit().remove("alarms")
        if(rotate||p.getString("epoch",null)==null)edit.putString("epoch",UUID.randomUUID().toString())
        edit.commit()
    }
    private fun arm(c:Context){
        // A valid alarm already delivered to the service must survive a fresh
        // snapshot/re-arm. claim() still validates its current occurrence.
        cancelAlarms(c,false)
        if(!TimerPreferences.enabled(c)||!enabled(c)||!backgroundAvailable(c))return
        val p=prefs(c);val now=System.currentTimeMillis();val epoch=p.getString("epoch",null)!!
        val future=blocks(c).filter{it.startMillis>now&&it.startMillis<now+7*86_400_000L}
            .sortedWith(compareBy<AutoFocusBlock>{it.startMillis}.thenBy{it.id}).take(256)
        p.edit().putStringSet("alarms",future.map{it.occurrence}.toSet()).commit()
        val manager=c.getSystemService(AlarmManager::class.java)
        future.forEach{block->
            val i=alarmIntent(c,block.occurrence).putExtra("auto_epoch",epoch)
                .putExtra("connection_generation",SecureConfig(c).generation)
            try{manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,block.startMillis,pending(c,block.occurrence,PendingIntent.FLAG_UPDATE_CURRENT,i)!!)}
            catch(_:SecurityException){cancelAlarms(c);return}
        }
    }
    fun setEnabled(c:Context,value:Boolean)=synchronized(lock){prefs(c).edit().putBoolean("enabled",value).commit();if(!value)cancelAlarms(c)else arm(c)}
    fun trackingChanged(c:Context)=synchronized(lock){
        cancelAlarms(c)
        val p=prefs(c);val now=System.currentTimeMillis()
        val active=blocks(c).filter{it.startMillis<=now&&now<it.endMillis}.map{it.occurrence}
        p.edit().putStringSet("consumed",p.getStringSet("consumed",emptySet()).orEmpty()+active).commit()
        arm(c)
    }
    fun rearm(c:Context)=synchronized(lock){arm(c)}
    fun reset(c:Context)=synchronized(lock){
        val p=prefs(c);val setting=enabled(c);cancelAlarms(c)
        p.edit().clear().putBoolean("enabled",setting).putString("epoch",UUID.randomUUID().toString()).commit()
    }
    fun invalidateTask(c:Context,id:String)=synchronized(lock){write(c,blocks(c).filterNot{it.id==id});arm(c)}
    fun invalidate(c:Context)=synchronized(lock){write(c,emptyList());cancelAlarms(c)}
    fun sync(c:Context,day:Day)=synchronized(lock){
        if(day.cached||day.connectionGeneration!=SecureConfig(c).generation||day.alarmRevision?.let{it!=Reminders.revision(c)}==true)return@synchronized
        val now=System.currentTimeMillis()
        val fresh=day.tasks.mapNotNull{task->autoFocusBlock(task.id,task.title,task.clockMinutes,task.minutes,task.done,day.date,day.timezone,task.remainingSeconds)}
        val merged=(blocks(c).filter{it.originDate!=day.date&&it.endMillis>now}+fresh)
            .associateBy{it.occurrence}.values.toList()
        write(c,merged)
        // Bound history while keeping paused/canceled occurrences across process death.
        val p=prefs(c);val consumed=p.getStringSet("consumed",emptySet()).orEmpty()
        p.edit().putStringSet("consumed",consumed.filter{it.substringAfterLast('@').toLongOrNull()?.let{start->start>now-14*86_400_000L}==true}.toSet()).commit()
        arm(c)
    }
    /** A confirmed edit can move a block to an uncached day without downloading that day. */
    fun syncChanges(c:Context,tasks:List<Task>,origin:String,zone:String)=synchronized(lock){
        val ids=tasks.map{it.id}.toSet()
        val fresh=tasks.mapNotNull{task->
            val date=if(task.clockMinutes<1440)task.date?:origin else origin
            autoFocusBlock(task.id,task.title,task.clockMinutes,task.minutes,task.done,date,zone,task.remainingSeconds)
        }
        write(c,(blocks(c).filterNot{it.id in ids}+fresh).distinctBy{it.occurrence});arm(c)
    }
    private fun request(c:Context,block:AutoFocusBlock,epoch:String,generation:Long):Intent =
        TimerStore.intent(c,"AUTO_START").putExtra("occurrence",block.occurrence)
            .putExtra("auto_epoch",epoch).putExtra("connection_generation",generation)
    /** Called only while the Activity is foreground; no background permission fallback. */
    fun catchUp(c:Context)=synchronized(lock){
        if(!TimerPreferences.enabled(c)||!enabled(c))return@synchronized
        val p=prefs(c);val block=autoFocusCandidate(blocks(c),System.currentTimeMillis(),p.getStringSet("consumed",emptySet()).orEmpty())?:return@synchronized
        try{c.startForegroundService(request(c,block,p.getString("epoch",null)?:return@synchronized,SecureConfig(c).generation))}
        catch(_:IllegalStateException){}catch(_:SecurityException){}
    }
    fun receive(c:Context,i:Intent)=synchronized(lock){
        val token=i.data?.lastPathSegment?:return@synchronized;val p=prefs(c)
        if(!TimerPreferences.enabled(c)||!enabled(c)||!backgroundAvailable(c)||token !in p.getStringSet("alarms",emptySet()).orEmpty()||
            i.getStringExtra("auto_epoch")!=p.getString("epoch",null)||i.getLongExtra("connection_generation",-1)!=SecureConfig(c).generation)return@synchronized
        val block=autoFocusCandidate(blocks(c),System.currentTimeMillis(),p.getStringSet("consumed",emptySet()).orEmpty())?:return@synchronized
        try{c.startForegroundService(request(c,block,i.getStringExtra("auto_epoch")!!,i.getLongExtra("connection_generation",-1)))}
        catch(_:IllegalStateException){}catch(_:SecurityException){}
    }
    /** The service atomically validates and claims immediately before changing timer state. */
    fun claim(c:Context,i:Intent):AutoFocusBlock?=synchronized(lock){
        val p=prefs(c)
        if(!TimerPreferences.enabled(c)||!enabled(c)||i.getStringExtra("auto_epoch")!=p.getString("epoch",null)||
            i.getLongExtra("connection_generation",-1)!=SecureConfig(c).generation)return@synchronized null
        val consumed=p.getStringSet("consumed",emptySet()).orEmpty()
        val block=autoFocusCandidate(blocks(c),System.currentTimeMillis(),consumed)?:return@synchronized null
        if(block.occurrence!=i.getStringExtra("occurrence"))return@synchronized null
        // Retire older overlapping blocks too: ending the winning block must
        // not cause catch-up to unexpectedly restart an earlier one.
        val retired=blocks(c).filter{it.startMillis<=block.startMillis&&it.endMillis>System.currentTimeMillis()}.map{it.occurrence}
        if(!p.edit().putStringSet("consumed",consumed+retired).commit())return@synchronized null
        block
    }
    /** Manual pause/cancel/start should consume the active scheduled occurrence too. */
    fun suppressTask(c:Context,id:String)=synchronized(lock){
        val now=System.currentTimeMillis();val p=prefs(c)
        val tokens=blocks(c).filter{it.id==id&&it.startMillis<=now&&now<it.endMillis}.map{it.occurrence}
        p.edit().putStringSet("consumed",p.getStringSet("consumed",emptySet()).orEmpty()+tokens).commit()
    }
}

class AutoFocusReceiver:BroadcastReceiver(){override fun onReceive(c:Context,i:Intent){AutoFocusScheduler.receive(c,i)}}
