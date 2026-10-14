package dev.planneros.android

import android.content.Context
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

internal object DashboardCachePolicy {
    const val FRESH_MS=5*60*1000L
    fun fresh(saved:Long,now:Long)=now-saved in 0 until FRESH_MS
    fun fresh(saved:Long,now:Long,savedRevision:Long,currentRevision:Long,dirty:Boolean=false)=
        !dirty && savedRevision==currentRevision && fresh(saved,now)
    fun key(generation:Long,path:String)="$generation:$path"
    /** Only this connection's old revision keys may migrate into its stable key. */
    fun legacyRevision(key:String,generation:Long,path:String):Long? {
        val prefix="$generation:"
        val suffix=":$path"
        if(!key.startsWith(prefix)||!key.endsWith(suffix))return null
        return key.removePrefix(prefix).removeSuffix(suffix).toLongOrNull()
    }
    fun legacyKeys(keys:Collection<String>,generation:Long,path:String)=keys.mapNotNull{key->
        legacyRevision(key,generation,path)?.let{revision->key to revision}
    }.sortedByDescending{it.second}
    fun path(section:String,project:String?=null,offset:Int=0,row:String?=null,date:String?=null,milestone:String?=null,includeParts:Boolean=false):String {
        fun encode(value:String)=URLEncoder.encode(value,"UTF-8")
        return "/v2/native/dashboard?section=${encode(section)}&offset=$offset"+
            project?.let{"&project_id=${encode(it)}"}.orEmpty()+
            row?.let{"&row_id=${encode(it)}"}.orEmpty()+
            date?.let{"&on_date=${encode(it)}"}.orEmpty()+
            milestone?.let{"&milestone_id=${encode(it)}"}.orEmpty()+
            if(includeParts)"&include_parts=true" else ""
    }
}

/** Separate workers, requests and storage. This never acquires the Day cache lock. */
internal class DashboardRepository(private val context:Context){
    companion object {
        private val network=Executors.newFixedThreadPool(2){r->Thread(r,"planner-dashboard").apply{isDaemon=true}}.asCoroutineDispatcher()
        private val requests=ConcurrentHashMap<String,Mutex>()
        private val published=ConcurrentHashMap<String,Long>()
        private val cacheLock=Any()
    }
    private val transport=PlannerRepository(context)
    private val cache=context.getSharedPreferences("dashboard-cache",Context.MODE_PRIVATE)
    val generation get()=transport.config.generation
    fun path(section:String,project:String?=null,offset:Int=0,row:String?=null,date:String?=null,milestone:String?=null,includeParts:Boolean=false):String =
        DashboardCachePolicy.path(section,project,offset,row,date,milestone,includeParts)

    /** A task mutation makes this stale, never invisible. No network or Day lock. */
    fun cached(path:String):JSONObject?=synchronized(cacheLock){
        val version=generation
        val key=DashboardCachePolicy.key(version,path)
        var previous=cache.getString(key,null)?.let{runCatching{JSONObject(it)}.getOrNull()}
        if(previous==null){
            val legacy=DashboardCachePolicy.legacyKeys(cache.all.keys,version,path).firstNotNullOfOrNull{(oldKey,revision)->
                cache.getString(oldKey,null)?.let{raw->runCatching{JSONObject(raw).put("_revision",revision)}.getOrNull()}
            }
            if(legacy!=null && generation==version){cache.edit().putString(key,legacy.toString()).apply();previous=legacy}
        }
        if(generation==version)previous else null
    }

    /** Persist a complete page, including merged pagination, in this connection only. */
    fun store(path:String,data:JSONObject,expectedGeneration:Long=generation,expectedRevision:Long=Reminders.revision(context)):JSONObject=synchronized(cacheLock){
        check(generation==expectedGeneration){"Connection changed. Reopen Dashboard for the current account."}
        check(Reminders.revision(context)==expectedRevision){"Your plan changed while this section loaded. Refresh for the latest progress."}
        val copy=JSONObject(data.toString()).put("_saved_at",System.currentTimeMillis()).put("_revision",expectedRevision).put("_dirty",false)
        val key=DashboardCachePolicy.key(expectedGeneration,path)
        cache.edit().putString(key,copy.toString()).apply()
        published.merge(key,1L){old,increment->old+increment}
        check(generation==expectedGeneration){"Connection changed. Reopen Dashboard for the current account."}
        copy
    }

    fun replaceRows(path:String,rows:JSONArray,expectedGeneration:Long=generation,expectedRevision:Long=Reminders.revision(context)):JSONObject {
        check(generation==expectedGeneration){"Connection changed. Reopen Dashboard for the current account."}
        val data=cached(path)?:JSONObject()
        return store(path,data.put("rows",JSONArray(rows.toString())),expectedGeneration,expectedRevision)
    }
    fun saveRows(path:String,rows:JSONArray,expectedGeneration:Long=generation,expectedRevision:Long=Reminders.revision(context)):JSONObject=
        replaceRows(path,rows,expectedGeneration,expectedRevision)

    /** Keep every readable page while ensuring the next load refreshes it quietly. */
    fun invalidate()=synchronized(cacheLock){
        val version=generation
        val edit=cache.edit()
        cache.all.forEach{(key,value)->
            if(key.startsWith("$version:")&&value is String)runCatching{edit.putString(key,JSONObject(value).put("_dirty",true).toString())}
        }
        if(generation==version)edit.apply()
    }

    suspend fun load(path:String,force:Boolean=false):JSONObject {
        val version=generation
        val key=DashboardCachePolicy.key(version,path)
        val observed=published[key]?:0L
        return withContext(network){
            requests.computeIfAbsent(key){Mutex()}.withLock{
                check(generation==version){"Connection changed. Reopen Dashboard for the current account."}
                val revision=Reminders.revision(context)
                val previous=cached(path)
                val refreshedWhileWaiting=(published[key]?:0L)!=observed
                if((!force||refreshedWhileWaiting)&&previous!=null&&DashboardCachePolicy.fresh(
                    previous.optLong("_saved_at"),System.currentTimeMillis(),previous.optLong("_revision",-1L),revision,previous.optBoolean("_dirty")
                ))return@withLock previous
                val data=transport.request("GET",path,dispatcher=network).getJSONObject("data")
                store(path,data,version,revision)
            }
        }
    }
}
