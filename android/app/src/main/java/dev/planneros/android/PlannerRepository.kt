package dev.planneros.android

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.security.KeyStore
import java.time.LocalDate
import java.util.concurrent.atomic.AtomicLong
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class Task(val id: String, val title: String, val time: String?, val minutes: Int, val done: Boolean,
                val starred: Boolean, val habit: Boolean, val parent: String?, val date: String?, val notes: String?, val projectId: String?,
                val recurrenceKey: String? = null, val parentTitle: String? = null, val partIndex: Int? = null, val partCount: Int? = null, val dueDate: String? = null,
                val workedSeconds:Int=0,val plannedSeconds:Int?=null,val milestoneId:String?=null,
                // Focus ranks starred and high-priority work first.
                val priority:String?=null) {
    val remainingSeconds:Int get()=((plannedSeconds?:minutes*60)-workedSeconds).coerceAtLeast(0)
    val clockMinutes: Int get() = time?.split(":")?.let { it[0].toIntOrNull()?.times(60)?.plus(it.getOrNull(1)?.toIntOrNull() ?: 0) } ?: Int.MAX_VALUE
    companion object {
        fun from(j: JSONObject) = Task(j.getString("id"), j.optString("title"), j.nullString("start_time"), j.optInt("estimated_minutes",30).coerceAtLeast(1),
            j.optBoolean("done"),j.optBoolean("starred"),j.optBoolean("is_habit"),j.nullString("parent_task_id"),j.nullString("scheduled_date"),j.nullString("notes"),j.nullString("project_id"),
            j.nullString("recurrence_key"), j.nullString("parent_title"), j.nullInt("part_index"), j.nullInt("part_total"), j.nullString("due_date"),j.optInt("worked_seconds"),j.nullInt("planned_seconds"),j.nullString("milestone_id"),j.nullString("priority"))
    }
}
fun JSONObject.nullString(key: String): String? = if (isNull(key)) null else optString(key).takeIf { it.isNotBlank() }
fun JSONObject.nullInt(key: String): Int? = if (!has(key) || isNull(key)) null else optInt(key)
data class Day(val date: String, val timezone: String, val tasks: List<Task>, val cached: Boolean = false, val starLimit: Int = 5, val alarmRevision: Long? = null, val connectionGeneration:Long?=null) {
    companion object { fun from(json: JSONObject, cached: Boolean = false): Day { val a=json.getJSONArray("items"); return Day(json.getString("date"),json.optString("timezone","Asia/Kolkata"),List(a.length()){Task.from(a.getJSONObject(it))},cached,json.optInt("starred_limit",5)) } }
}

