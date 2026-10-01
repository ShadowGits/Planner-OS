package dev.planneros.android

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.security.KeyStore
import java.time.LocalDate
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class Task(val id: String, val title: String, val time: String?, val minutes: Int, val done: Boolean,
                val starred: Boolean, val habit: Boolean, val parent: String?, val date: String?, val notes: String?, val projectId: String?,
                val recurrenceKey: String? = null, val parentTitle: String? = null, val partIndex: Int? = null, val partCount: Int? = null, val dueDate: String? = null) {
    val clockMinutes: Int get() = time?.split(":")?.let { it[0].toIntOrNull()?.times(60)?.plus(it.getOrNull(1)?.toIntOrNull() ?: 0) } ?: Int.MAX_VALUE
    companion object {
        fun from(j: JSONObject) = Task(j.getString("id"), j.optString("title"), j.nullString("start_time"), j.optInt("estimated_minutes",30).coerceAtLeast(1),
            j.optBoolean("done"),j.optBoolean("starred"),j.optBoolean("is_habit"),j.nullString("parent_task_id"),j.nullString("scheduled_date"),j.nullString("notes"),j.nullString("project_id"),
            j.nullString("recurrence_key"), j.nullString("parent_title"), j.nullInt("part_index"), j.nullInt("part_total"), j.nullString("due_date"))
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
            TimerStore.reset(context)
            Reminders.reset(context)
            context.getSharedPreferences("day-cache",Context.MODE_PRIVATE).edit().clear().commit()
            context.getSharedPreferences("inbox-cache",Context.MODE_PRIVATE).edit().clear().commit()
        }
        check(prefs.edit().putString("url",origin).putString("secret",Base64.encodeToString(cipher.iv,Base64.NO_WRAP)+":"+Base64.encodeToString(encrypted,Base64.NO_WRAP)).putLong("generation",generation + if(changed) 1 else 0).commit()) { "Connection settings could not be saved." }
    }
    fun clear() = synchronized(connectionLock) {
        TimerStore.reset(context); Reminders.reset(context)
        val nextGeneration = generation + 1
        prefs.edit().clear().putLong("generation",nextGeneration).commit()
        context.getSharedPreferences("day-cache",Context.MODE_PRIVATE).edit().clear().commit()
        context.getSharedPreferences("inbox-cache",Context.MODE_PRIVATE).edit().clear().commit()
    }
}

