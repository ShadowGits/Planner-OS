package dev.planneros.android

import android.app.Activity
import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Paint
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.RemoteViews
import android.widget.RemoteViewsService
import androidx.work.*
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.UUID
import java.util.concurrent.TimeUnit

data class WidgetOpenRequest(val widget:Int,val generation:Long,val date:String,val task:String?)

internal object TimelineWidgetStore {
    fun prefs(c:Context)=c.getSharedPreferences("timeline-widget",Context.MODE_PRIVATE)
    fun ids(c:Context)=AppWidgetManager.getInstance(c).getAppWidgetIds(ComponentName(c,TimelineWidgetProvider::class.java))
    fun zone(c:Context):ZoneId {
        val generation=SecureConfig(c).generation
        val latest=c.getSharedPreferences("day-cache",Context.MODE_PRIVATE).all.filterKeys{it.startsWith("$generation:")}
            .values.mapNotNull{(it as? String)?.let{raw->runCatching{org.json.JSONObject(raw)}.getOrNull()}}
            .maxByOrNull{it.optLong("_saved_at")}
        return runCatching{ZoneId.of(latest?.optString("timezone","Asia/Kolkata")?:"Asia/Kolkata")}.getOrDefault(ZoneId.of("Asia/Kolkata"))
    }
    fun date(c:Context,id:Int):LocalDate = prefs(c).getString("date:$id",null)?.let{runCatching{LocalDate.parse(it)}.getOrNull()}
        ?:logicalToday(ZonedDateTime.now(zone(c)))
    fun select(c:Context,id:Int,date:LocalDate?) { prefs(c).edit().apply{if(date==null)remove("date:$id")else putString("date:$id",date.toString())}.apply() }
    fun statusKey(generation:Long,task:String)="status:$generation:$task"
    fun pending(c:Context,generation:Long,task:String)=prefs(c).getLong("pending:$generation:$task",0).let{it>0&&System.currentTimeMillis()-it in 0..120_000L}
    fun token(c:Context,request:WidgetOpenRequest):String {
        val token=UUID.randomUUID().toString()
        prefs(c).edit().putString("open:$token",org.json.JSONObject().put("widget",request.widget).put("generation",request.generation).put("date",request.date)
            .put("task",request.task?:org.json.JSONObject.NULL).put("expires",System.currentTimeMillis()+60_000).toString()).commit()
        return token
    }
    fun consume(c:Context,token:String?):WidgetOpenRequest? {
        if(token==null)return null
        val raw=prefs(c).getString("open:$token",null)?:return null
        prefs(c).edit().remove("open:$token").commit()
        val j=runCatching{org.json.JSONObject(raw)}.getOrNull()?:return null
        if(j.optLong("expires")<System.currentTimeMillis()||j.optLong("generation")!=SecureConfig(c).generation||j.optInt("widget") !in ids(c))return null
        return WidgetOpenRequest(j.optInt("widget"),j.optLong("generation"),j.getString("date"),j.nullString("task"))
    }
}

