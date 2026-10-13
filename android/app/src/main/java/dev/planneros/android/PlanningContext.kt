package dev.planneros.android

import org.json.JSONObject
import java.util.Locale

internal data class PlanningProject(val id:String,val name:String,val status:String="active")
internal data class PlanningContext(val date:String,val timezone:String,val projects:List<PlanningProject>,val tasks:List<Task>,val cached:Boolean=false,val projectAliases:Map<String,String> = emptyMap()){
    companion object {
        fun from(data:JSONObject,cached:Boolean=false):PlanningContext {
            val projects=data.getJSONArray("projects")
            val tasks=data.getJSONArray("items")
            val aliases=data.optJSONObject("project_aliases")?.let{json->json.keys().asSequence().mapNotNull{key->json.nullString(key)?.let{key to it}}.toMap()}.orEmpty()
            return PlanningContext(data.getString("date"),data.optString("timezone","Asia/Kolkata"),
                List(projects.length()){i->projects.getJSONObject(i).let{PlanningProject(it.getString("id"),it.getString("name"),it.optString("status","active"))}},
                List(tasks.length()){Task.from(tasks.getJSONObject(it))},cached,aliases)
        }
    }
}

internal object PlanningCachePolicy {
    const val FRESH_MS=10*60*1000L
    const val VISIBLE_SUGGESTIONS=6
    fun fresh(savedAt:Long,now:Long,dirty:Boolean,pending:Boolean)=!dirty&&!pending&&now-savedAt in 0 until FRESH_MS
    fun acceptRefresh(startGeneration:Long,currentGeneration:Long,startRevision:Long,currentRevision:Long,pendingWrites:Boolean)=
        startGeneration==currentGeneration&&startRevision==currentRevision&&!pendingWrites
}

/** Once consolidated, the two everyday projects are the only picker choices. */
@Suppress("UNUSED_PARAMETER")
internal fun pickerProjects(projects:List<PlanningProject>,existingProjectId:String?=null):List<PlanningProject> {
    fun name(project:PlanningProject)=project.name.trim().lowercase(Locale.ROOT)
    val germany=projects.firstOrNull{name(it)=="germany"}
    val life=projects.firstOrNull{name(it)=="life other than germany"}
    val primary=listOfNotNull(germany,life)
    // A stale Dashboard snapshot can still contain emptied source projects. Keep
    // their task assignments in drafts, but never offer them as new destinations.
    return primary
}

/** Resolve historical project ids without touching task ids, notes or milestone links. */
internal fun resolvePlanningProject(id:String?,aliases:Map<String,String>):String? {
    var resolved=id?:return null
    val seen=mutableSetOf<String>()
    while(seen.add(resolved)){
        val next=aliases[resolved]?:return resolved
        if(next==resolved)return resolved
        resolved=next
    }
    return id // A malformed cycle never changes an existing assignment.
}
internal fun canonicalPlanningTask(task:Task,aliases:Map<String,String>,knownProjectId:String?=null):Task {
    val project=resolvePlanningProject(task.projectId,aliases)?:knownProjectId
    return if(project==task.projectId)task else task.copy(projectId=project)
}
/** An untouched unknown legacy id must never undo server-side consolidation. */
internal fun shouldPatchPlanningProject(original:String?,selected:String?,explicit:Boolean)=explicit||(selected!=null&&selected!=original)

/** Current snapshots override the picker cache, including completed/scheduled removals. */
internal fun planningRows(context:PlanningContext?,day:Day?,backlog:Day?):List<Task> {
    val rows=(context?.tasks?:backlog?.tasks.orEmpty()).associateBy{it.id}.toMutableMap()
    // Once all-project context exists, absence is authoritative: an older Inbox must
    // not reintroduce a task that has since been scheduled or completed elsewhere.
    day?.tasks.orEmpty().forEach{task->rows[task.id]=canonicalPlanningTask(task,context?.projectAliases.orEmpty(),rows[task.id]?.projectId)}
    return rows.values.filter{!it.done&&it.time==null&&!it.id.startsWith("pending:")}.map{canonicalPlanningTask(it,context?.projectAliases.orEmpty())}
}

/** Local title lookup: never asks the server for a keystroke. */
internal fun taskSuggestions(rows:List<Task>,projectId:String?,query:String):List<Task> {
    val words=query.trim().lowercase(Locale.ROOT).split(Regex("\\s+")).filter{it.isNotBlank()}
    if(projectId==null||words.isEmpty())return emptyList()
    return rows.filter{task->task.projectId==projectId&&!task.done&&task.time==null&&!task.id.startsWith("pending:")&&
        words.all{task.title.lowercase(Locale.ROOT).contains(it)}}
        .distinctBy{it.id}
        .sortedWith(compareByDescending<Task>{it.title.trim().lowercase(Locale.ROOT).startsWith(query.trim().lowercase(Locale.ROOT))}
            .thenByDescending{it.starred}.thenBy{it.title.lowercase(Locale.ROOT)}.thenBy{it.id})
}

/** Update only the changed task ids, retaining future-dated unscheduled tasks. */
internal fun applyPlanningChanges(context:PlanningContext,before:Day,after:Day):PlanningContext {
    val changed=changedTaskIds(before,after)
    return context.copy(tasks=context.tasks.filterNot{it.id in changed}+after.tasks.filter{it.id in changed&&!it.done&&it.time==null}.map{canonicalPlanningTask(it,context.projectAliases)})
}
