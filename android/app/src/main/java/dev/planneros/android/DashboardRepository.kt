package dev.planneros.android

import android.content.Context
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.Executors

internal object DashboardCachePolicy {
    const val FRESH_MS=5*60*1000L
    fun fresh(saved:Long,now:Long)=now-saved in 0 until FRESH_MS
}

/** Separate workers, requests and storage. This never acquires the Day cache lock. */
internal class DashboardRepository(private val context:Context){
    companion object {
        private val network=Executors.newFixedThreadPool(2){r->Thread(r,"planner-dashboard").apply{isDaemon=true}}.asCoroutineDispatcher()
    }
    private val transport=PlannerRepository(context)
    private val cache=context.getSharedPreferences("dashboard-cache",Context.MODE_PRIVATE)
    val generation get()=transport.config.generation
    fun path(section:String,project:String?=null,offset:Int=0,row:String?=null,date:String?=null):String {
        fun encode(value:String)=URLEncoder.encode(value,"UTF-8")
        return "/v2/native/dashboard?section=${encode(section)}&offset=$offset"+
            project?.let{"&project_id=${encode(it)}"}.orEmpty()+row?.let{"&row_id=${encode(it)}"}.orEmpty()+date?.let{"&on_date=${encode(it)}"}.orEmpty()
    }
    private fun cacheKey(path:String)="$generation:${Reminders.revision(context)}:$path"
    fun cached(path:String):JSONObject?=cache.getString(cacheKey(path),null)?.let{runCatching{JSONObject(it)}.getOrNull()}
    suspend fun load(path:String,force:Boolean=false):JSONObject=withContext(network){
        val version=generation
        val revision=Reminders.revision(context)
        val key=cacheKey(path)
        val previous=cached(path)
        if(!force&&previous!=null&&DashboardCachePolicy.fresh(previous.optLong("_saved_at"),System.currentTimeMillis()))return@withContext previous
        val data=transport.request("GET",path,dispatcher=network).getJSONObject("data")
        check(generation==version){"Connection changed. Reopen Dashboard for the current account."}
        check(Reminders.revision(context)==revision){"Your plan changed while this section loaded. Refresh for the latest progress."}
        data.put("_saved_at",System.currentTimeMillis())
        val prefix="$version:$revision:"
        val edit=cache.edit()
        cache.all.keys.filterNot{it.startsWith(prefix)}.forEach{edit.remove(it)}
        edit.putString(key,data.toString()).apply()
        data
    }
}