/** No secrets in source, backups, plaintext preferences, logs, or HTTP URLs. */
class SecureConfig(private val context: Context) {
    companion object { private val connectionLock = Any() }
    private val prefs=context.getSharedPreferences("connection",Context.MODE_PRIVATE)
    val baseUrl get()=prefs.getString("url","").orEmpty()
    val configured get()=baseUrl.isNotEmpty() && key().isNotEmpty()
    val generation: Long get() = prefs.getLong("generation", 0L)
    fun connection(): Pair<String,String> = synchronized(connectionLock) { baseUrl to key() }
    var reminders: Boolean get()=prefs.getBoolean("reminders",false); set(value){prefs.edit().putBoolean("reminders",value).apply()}
    private fun secret(): SecretKey {
        val store=KeyStore.getInstance("AndroidKeyStore").apply{load(null)}
        (store.getKey("planner-access-key",null) as? SecretKey)?.let{return it}
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("planner-access-key",KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun key(): String { return try {
        val raw=prefs.getString("secret",null) ?: return ""
        val parts=raw.split(":")
        val cipher=Cipher.getInstance("AES/GCM/NoPadding").apply{init(Cipher.DECRYPT_MODE,secret(),GCMParameterSpec(128,Base64.decode(parts[0],Base64.NO_WRAP)))}
        String(cipher.doFinal(Base64.decode(parts[1],Base64.NO_WRAP)),Charsets.UTF_8)
    } catch(_: Exception){""} }
    fun save(url: String,key: String) = synchronized(connectionLock) {
        val u=URI(url.trim().trimEnd('/'))
        require(u.scheme=="https" && !u.host.isNullOrBlank() && u.rawUserInfo==null && u.rawQuery==null && u.rawFragment==null && (u.path.isNullOrBlank() || u.path=="/")){"Use your HTTPS server origin, without /app, credentials or query parameters."}
        require(key.isNotBlank()){ "An app access key is required." }
        val cipher=Cipher.getInstance("AES/GCM/NoPadding").apply{init(Cipher.ENCRYPT_MODE,secret())}
        val encrypted=cipher.doFinal(key.trim().toByteArray(Charsets.UTF_8))
        val origin = u.toString().trimEnd('/')
        val changed = origin != baseUrl || key.trim() != key()
        if (changed) {
            FocusWorkLogs.clearNotifications(context)
            TimerStore.reset(context)
            Reminders.reset(context)
            context.getSharedPreferences("day-cache",Context.MODE_PRIVATE).edit().clear().commit()
            context.getSharedPreferences("inbox-cache",Context.MODE_PRIVATE).edit().clear().commit()
            context.getSharedPreferences("dashboard-cache",Context.MODE_PRIVATE).edit().clear().commit()
            context.getSharedPreferences("planning-cache",Context.MODE_PRIVATE).edit().clear().commit()
        }
        check(prefs.edit().putString("url",origin).putString("secret",Base64.encodeToString(cipher.iv,Base64.NO_WRAP)+":"+Base64.encodeToString(encrypted,Base64.NO_WRAP)).putLong("generation",generation + if(changed) 1 else 0).commit()) { "Connection settings could not be saved." }
        TimelineWidget.cacheChanged(context)
    }
    fun clear() = synchronized(connectionLock) {
        FocusWorkLogs.clearNotifications(context)
        TimerStore.reset(context); Reminders.reset(context)
        val nextGeneration = generation + 1
        prefs.edit().clear().putLong("generation",nextGeneration).commit()
        context.getSharedPreferences("day-cache",Context.MODE_PRIVATE).edit().clear().commit()
        context.getSharedPreferences("inbox-cache",Context.MODE_PRIVATE).edit().clear().commit()
        context.getSharedPreferences("dashboard-cache",Context.MODE_PRIVATE).edit().clear().commit()
        context.getSharedPreferences("planning-cache",Context.MODE_PRIVATE).edit().clear().commit()
        TimelineWidget.cacheChanged(context)
    }
}

class PlannerRepository(private val context: Context) {
    companion object {
        val mutations = MutationCoordinator()
        private val cacheLock = Any()
        private val planningMutex=Mutex()
        private val mutationRevision = AtomicLong(0L)
        private val mutationStateLock=Any()
        @Volatile private var activeSnapshotWrites = 0
        val pendingSnapshots=MutableStateFlow(0)
        private val pendingCacheKeys = mutableSetOf<String>()
        private var pendingInboxGeneration:Long?=null
        private var pendingPlanningGeneration:Long?=null
    }
    val config=SecureConfig(context)
    private val cache=context.getSharedPreferences("day-cache",Context.MODE_PRIVATE)
    private val inboxCache=context.getSharedPreferences("inbox-cache",Context.MODE_PRIVATE)
    private val weekCache=context.getSharedPreferences("week-cache",Context.MODE_PRIVATE)
    private val planningCache=context.getSharedPreferences("planning-cache",Context.MODE_PRIVATE)
    private fun invalidateDays() = synchronized(cacheLock) {
        mutationRevision.incrementAndGet()
        val key="${config.generation}:planning"
        planningCache.getString(key,null)?.let{raw->runCatching{JSONObject(raw)}.getOrNull()?.let{
            planningCache.edit().putString(key,it.put("_dirty",true).toString()).apply()
        }}
        // Keep readable snapshots: quiet reconciliation replaces their contents.
    }
    private fun invalidateWorkSnapshots()=synchronized(cacheLock){
        invalidateDays()
        for(store in listOf(cache,inboxCache,planningCache)){
            val edit=store.edit()
            store.all.forEach{(key,value)->if(key.startsWith("${config.generation}:")&&value is String)runCatching{edit.putString(key,JSONObject(value).put("_dirty",true).toString())}}
            edit.commit()
        }
    }
    /** Project changed rows into every cached logical-day copy, keeping unrelated rows. */
    fun isFresh(date:LocalDate,ttlMillis:Long=10*60*1000L):Boolean {
        val data=cache.getString("${config.generation}:$date",null)?.let{runCatching{JSONObject(it)}.getOrNull()}?:return false
        return !data.optBoolean("_dirty")&&!data.optBoolean("_pending")&&System.currentTimeMillis()-data.optLong("_saved_at",0) in 0..ttlMillis
    }
    fun beginSnapshotWrite()=synchronized(mutationStateLock){mutationRevision.incrementAndGet();activeSnapshotWrites++;pendingSnapshots.value=activeSnapshotWrites}
    fun endSnapshotWrite()=synchronized(mutationStateLock){activeSnapshotWrites=(activeSnapshotWrites-1).coerceAtLeast(0);pendingSnapshots.value=activeSnapshotWrites}
    fun hasPendingSnapshots()=activeSnapshotWrites>0
    fun confirmedCached(date:LocalDate,ttlMillis:Long=10*60*1000L):Day? = synchronized(cacheLock){
        if(!isFresh(date,ttlMillis))null else cached(date)?.copy(cached=false,alarmRevision=Reminders.revision(context),connectionGeneration=config.generation)
    }
    fun confirmSnapshots()=synchronized(cacheLock){
        if(activeSnapshotWrites>0)return@synchronized
        val edit=cache.edit()
        pendingCacheKeys.filter{it.startsWith("${config.generation}:")}.forEach{key->
            val data=runCatching{JSONObject(cache.getString(key,null)!!)}.getOrNull()?:return@forEach
            if(data.optBoolean("_pending"))edit.putString(key,data.put("_pending",false).toString())
        };edit.apply();pendingCacheKeys.clear()
        if(pendingInboxGeneration==config.generation){
            val key="${config.generation}:inbox"
            inboxCache.getString(key,null)?.let{raw->runCatching{JSONObject(raw)}.getOrNull()?.let{inboxCache.edit().putString(key,it.put("_pending",false).toString()).apply()}}
        };pendingInboxGeneration=null
        if(pendingPlanningGeneration==config.generation){
            val key="${config.generation}:planning"
            planningCache.getString(key,null)?.let{raw->runCatching{JSONObject(raw)}.getOrNull()?.let{
                planningCache.edit().putString(key,it.put("_pending",false).toString()).apply()
            }}
        };pendingPlanningGeneration=null
        TimelineWidget.cacheChanged(context)
    }
    fun markPropagation(task:Task)=synchronized(cacheLock){
        val group=task.parent?:task.id;val edit=cache.edit()
        cache.all.keys.filter{it.startsWith("${config.generation}:")}.forEach{key->
            val data=runCatching{JSONObject(cache.getString(key,null)!!)}.getOrNull()?:return@forEach
            val view=runCatching{Day.from(data)}.getOrNull()?:return@forEach
            if(view.tasks.any{it.id==group||it.parent==group})edit.putString(key,data.put("_dirty",true).toString())
        };edit.apply()
        val key="${config.generation}:inbox"
        inboxCache.getString(key,null)?.let{raw->runCatching{JSONObject(raw)}.getOrNull()?.let{inboxCache.edit().putString(key,it.put("_dirty",true).toString()).apply()}}
    }
    fun saveSnapshot(before:Day,after:Day,expectedGeneration:Long=config.generation)=synchronized(cacheLock){
        if(config.generation!=expectedGeneration)return@synchronized
        mutationRevision.incrementAndGet()
        val generation=config.generation
        val views=cache.all.keys.filter{it.startsWith("$generation:")}.mapNotNull{key->
            runCatching{Day.from(JSONObject(cache.getString(key,null)!!),true)}.getOrNull()
        }.associateBy{it.date}.toMutableMap()
        val projected=DayCachePolicy.project(views,before,after)
        val edit=cache.edit()
        projected.values.forEach{view->
            val key="$generation:${view.date}"
            if(views[view.date]==view)return@forEach
            pendingCacheKeys.add(key)
            val previous=cache.getString(key,null)?.let{runCatching{JSONObject(it)}.getOrNull()}
            edit.putString(key,encodeDay(view).put("_pending",true).put("_saved_at",previous?.optLong("_saved_at",0)?:0).put("_dirty",previous?.optBoolean("_dirty")?:true).toString())
        }
        edit.apply()
        val inboxKey="$generation:inbox"
        inboxCache.getString(inboxKey,null)?.let{raw->
            val data=runCatching{JSONObject(raw)}.getOrNull()?:return@let
            val old=runCatching{Day.from(data)}.getOrNull()?:return@let
            val now=java.time.ZonedDateTime.now(java.time.ZoneId.of(old.timezone))
            val updated=applyInboxChanges(old,before,after,now)
            pendingInboxGeneration=generation
            inboxCache.edit().putString(inboxKey,encodeDay(updated).put("_saved_at",data.optLong("_saved_at",0)).put("_dirty",data.optBoolean("_dirty")).put("_pending",true).toString()).apply()
        }
        TimelineWidget.cacheChanged(context)
        val planningKey="$generation:planning"
        planningCache.getString(planningKey,null)?.let{raw->
            val data=runCatching{JSONObject(raw)}.getOrNull()?:return@let
            val old=runCatching{PlanningContext.from(data)}.getOrNull()?:return@let
            val updated=applyPlanningChanges(old,before,after)
            pendingPlanningGeneration=generation
            planningCache.edit().putString(planningKey,encodePlanning(updated).put("_saved_at",data.optLong("_saved_at",0))
                .put("_dirty",data.optBoolean("_dirty")).put("_pending",true).toString()).apply()
        }
    }
    private fun encodePlanning(view:PlanningContext)=encodeDay(Day(view.date,view.timezone,view.tasks))
        .put("projects",JSONArray(view.projects.map{JSONObject().put("id",it.id).put("name",it.name).put("status",it.status)}))
        .put("project_aliases",JSONObject(view.projectAliases))
    private fun encodeDay(day:Day)=JSONObject().put("date",day.date).put("timezone",day.timezone).put("starred_limit",day.starLimit).put("items",JSONArray(day.tasks.map{task->
        JSONObject().put("id",task.id).put("title",task.title).put("start_time",task.time?:JSONObject.NULL)
            .put("estimated_minutes",task.minutes).put("done",task.done).put("starred",task.starred).put("is_habit",task.habit)
            .put("parent_task_id",task.parent?:JSONObject.NULL).put("scheduled_date",task.date?:JSONObject.NULL).put("notes",task.notes?:JSONObject.NULL)
            .put("project_id",task.projectId?:JSONObject.NULL).put("milestone_id",task.milestoneId?:JSONObject.NULL).put("recurrence_key",task.recurrenceKey?:JSONObject.NULL)
            .put("parent_title",task.parentTitle?:JSONObject.NULL).put("part_index",task.partIndex?:JSONObject.NULL).put("part_total",task.partCount?:JSONObject.NULL).put("due_date",task.dueDate?:JSONObject.NULL).put("worked_seconds",task.workedSeconds).put("planned_seconds",task.plannedSeconds?:JSONObject.NULL)
            .put("priority",task.priority?:JSONObject.NULL)
    }))
    suspend fun request(method: String,path: String,body: JSONObject?=null,dispatcher:CoroutineDispatcher=Dispatchers.IO): JSONObject = withContext(dispatcher) {
        val connection = config.connection()
        check(connection.first.isNotEmpty() && connection.second.isNotEmpty()){ "Connect to your Planner OS server in Settings." }
        require(path.startsWith("/v2/") && !path.contains("://")) { "Invalid planner API path." }
        val generation = config.generation
        val c=URL(connection.first+path).openConnection() as HttpURLConnection
        try {
            c.requestMethod=method; c.connectTimeout=15_000; c.readTimeout=20_000; c.instanceFollowRedirects=false
            c.setRequestProperty("X-App-Key",connection.second); c.setRequestProperty("Accept","application/json")
            if(body!=null){c.doOutput=true;c.setRequestProperty("Content-Type","application/json");c.outputStream.use{it.write(body.toString().toByteArray())}}
            val code=c.responseCode
            val stream = if(code in 200..299) c.inputStream else c.errorStream
            val raw = stream?.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while(true) {
                    val count = input.read(buffer)
                    if(count < 0) break
                    check(output.size() + count <= 2 * 1024 * 1024) { "Planner response is too large." }
                    output.write(buffer,0,count)
                }
                output.toString("UTF-8")
            }.orEmpty()
            val json = runCatching { JSONObject(raw) }.getOrNull()
            val detail = json?.opt("detail")
            val message = when(detail) { is JSONObject -> detail.nullString("message"); is String -> detail; else -> json?.nullString("message") }
            check(config.generation == generation && config.connection() == connection) { "Connection changed. Refresh the current account." }
            ApiResponsePolicy.failure(code, json?.takeIf { it.has("success") }?.optBoolean("success"), message)?.let {
                throw PlannerHttpException(code,it)
            }
            if(path.startsWith("/v2/day/tasks/") && (method == "DELETE" || (method == "PATCH" && listOf("done","start_time","scheduled_date","title","estimated_minutes").any { body?.has(it) == true }))) {
                Reminders.cancelTask(context,java.net.URLDecoder.decode(path.substringAfterLast('/'),"UTF-8"))
            }
            if(method == "POST" && path == "/v2/day/tasks") Reminders.invalidateSchedule(context)
            if(method=="POST"&&path.endsWith("/work")){invalidateWorkSnapshots();Reminders.invalidateSchedule(context)}
            if(method=="POST"&&path.endsWith("/split")){invalidateWorkSnapshots();Reminders.invalidateSchedule(context)}
            if((path.startsWith("/v2/day/tasks/") && method in listOf("PATCH","DELETE")) || (path == "/v2/day/tasks" && method == "POST")) invalidateDays()
            json ?: throw IllegalStateException("Server returned an invalid planner response.")
        } finally { c.disconnect() }
    }
    fun cached(date: LocalDate): Day? = (cache.getString("${config.generation}:$date",null) ?: if(config.generation==0L)cache.getString(date.toString(),null)else null)?.let{runCatching{Day.from(JSONObject(it),true)}.getOrNull()}
    fun cachedInbox():Day?=inboxCache.getString("${config.generation}:inbox",null)?.let{runCatching{Day.from(JSONObject(it),true)}.getOrNull()}
    internal fun cachedPlanningContext():PlanningContext? {
        val generation=config.generation
        planningCache.getString("$generation:planning",null)?.let{raw->
            runCatching{PlanningContext.from(JSONObject(raw),true)}.getOrNull()?.let{return it}
        }
        // Existing installations can paint their already-saved Dashboard projects and days
        // before the first planning-context request finishes. Never mix account generations.
        val dashboard=context.getSharedPreferences("dashboard-cache",Context.MODE_PRIVATE)
        val projectData=dashboard.all.filterKeys{it.startsWith("$generation:")&&it.contains("section=projects")}.values
            .mapNotNull{raw->(raw as? String)?.let{runCatching{JSONObject(it)}.getOrNull()}}
            .maxByOrNull{it.optLong("_saved_at")}
        val rows=projectData?.optJSONArray("rows")?:return null
        val projects=(0 until rows.length()).mapNotNull{i->runCatching{rows.getJSONObject(i).let{PlanningProject(it.getString("id"),it.getString("name"),it.optString("status","active"))}}.getOrNull()}
        if(projects.isEmpty())return null
        val days=cache.all.filterKeys{it.startsWith("$generation:")}.values.mapNotNull{raw->
            (raw as? String)?.let{runCatching{Day.from(JSONObject(it),true)}.getOrNull()}}
        val tasks=(days.flatMap{it.tasks}+cachedInbox()?.tasks.orEmpty()).associateBy{it.id}.values.filter{!it.done&&it.time==null}
        return PlanningContext(LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")).toString(),"Asia/Kolkata",projects,tasks,true)
    }
    internal suspend fun planningContext(force:Boolean=false):PlanningContext=planningMutex.withLock{withContext(Dispatchers.IO){
        val generation=config.generation
        val key="$generation:planning"
        val revision=synchronized(cacheLock){
            planningCache.getString(key,null)?.let{raw->
                val data=runCatching{JSONObject(raw)}.getOrNull()
                if(!force&&data!=null&&PlanningCachePolicy.fresh(data.optLong("_saved_at"),System.currentTimeMillis(),data.optBoolean("_dirty"),data.optBoolean("_pending")))
                    return@withContext PlanningContext.from(data)
            }
            check(activeSnapshotWrites==0){"Plan changed while refreshing. Refresh task suggestions again."}
            mutationRevision.get()
        }
        val data=request("GET","/v2/day/planning-context").getJSONObject("data")
        synchronized(cacheLock){
            check(PlanningCachePolicy.acceptRefresh(generation,config.generation,revision,mutationRevision.get(),activeSnapshotWrites>0)){
                "Plan changed while refreshing. Refresh task suggestions again."
            }
            planningCache.edit().putString(key,data.put("_saved_at",System.currentTimeMillis()).toString()).apply()
        }
        PlanningContext.from(data)
    }}
    suspend fun inbox(force:Boolean=false):Day=withContext(Dispatchers.IO){
        val generation=config.generation
        val key="$generation:inbox"
        synchronized(cacheLock){
            inboxCache.getString(key,null)?.let{raw->
                val data=runCatching{JSONObject(raw)}.getOrNull()
                if(!force&&data!=null&&data.optString("date")==java.time.ZonedDateTime.now(java.time.ZoneId.of(data.optString("timezone","Asia/Kolkata"))).toLocalDate().toString()&&!data.optBoolean("_dirty")&&!data.optBoolean("_pending")&&System.currentTimeMillis()-data.optLong("_saved_at",0) in 0..10*60*1000L)
                    return@withContext Day.from(data).copy(connectionGeneration=generation)
            }
        }
        val revision=mutationRevision.get()
        val data=request("GET","/v2/day/inbox").getJSONObject("data")
        synchronized(cacheLock){
            check(config.generation==generation){"Connection changed. Refresh the current account."}
            check(revision==mutationRevision.get()&&activeSnapshotWrites==0){"Plan changed while refreshing. Refresh Inbox again."}
            inboxCache.edit().putString(key,data.put("_saved_at",System.currentTimeMillis()).toString()).apply()
        }
        Day.from(data).copy(connectionGeneration=generation)
    }
    suspend fun day(date: LocalDate): Day = withContext(Dispatchers.IO) {
        val generation = config.generation
        val alarmRevision = Reminders.revision(context)
        val cacheRevision = mutationRevision.get()
        val data=request("GET","/v2/day?date=$date").getJSONObject("data")
        check(config.generation == generation) { "Connection changed. Refresh the current account." }
        synchronized(cacheLock) {
            if(cacheRevision!=mutationRevision.get()||activeSnapshotWrites>0)throw DayRefreshSuperseded()
            cache.edit().putString("$generation:$date",data.put("_saved_at",System.currentTimeMillis()).toString()).apply()
        }
        TimelineWidget.cacheChanged(context)
        Day.from(data).copy(alarmRevision=alarmRevision,connectionGeneration=generation)
    }
    /** Neighbouring days warm independently after the selected day has painted. */
    suspend fun warmDays(center:LocalDate)=withContext(Dispatchers.IO){coroutineScope {
        val generation=config.generation
        val slots=Semaphore(2)
        listOf(-1L,1L,-2L,2L,-3L,3L).forEach{offset->launch{slots.withPermit{
            val date=center.plusDays(offset)
            if(config.generation!=generation||hasPendingSnapshots()||isFresh(date))return@withPermit
            try{day(date)}catch(cancel:CancellationException){throw cancel}catch(_:Exception){/* Keep every saved page offline. */}
        }}}
    }}
    suspend fun patch(task: Task,body: JSONObject){
        request("PATCH","/v2/day/tasks/${java.net.URLEncoder.encode(task.id,"UTF-8")}",body)
        if(task.parent!=null&&body.has("done"))markPropagation(task)
    }
    suspend fun create(title: String,date: LocalDate?,time: String?,minutes: Int,notes: String?=null,parent: String?=null,projectId: String?=null): String {
        val b=JSONObject().put("title",title).put("estimated_minutes",minutes)
        date?.let{b.put("date",it.toString())};time?.let{b.put("start_time",it)};notes?.let{b.put("notes",it)};parent?.let{b.put("parent_task_id",it)};projectId?.let{b.put("project_id",it)}
        return request("POST","/v2/day/tasks",b).getJSONObject("data").getJSONObject("task").getString("id")
    }
    suspend fun delete(task: Task){
        try { request("DELETE","/v2/day/tasks/${java.net.URLEncoder.encode(task.id,"UTF-8")}") }
        catch(error: PlannerHttpException) { if(error.statusCode != 404) throw error; Reminders.cancelTask(context,task.id); invalidateDays() }
        if(TimerStore.read(context)?.taskId == task.id) TimerStore.reset(context)
    }
    /**
     * Move tasks to one day, untimed, or drop them as skipped, in a single
     * request. The per-task PATCH cannot move a broken deadline or close a task
     * as skipped, so it cannot take an overdue task off the Focus list.
     */
    suspend fun triage(ids:List<String>,action:String,to:LocalDate?=null):JSONObject {
        val body=JSONObject().put("task_ids",JSONArray(ids)).put("action",action).put("to_date",to?.toString()?:JSONObject.NULL)
        val data=request("POST","/v2/day/tasks/triage",body).getJSONObject("data")
        invalidateDays()
        return data
    }
    /** Focus's week, read whole in one request; the last copy stays for offline. */
    suspend fun week(anchor:LocalDate):Day=withContext(Dispatchers.IO){
        val generation=config.generation
        val data=request("GET","/v2/week?date=$anchor").getJSONObject("data")
        check(config.generation==generation){"Connection changed. Refresh the current account."}
        weekCache.edit().putString("$generation:week",data.toString()).apply()
        weekFrom(data)
    }
    fun cachedWeek():Day?=weekCache.getString("${config.generation}:week",null)?.let{runCatching{weekFrom(JSONObject(it)).copy(cached=true)}.getOrNull()}
    private fun weekFrom(data:JSONObject):Day{val items=data.getJSONArray("items")
        return Day(data.getString("week_start"),data.optString("timezone","Asia/Kolkata"),List(items.length()){Task.from(items.getJSONObject(it))})}
    suspend fun split(task: Task):JSONObject {
        require(!task.habit&&!task.done&&task.remainingSeconds>=2){"Choose an unfinished task with remaining work."}
        val store=context.getSharedPreferences("split-outbox",Context.MODE_PRIVATE)
        val key="${config.generation}:${task.id}"
        // Keep the same server transaction ID after a lost response or process restart.
        val body=store.getString(key,null)?.let(::JSONObject)?:JSONObject()
            .put("request_id",java.util.UUID.randomUUID().toString())
            .put("first_seconds",(task.remainingSeconds+1)/2).put("expected_remaining",task.remainingSeconds)
        check(store.edit().putString(key,body.toString()).commit()){"Split couldn't be saved on this device."}
        try{
            val result=request("POST","/v2/day/tasks/${java.net.URLEncoder.encode(task.id,"UTF-8")}/split",body).getJSONObject("data")
            store.edit().remove(key).commit();markPropagation(task)
            return result
        }catch(e:PlannerHttpException){
            if(e.statusCode in listOf(400,404))store.edit().remove(key).commit()
            throw e
        }
    }
}
