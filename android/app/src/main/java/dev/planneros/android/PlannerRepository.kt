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
                val starred: Boolean, val habit: Boolean, val parent: String?, val date: String?, val notes: String?, val projectId: String?) {
    val clockMinutes: Int get() = time?.split(":")?.let { it[0].toIntOrNull()?.times(60)?.plus(it.getOrNull(1)?.toIntOrNull() ?: 0) } ?: Int.MAX_VALUE
    companion object {
        fun from(j: JSONObject) = Task(j.getString("id"), j.optString("title"), j.nullString("start_time"), j.optInt("estimated_minutes",30).coerceAtLeast(1),
            j.optBoolean("done"),j.optBoolean("starred"),j.optBoolean("is_habit"),j.nullString("parent_task_id"),j.nullString("scheduled_date"),j.nullString("notes"),j.nullString("project_id"))
    }
}
fun JSONObject.nullString(key: String): String? = if (isNull(key)) null else optString(key).takeIf { it.isNotBlank() }
data class Day(val date: String, val timezone: String, val tasks: List<Task>, val cached: Boolean = false) {
    companion object { fun from(json: JSONObject, cached: Boolean = false): Day { val a=json.getJSONArray("items"); return Day(json.getString("date"),json.optString("timezone","Asia/Kolkata"),List(a.length()){Task.from(a.getJSONObject(it))},cached) } }
}

/** No secrets in source, backups, plaintext preferences, logs, or HTTP URLs. */
class SecureConfig(private val context: Context) {
    private val prefs=context.getSharedPreferences("connection",Context.MODE_PRIVATE)
    val baseUrl get()=prefs.getString("url","").orEmpty()
    val configured get()=baseUrl.isNotEmpty() && key().isNotEmpty()
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
    fun save(url: String,key: String) {
        val u=URI(url.trim().trimEnd('/'))
        require(u.scheme=="https" && !u.host.isNullOrBlank() && u.rawUserInfo==null && u.rawQuery==null && u.rawFragment==null && (u.path.isNullOrBlank() || u.path=="/")){"Use your HTTPS server origin, without /app, credentials or query parameters."}
        require(key.isNotBlank()){ "An app access key is required." }
        val cipher=Cipher.getInstance("AES/GCM/NoPadding").apply{init(Cipher.ENCRYPT_MODE,secret())}
        val encrypted=cipher.doFinal(key.trim().toByteArray(Charsets.UTF_8))
        prefs.edit().putString("url",u.toString().trimEnd('/')).putString("secret",Base64.encodeToString(cipher.iv,Base64.NO_WRAP)+":"+Base64.encodeToString(encrypted,Base64.NO_WRAP)).commit()
    }
    fun clear(){ prefs.edit().clear().commit(); context.getSharedPreferences("day-cache",Context.MODE_PRIVATE).edit().clear().commit() }
}

class PlannerRepository(private val context: Context) {
    val config=SecureConfig(context)
    private val cache=context.getSharedPreferences("day-cache",Context.MODE_PRIVATE)
    suspend fun request(method: String,path: String,body: JSONObject?=null): JSONObject = withContext(Dispatchers.IO) {
        check(config.configured){"Connect to your Planner OS server in Settings."}
        val c=URL(config.baseUrl+path).openConnection() as HttpURLConnection
        try {
            c.requestMethod=method; c.connectTimeout=15_000; c.readTimeout=20_000; c.instanceFollowRedirects=false
            c.setRequestProperty("X-App-Key",config.key()); c.setRequestProperty("Accept","application/json")
            if(body!=null){c.doOutput=true;c.setRequestProperty("Content-Type","application/json");c.outputStream.use{it.write(body.toString().toByteArray())}}
            val code=c.responseCode
            if(code !in 200..299){
                val details=c.errorStream?.bufferedReader()?.use{it.readText()}?.let{runCatching{JSONObject(it).optJSONObject("detail")?.optString("message")}.getOrNull()}
                throw IllegalStateException(if(code==401) "Access key was rejected. Update Settings." else details?.takeIf{it.isNotBlank()} ?: "Server returned $code. Changes were not saved.")
            }
            JSONObject(c.inputStream.bufferedReader().use{it.readText()})
        } finally { c.disconnect() }
    }
    fun cached(date: LocalDate): Day? = cache.getString(date.toString(),null)?.let{runCatching{Day.from(JSONObject(it),true)}.getOrNull()}
    suspend fun day(date: LocalDate): Day {
        val data=request("GET","/v2/day?date=$date").getJSONObject("data")
        cache.edit().putString(date.toString(),data.toString()).apply()
        return Day.from(data)
    }
    suspend fun patch(task: Task,body: JSONObject){request("PATCH","/v2/day/tasks/${java.net.URLEncoder.encode(task.id,"UTF-8")}",body)}
    suspend fun create(title: String,date: LocalDate?,time: String?,minutes: Int,notes: String?=null,parent: String?=null,projectId: String?=null): String {
        val b=JSONObject().put("title",title).put("estimated_minutes",minutes)
        date?.let{b.put("date",it.toString())};time?.let{b.put("start_time",it)};notes?.let{b.put("notes",it)};parent?.let{b.put("parent_task_id",it)};projectId?.let{b.put("project_id",it)}
        return request("POST","/v2/day/tasks",b).getJSONObject("data").getJSONObject("task").getString("id")
    }
    suspend fun delete(task: Task){request("DELETE","/v2/day/tasks/${java.net.URLEncoder.encode(task.id,"UTF-8")}")}
    suspend fun split(task: Task,date: LocalDate) {
        require(!task.habit && task.minutes>=2){"Habits or one-minute blocks cannot be split."}
        // Both child slots preserve the original time budget. Never shorten the original before both exist.
        val first=task.minutes/2; val leader=task.parent ?: task.id
        if(task.parent!=null){
            val added=create(task.title,date,null,task.minutes-first,task.notes,leader,task.projectId)
            try{patch(task,JSONObject().put("estimated_minutes",first))}catch(e:Exception){request("DELETE","/v2/day/tasks/$added");throw e}
        }else{
            val added=create(task.title,date,task.time,first,task.notes,leader,task.projectId)
            try{create(task.title,date,null,task.minutes-first,task.notes,leader,task.projectId)}catch(e:Exception){request("DELETE","/v2/day/tasks/$added");throw e}
        }
    }
}