object TimelineWidget {
    private val handler=Handler(Looper.getMainLooper())
    private var queued=false
    /** Cache writes paint widgets only. They never trigger a new network request. */
    fun cacheChanged(c:Context) {
        val app=c.applicationContext
        synchronized(this){if(queued)return;queued=true}
        handler.postDelayed({synchronized(this){queued=false};renderAll(app)},100)
    }
    fun renderAll(c:Context) {
        val manager=AppWidgetManager.getInstance(c)
        TimelineWidgetStore.ids(c).forEach{id->runCatching{manager.updateAppWidget(id,views(c,id));manager.notifyAppWidgetViewDataChanged(id,R.id.widget_tasks)}}
        scheduleBoundary(c)
    }
    private fun intent(c:Context,id:Int,date:LocalDate,action:String)=Intent(c,TimelineWidgetProvider::class.java)
        .setAction(action).setData(Uri.parse("planneros://widget/"+widgetRequestIdentity(id,SecureConfig(c).generation,date.toString(),action)))
        .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID,id).putExtra("generation",SecureConfig(c).generation).putExtra("date",date.toString())
    private fun click(c:Context,id:Int,date:LocalDate,action:String):PendingIntent {
        val request=intent(c,id,date,action)
        return if(action==TimelineWidgetProvider.OPEN)PendingIntent.getActivity(c,0,request.setComponent(ComponentName(c,TimelineWidgetEntryActivity::class.java)),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            else PendingIntent.getBroadcast(c,0,request,PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
    fun views(c:Context,id:Int):RemoteViews {
        val repo=PlannerRepository(c);val date=TimelineWidgetStore.date(c,id);val day=repo.cached(date)
        val now=ZonedDateTime.now(day?.let{runCatching{ZoneId.of(it.timezone)}.getOrNull()}?:TimelineWidgetStore.zone(c))
        val rows=day?.let{widgetTimelineRows(it,now)}.orEmpty()
        val completed=rows.count{it.task.done};val today=logicalToday(now)
        val generation=repo.config.generation
        val statuses=rows.mapNotNull{TimelineWidgetStore.prefs(c).getString(TimelineWidgetStore.statusKey(generation,it.task.id),null)}
        val saved=c.getSharedPreferences("day-cache",Context.MODE_PRIVATE).getString("$generation:$date",null)
            ?.let{runCatching{org.json.JSONObject(it).optLong("_saved_at")}.getOrNull()}?:0
        val status=when{
            !repo.config.configured->"Tap to connect Planner OS"
            rows.any{TimelineWidgetStore.pending(c,generation,it.task.id)}->"Saving task…"
            statuses.isNotEmpty()->statuses.first()
            day==null->"No saved day yet · tap refresh"
            saved>0->"Saved · updated ${java.time.Instant.ofEpochMilli(saved).atZone(now.zone).format(DateTimeFormatter.ofPattern("HH:mm"))} · refreshes quietly"
            else->"Saved timeline · refreshes quietly"
        }
        return RemoteViews(c.packageName,R.layout.widget_timeline).apply {
            setTextViewText(R.id.widget_date,if(date==today)"Today · ${date.format(DateTimeFormatter.ofPattern("d MMM"))}" else date.format(DateTimeFormatter.ofPattern("EEE, d MMM")))
            setTextViewText(R.id.widget_summary,"$completed/${rows.size} completed${if(day!=null&&day.tasks.any{it.time==null&&!it.done})" · ${day.tasks.count{it.time==null&&!it.done}} unscheduled" else ""}")
            setString(R.id.widget_clock,"setTimeZone",now.zone.id)
            setTextViewText(R.id.widget_status,status)
            setTextViewText(R.id.widget_empty,when{!repo.config.configured->"Connect to Planner OS\nTap to open settings";day==null->"Your saved timeline appears here.\nTap refresh to load this day.";else->"No scheduled tasks\nTap to plan this day."})
            setEmptyView(R.id.widget_tasks,R.id.widget_empty)
            setOnClickPendingIntent(R.id.widget_open,click(c,id,date,TimelineWidgetProvider.OPEN))
            setOnClickPendingIntent(R.id.widget_empty,click(c,id,date,TimelineWidgetProvider.OPEN))
            setOnClickPendingIntent(R.id.widget_refresh,click(c,id,date,TimelineWidgetProvider.REFRESH))
            setOnClickPendingIntent(R.id.widget_previous,click(c,id,date,TimelineWidgetProvider.PREVIOUS))
            setOnClickPendingIntent(R.id.widget_next,click(c,id,date,TimelineWidgetProvider.NEXT))
            setOnClickPendingIntent(R.id.widget_today,click(c,id,date,TimelineWidgetProvider.TODAY))
            val adapter=Intent(c,TimelineWidgetService::class.java).setData(Uri.parse("planneros://widget-list/$id/$generation/$date"))
                .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID,id).putExtra("generation",generation).putExtra("date",date.toString())
            setRemoteAdapter(R.id.widget_tasks,adapter)
            // A collection needs mutable fill-in extras; explicit non-exported entry activity +
            // generation/widget/date validation prevents third-party task mutations.
            setPendingIntentTemplate(R.id.widget_tasks,PendingIntent.getActivity(c,0,intent(c,id,date,TimelineWidgetProvider.ROW).setComponent(ComponentName(c,TimelineWidgetEntryActivity::class.java)),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE))
        }
    }
    fun setup(c:Context) {
        val manager=WorkManager.getInstance(c)
        if(TimelineWidgetStore.ids(c).isEmpty())return
        manager.enqueueUniquePeriodicWork("planner-timeline-widget",ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<TimelineWidgetRefreshWorker>(30,TimeUnit.MINUTES).setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build())
        renderAll(c)
    }
    fun refresh(c:Context,force:Boolean=false,onlyDate:LocalDate?=null) {
        renderAll(c)
        if(!SecureConfig(c).configured)return
        val generation=SecureConfig(c).generation
        val dates=onlyDate?.let{listOf(it)}?:TimelineWidgetStore.ids(c).map{TimelineWidgetStore.date(c,it)}.distinct()
        dates.forEach{date->WorkManager.getInstance(c).enqueueUniqueWork("planner-timeline-widget-refresh-$generation-$date",ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<TimelineWidgetRefreshWorker>().setInputData(workDataOf("generation" to generation,"force" to force,"only_date" to date.toString()))
                .addTag("planner-timeline-widget-refresh").setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build())}
    }
    private fun scheduleBoundary(c:Context) {
        val ids=TimelineWidgetStore.ids(c)
        if(ids.isEmpty())return
        val repo=PlannerRepository(c);val now=ZonedDateTime.now(TimelineWidgetStore.zone(c));val today=logicalToday(now)
        val boundaries=mutableListOf(now.toLocalDate().plusDays(1).atStartOfDay(now.zone).toInstant().toEpochMilli(),today.plusDays(1).atTime(4,0).atZone(now.zone).toInstant().toEpochMilli())
        ids.forEach{id->repo.cached(TimelineWidgetStore.date(c,id))?.let{day->
            widgetTimelineRows(day,now).filterNot{it.task.done}.forEach{row->
                val start=LocalDate.parse(day.date).atStartOfDay(now.zone).plusMinutes(row.task.clockMinutes.toLong())
                boundaries.add(start.toInstant().toEpochMilli());boundaries.add(start.plusMinutes(row.task.minutes.toLong()).toInstant().toEpochMilli())
            }
        }}
        val next=boundaries.filter{it>System.currentTimeMillis()+1000}.minOrNull()?:return
        val p=TimelineWidgetStore.prefs(c)
        if(p.getLong("boundary",0)==next)return
        p.edit().putLong("boundary",next).apply()
        WorkManager.getInstance(c).enqueueUniqueWork("planner-timeline-widget-boundary",ExistingWorkPolicy.REPLACE,
            OneTimeWorkRequestBuilder<TimelineWidgetBoundaryWorker>().setInitialDelay((next-System.currentTimeMillis()).coerceAtLeast(1000),TimeUnit.MILLISECONDS).build())
    }
}

class TimelineWidgetProvider:AppWidgetProvider() {
    companion object {
        const val PREFIX="dev.planneros.android.widget."
        const val OPEN=PREFIX+"OPEN";const val ROW=PREFIX+"ROW";const val REFRESH=PREFIX+"REFRESH"
        const val PREVIOUS=PREFIX+"PREVIOUS";const val NEXT=PREFIX+"NEXT";const val TODAY=PREFIX+"TODAY"
    }
    override fun onUpdate(c:Context,manager:AppWidgetManager,ids:IntArray){TimelineWidget.setup(c);TimelineWidget.refresh(c)}
    override fun onEnabled(c:Context){TimelineWidget.setup(c)}
    override fun onAppWidgetOptionsChanged(c:Context,manager:AppWidgetManager,id:Int,options:Bundle){TimelineWidget.renderAll(c)}
    override fun onDeleted(c:Context,ids:IntArray){ids.forEach{TimelineWidgetStore.select(c,it,null)}}
    override fun onDisabled(c:Context){val work=WorkManager.getInstance(c);listOf("planner-timeline-widget","planner-timeline-widget-boundary").forEach(work::cancelUniqueWork);work.cancelAllWorkByTag("planner-timeline-widget-refresh")}
    override fun onReceive(c:Context,intent:Intent) {
        super.onReceive(c,intent)
        if(intent.action in listOf(Intent.ACTION_DATE_CHANGED,Intent.ACTION_TIME_CHANGED,Intent.ACTION_TIMEZONE_CHANGED,Intent.ACTION_BOOT_COMPLETED)){
            TimelineWidgetStore.prefs(c).edit().remove("boundary").apply();TimelineWidget.setup(c);TimelineWidget.refresh(c);return
        }
        if(intent.action?.startsWith(PREFIX)!=true)return
        val id=intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID,-1)
        val generation=intent.getLongExtra("generation",-1)
        val date=intent.getStringExtra("date")?.let{runCatching{LocalDate.parse(it)}.getOrNull()}?:return
        if(id !in TimelineWidgetStore.ids(c)||generation!=SecureConfig(c).generation||date!=TimelineWidgetStore.date(c,id))return
        when(intent.action) {
            PREVIOUS->{TimelineWidgetStore.select(c,id,date.minusDays(1));TimelineWidget.refresh(c)}
            NEXT->{TimelineWidgetStore.select(c,id,date.plusDays(1));TimelineWidget.refresh(c)}
            TODAY->{TimelineWidgetStore.select(c,id,null);TimelineWidget.refresh(c)}
            REFRESH->{val p=TimelineWidgetStore.prefs(c);val now=System.currentTimeMillis();if(now-p.getLong("last_manual",0)>5000){p.edit().putLong("last_manual",now).apply();TimelineWidget.refresh(c,true)}}

        }
    }

}

