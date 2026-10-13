package dev.planneros.android

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.time.LocalDate

class TimelineWidgetRefreshWorker(c:Context,p:WorkerParameters):CoroutineWorker(c,p) {
    override suspend fun doWork():Result {
        val c=applicationContext;val repo=PlannerRepository(c)
        val generation=inputData.getLong("generation",repo.config.generation)
        if(generation!=repo.config.generation||!repo.config.configured)return Result.success()
        TimelineWidget.renderAll(c)
        try{withTimeout(60_000){
            val dates=inputData.getString("only_date")?.let{listOf(LocalDate.parse(it))}?:TimelineWidgetStore.ids(c).map{TimelineWidgetStore.date(c,it)}.distinct()
            dates.forEach{date->
                if(generation!=repo.config.generation||repo.hasPendingSnapshots())return@withTimeout
                if(date !in TimelineWidgetStore.ids(c).map{TimelineWidgetStore.date(c,it)})return@forEach
                if(inputData.getBoolean("force",false)||!repo.isFresh(date))repo.day(date)
            }
        }}catch(_:TimeoutCancellationException){ /* Keep the saved day on a slow connection. */ }catch(cancel:CancellationException){throw cancel}catch(_:Exception){
            // Saved rows stay visible; connectivity does not gate the launcher.
        }
        TimelineWidget.renderAll(c)
        return Result.success()
    }
}
class TimelineWidgetBoundaryWorker(c:Context,p:WorkerParameters):CoroutineWorker(c,p) {
    override suspend fun doWork():Result {
        TimelineWidgetStore.prefs(applicationContext).edit().remove("boundary").apply()
        TimelineWidget.renderAll(applicationContext)
        // Date rollover may need a new day, but task boundaries only repaint cache.
        if(TimelineWidgetStore.ids(applicationContext).any{PlannerRepository(applicationContext).cached(TimelineWidgetStore.date(applicationContext,it))==null})TimelineWidget.refresh(applicationContext)
        return Result.success()
    }
}

class TimelineWidgetCompleteWorker(c:Context,p:WorkerParameters):CoroutineWorker(c,p) {
    override suspend fun doWork():Result {
        val c=applicationContext;val repo=PlannerRepository(c)
        val generation=inputData.getLong("generation",-1)
        val taskId=inputData.getString("task")?:return Result.success()
        val date=inputData.getString("date")?.let{runCatching{LocalDate.parse(it)}.getOrNull()}?:return Result.success()
        val expectedDone=inputData.getBoolean("expected_done",false)
        val store=TimelineWidgetStore.prefs(c);val statusKey=TimelineWidgetStore.statusKey(generation,taskId)
        val pendingKey="pending:$generation:$taskId"
        val outboxKey="write:$generation:$taskId"
        var before:Day?=null;var after:Day?=null;var keys=emptySet<String>();var acquired=false;var snapshot=false;var reconcile=false;var saved=false
        try {
            if(generation!=repo.config.generation||inputData.getInt("widget",-1) !in TimelineWidgetStore.ids(c))return Result.success()
            val view=repo.cached(date)?:return Result.success()
            val task=view.tasks.find{it.id==taskId}?:return Result.success()
            val recovering=store.getString(outboxKey,null)?.let{runCatching{JSONObject(it)}.getOrNull()}
            val resuming=recovering?.optBoolean("expected_done")==expectedDone
            if(!resuming&&!widgetCanApply(generation,repo.config.generation,expectedDone,task,PlannerRepository.mutations.pending(taskId)))return Result.success()
            keys=mutationKeys(task);acquired=PlannerRepository.mutations.begin(keys)
            if(!acquired){store.edit().putString(statusKey,"Task is being edited · tap to retry").apply();return Result.success()}
            // Re-read after acquiring the same task/group lock used by the app.
            // Another foreground write may have finished between the first read and lock.
            val lockedView=repo.cached(date)?:return Result.success()
            val lockedTask=lockedView.tasks.find{it.id==taskId}?:return Result.success()
            if(mutationKeys(lockedTask)!=keys||(!resuming&&lockedTask.done!=expectedDone))return Result.success()
            // A durable, idempotent desired-state PATCH is safe after a lost response.
            // An app restart repeats the same completion value instead of flipping twice.
            before=if(resuming)lockedView.copy(tasks=lockedView.tasks.map{if(it.id==taskId)it.copy(done=expectedDone)else it})else lockedView
            after=replaceTask(before,lockedTask.copy(done=!expectedDone))
            store.edit().putString(outboxKey,JSONObject().put("expected_done",expectedDone).toString()).commit()
            repo.beginSnapshotWrite();snapshot=true
            repo.saveSnapshot(before,after)
            TimelineWidget.renderAll(c)
            withTimeout(45_000){repo.patch(lockedTask,JSONObject().put("done",!expectedDone))}
            if(generation==repo.config.generation){
                saved=true;reconcile=lockedTask.parent!=null
                store.edit().remove(outboxKey).remove(statusKey).apply()
                AutoFocusScheduler.syncChanges(c,after.tasks.filter{it.id==taskId},after.date,after.timezone)
            }
        }catch(_:TimeoutCancellationException){
            if(generation==repo.config.generation){
                if(before!=null&&after!=null)repo.saveSnapshot(after,before)
                store.edit().putString(statusKey,"Connection timed out · tap checkbox to retry").apply()
            }
        }catch(cancel:CancellationException){
            // Retain the outbox for an interrupted/lost response; retry is desired-state safe.
            if(generation==repo.config.generation&&before!=null&&after!=null)repo.saveSnapshot(after,before)
            throw cancel
        }catch(error:Exception){
            if(generation==repo.config.generation){
                if(before!=null&&after!=null)repo.saveSnapshot(after,before)
                if(error is PlannerHttpException)store.edit().remove(outboxKey).apply()
                store.edit().putString(statusKey,if(error is PlannerHttpException&&error.statusCode in listOf(401,403))"Reconnect in app to save" else "Couldn't save · tap checkbox to retry").apply()
            }
        }finally{
            if(snapshot)repo.endSnapshotWrite()
            if(acquired)PlannerRepository.mutations.end(keys)
            if(!repo.hasPendingSnapshots()&&generation==repo.config.generation)repo.confirmSnapshots()
            store.edit().remove(pendingKey).apply()
            TimelineWidget.renderAll(c)
        }
        if(generation==repo.config.generation&&saved){
            if(reconcile)TimelineWidget.refresh(c,true,date)
            else repo.confirmedCached(date)?.let{fresh->
                val now=java.time.ZonedDateTime.now(java.time.ZoneId.of(fresh.timezone))
                if(date==logicalToday(now))Reminders.schedule(c,fresh)
            }
        }
        return Result.success()
    }
}