class PlannerRepository(private val context: Context) {
    companion object {
        private val cacheLock = Any()
        private var mutationRevision = 0L
        private var activeSnapshotWrites = 0
        private val pendingCacheKeys = mutableSetOf<String>()
        private var pendingInboxGeneration:Long?=null
    }
    val config=SecureConfig(context)
    private val cache=context.getSharedPreferences("day-cache",Context.MODE_PRIVATE)
    private val inboxCache=context.getSharedPreferences("inbox-cache",Context.MODE_PRIVATE)
    private fun invalidateDays() = synchronized(cacheLock) {
        mutationRevision++
        // Keep readable snapshots: quiet reconciliation replaces their contents.
    }
    /** Project changed rows into every cached logical-day copy, keeping unrelated rows. */
    fun isFresh(date:LocalDate,ttlMillis:Long=10*60*1000L):Boolean {
        val data=cache.getString("${config.generation}:$date",null)?.let{runCatching{JSONObject(it)}.getOrNull()}?:return false
        return !data.optBoolean("_dirty")&&!data.optBoolean("_pending")&&System.currentTimeMillis()-data.optLong("_saved_at",0) in 0..ttlMillis
    }
    fun beginSnapshotWrite()=synchronized(cacheLock){activeSnapshotWrites++}
    fun endSnapshotWrite()=synchronized(cacheLock){activeSnapshotWrites=(activeSnapshotWrites-1).coerceAtLeast(0)}
    fun hasPendingSnapshots()=synchronized(cacheLock){activeSnapshotWrites>0}
    fun confirmedCached(date:LocalDate,ttlMillis:Long=10*60*1000L):Day? = synchronized(cacheLock){
        if(!isFresh(date,ttlMillis))null else cached(date)?.copy(cached=false,alarmRevision=Reminders.revision(context),connectionGeneration=config.generation)
    }
    fun confirmSnapshots()=synchronized(cacheLock){
        val edit=cache.edit()
        pendingCacheKeys.filter{it.startsWith("${config.generation}:")}.forEach{key->
            val data=runCatching{JSONObject(cache.getString(key,null)!!)}.getOrNull()?:return@forEach
            if(data.optBoolean("_pending"))edit.putString(key,data.put("_pending",false).toString())
        };edit.apply();pendingCacheKeys.clear()
        if(pendingInboxGeneration==config.generation){
            val key="${config.generation}:inbox"
            inboxCache.getString(key,null)?.let{raw->runCatching{JSONObject(raw)}.getOrNull()?.let{inboxCache.edit().putString(key,it.put("_pending",false).toString()).apply()}}
        };pendingInboxGeneration=null
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
    fun saveSnapshot(before:Day,after:Day)=synchronized(cacheLock){
        mutationRevision++
        val generation=config.generation
        val views=cache.all.keys.filter{it.startsWith("$generation:")}.mapNotNull{key->
            runCatching{Day.from(JSONObject(cache.getString(key,null)!!),true)}.getOrNull()
        }.associateBy{it.date}.toMutableMap()
        views.putIfAbsent(before.date,before)
        val edit=cache.edit()
        views.values.forEach{view->
            val key="$generation:${view.date}"
            pendingCacheKeys.add(key)
            val previous=cache.getString(key,null)?.let{runCatching{JSONObject(it)}.getOrNull()}
            edit.putString(key,encodeDay(projectChanges(view,before,after)).put("_pending",true).put("_saved_at",previous?.optLong("_saved_at",0)?:0).put("_dirty",previous?.optBoolean("_dirty")?:false).toString())
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
    }
    private fun encodeDay(day:Day)=JSONObject().put("date",day.date).put("timezone",day.timezone).put("starred_limit",day.starLimit).put("items",JSONArray(day.tasks.map{task->
        JSONObject().put("id",task.id).put("title",task.title).put("start_time",task.time?:JSONObject.NULL)
            .put("estimated_minutes",task.minutes).put("done",task.done).put("starred",task.starred).put("is_habit",task.habit)
            .put("parent_task_id",task.parent?:JSONObject.NULL).put("scheduled_date",task.date?:JSONObject.NULL).put("notes",task.notes?:JSONObject.NULL)
            .put("project_id",task.projectId?:JSONObject.NULL).put("recurrence_key",task.recurrenceKey?:JSONObject.NULL)
            .put("parent_title",task.parentTitle?:JSONObject.NULL).put("part_index",task.partIndex?:JSONObject.NULL).put("part_total",task.partCount?:JSONObject.NULL).put("due_date",task.dueDate?:JSONObject.NULL)
    }))
    suspend fun request(method: String,path: String,body: JSONObject?=null): JSONObject = withContext(Dispatchers.IO) {
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
            if((path.startsWith("/v2/day/tasks/") && method in listOf("PATCH","DELETE")) || (path == "/v2/day/tasks" && method == "POST")) invalidateDays()
            json ?: throw IllegalStateException("Server returned an invalid planner response.")
        } finally { c.disconnect() }
    }
    fun cached(date: LocalDate): Day? = (cache.getString("${config.generation}:$date",null) ?: if(config.generation==0L)cache.getString(date.toString(),null)else null)?.let{runCatching{Day.from(JSONObject(it),true)}.getOrNull()}
    fun cachedInbox():Day?=inboxCache.getString("${config.generation}:inbox",null)?.let{runCatching{Day.from(JSONObject(it),true)}.getOrNull()}
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
        val revision=synchronized(cacheLock){mutationRevision}
        val data=request("GET","/v2/day/inbox").getJSONObject("data")
        synchronized(cacheLock){
            check(config.generation==generation){"Connection changed. Refresh the current account."}
            check(revision==mutationRevision){"Plan changed while refreshing. Refresh Inbox again."}
            inboxCache.edit().putString(key,data.put("_saved_at",System.currentTimeMillis()).toString()).apply()
        }
        Day.from(data).copy(connectionGeneration=generation)
    }
    suspend fun day(date: LocalDate): Day = withContext(Dispatchers.IO) {
        val generation = config.generation
        val alarmRevision = Reminders.revision(context)
        val cacheRevision = synchronized(cacheLock) { mutationRevision }
        val data=request("GET","/v2/day?date=$date").getJSONObject("data")
        check(config.generation == generation) { "Connection changed. Refresh the current account." }
        synchronized(cacheLock) {
            check(cacheRevision == mutationRevision) { "Plan changed while refreshing. Refresh this day again." }
            cache.edit().putString("$generation:$date",data.put("_saved_at",System.currentTimeMillis()).toString()).apply()
        }
        Day.from(data).copy(alarmRevision=alarmRevision,connectionGeneration=generation)
    }
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
    suspend fun split(task: Task,date: LocalDate) {
        markPropagation(task)
        require(!task.habit && task.minutes>=2){"Habits or one-minute blocks cannot be split."}
        // Both child slots preserve the original time budget. Never shorten the original before both exist.
        val first=(task.minutes+1)/2; val leader=task.parent ?: task.id
        val slot = task.time?.let { normalizeSlot(if(task.clockMinutes<1440)task.date?.let(LocalDate::parse)?:date else date, task.clockMinutes) }
        val actualDate = slot?.date ?: task.date?.let(LocalDate::parse) ?: date
        if(task.parent!=null){
            val added=create(task.title,actualDate,null,task.minutes-first,task.notes,leader,task.projectId)
            try{patch(task,JSONObject().put("estimated_minutes",first))}catch(e:Exception){compensateSplit(added,e)}
        }else{
            val added=create(task.title,actualDate,slot?.clock,first,task.notes,leader,task.projectId)
            try{create(task.title,actualDate,null,task.minutes-first,task.notes,leader,task.projectId)}catch(e:Exception){compensateSplit(added,e)}
        }
    }
    private suspend fun compensateSplit(added: String, original: Exception): Nothing {
        try { request("DELETE","/v2/day/tasks/${java.net.URLEncoder.encode(added,"UTF-8")}") }
        catch(cleanup: Exception) {
            throw java.io.IOException("Split could not be confirmed or rolled back. Refresh the day before retrying.",original).apply { addSuppressed(cleanup) }
        }
        throw java.io.IOException("Split could not be confirmed. Refresh the day before retrying.",original)
    }
}