/** Launcher interactions enter through a non-exported activity, never raw Main extras. */
class TimelineWidgetEntryActivity:Activity() {
    override fun onCreate(state:Bundle?) {
        super.onCreate(state)
        val id=intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID,-1);val generation=intent.getLongExtra("generation",-1)
        val date=intent.getStringExtra("date")?.let{runCatching{LocalDate.parse(it)}.getOrNull()}
        val task=intent.getStringExtra("task")
        if(date!=null&&id in TimelineWidgetStore.ids(this)&&generation==SecureConfig(this).generation&&date==TimelineWidgetStore.date(this,id)){
            val valid=task==null||PlannerRepository(this).cached(date)?.tasks?.any{it.id==task}==true
            if(valid&&task!=null&&intent.getStringExtra("operation")=="complete") {
                val row=PlannerRepository(this).cached(date)?.tasks?.find{it.id==task}
                if(row!=null&&row.done==intent.getBooleanExtra("expected_done",row.done)&&!TimelineWidgetStore.pending(this,generation,task)){
                    TimelineWidgetStore.prefs(this).edit().putLong("pending:$generation:$task",System.currentTimeMillis()).remove(TimelineWidgetStore.statusKey(generation,task)).apply()
                    TimelineWidget.renderAll(this)
                    WorkManager.getInstance(this).enqueueUniqueWork("planner-widget-complete-$generation-$task",ExistingWorkPolicy.KEEP,
                        OneTimeWorkRequestBuilder<TimelineWidgetCompleteWorker>().setInputData(workDataOf("widget" to id,"generation" to generation,"date" to date.toString(),"task" to task,"expected_done" to row.done)).build())
                }
            }else if(valid){val token=TimelineWidgetStore.token(this,WidgetOpenRequest(id,generation,date.toString(),task))
                startActivity(Intent(this,MainActivity::class.java).putExtra("widget_open_token",token).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))}
        }
        finish()
    }
}

class TimelineWidgetService:RemoteViewsService() {
    override fun onGetViewFactory(intent:Intent):RemoteViewsFactory=Factory(applicationContext,intent)
    private class Factory(val c:Context,val intent:Intent):RemoteViewsFactory {
        private var rows=emptyList<WidgetTimelineRow>()
        private val generation=intent.getLongExtra("generation",-1)
        private val date=intent.getStringExtra("date").orEmpty()
        override fun onCreate(){}
        override fun onDestroy(){rows=emptyList()}
        override fun onDataSetChanged(){
            rows=if(generation==SecureConfig(c).generation)runCatching{PlannerRepository(c).cached(LocalDate.parse(date))?.let{widgetTimelineRows(it,ZonedDateTime.now(ZoneId.of(it.timezone)))}}.getOrNull().orEmpty()else emptyList()
        }
        override fun getCount()=rows.size
        override fun getViewAt(position:Int):RemoteViews? {
            if(generation!=SecureConfig(c).generation)return null
            val row=rows.getOrNull(position)?:return null
            val task=row.task;val pending=TimelineWidgetStore.pending(c,generation,task.id)
            return RemoteViews(c.packageName,R.layout.widget_timeline_row).apply {
                setTextViewText(R.id.widget_start,row.start);setTextViewText(R.id.widget_end,row.end)
                if(c.resources.configuration.fontScale>1.3f){setTextViewTextSize(R.id.widget_start,android.util.TypedValue.COMPLEX_UNIT_SP,12f);setTextViewTextSize(R.id.widget_end,android.util.TypedValue.COMPLEX_UNIT_SP,10f)}
                setTextViewText(R.id.widget_title,task.title)
                setInt(R.id.widget_title,"setPaintFlags",Paint.ANTI_ALIAS_FLAG or if(task.done)Paint.STRIKE_THRU_TEXT_FLAG else 0)
                setTextColor(R.id.widget_title,Color.parseColor(if(task.done)"#766A6D" else "#292325"))
                val error=TimelineWidgetStore.prefs(c).getString(TimelineWidgetStore.statusKey(generation,task.id),null)
                setTextViewText(R.id.widget_meta,if(pending)"Saving…" else error?:"${durationLabel(task.minutes)} · ${row.state}")
                setTextColor(R.id.widget_meta,Color.parseColor(if(row.current||error!=null)"#A23B50"else "#766A6D"))
                setInt(R.id.widget_row,"setBackgroundResource",if(row.current)R.drawable.widget_current else android.R.color.transparent)
                setInt(R.id.widget_check,"setBackgroundResource",if(task.done)R.drawable.widget_check_done else R.drawable.widget_check_empty)
                setTextViewText(R.id.widget_check,if(pending)"…"else if(task.done)"✓"else "")
                setBoolean(R.id.widget_task_check,"setEnabled",!pending)
                setContentDescription(R.id.widget_task_check,if(task.done)"Mark ${task.title} incomplete"else "Complete ${task.title}")
                setContentDescription(R.id.widget_task_open,"${row.start} to ${row.end}, ${task.title}, ${row.state}. Open task")
                setOnClickFillInIntent(R.id.widget_task_open,Intent().putExtra("task",task.id).putExtra("operation","open"))
                setOnClickFillInIntent(R.id.widget_task_check,Intent().putExtra("task",task.id).putExtra("operation","complete").putExtra("expected_done",task.done))
            }
        }
        override fun getLoadingView():RemoteViews?=null
        override fun getViewTypeCount()=1
        override fun getItemId(position:Int)=rows.getOrNull(position)?.task?.id?.hashCode()?.toLong()?:position.toLong()
        override fun hasStableIds()=false
    }
}
