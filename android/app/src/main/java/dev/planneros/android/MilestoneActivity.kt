package dev.planneros.android

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowInsetsControllerCompat
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.supervisorScope
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.UUID

class MilestoneActivity:ComponentActivity(){
    companion object {
        fun intent(context:Context,row:JSONObject)=Intent(context,MilestoneActivity::class.java)
            .putExtra("milestone_id",row.optString("id",row.optString("milestone_id")))
            .putExtra("milestone_seed",row.toString())
    }
    private var resumeVersion by mutableIntStateOf(0)
    override fun onResume(){super.onResume();FocusWorkLogs.foreground++;resumeVersion++}
    override fun onPause(){FocusWorkLogs.foreground=(FocusWorkLogs.foreground-1).coerceAtLeast(0);super.onPause()}
    override fun onCreate(savedInstanceState:Bundle?){
        super.onCreate(savedInstanceState);enableEdgeToEdge()
        val id=intent.getStringExtra("milestone_id")?:run{finish();return}
        if(runCatching{UUID.fromString(id)}.isFailure){finish();return}
        val seed=runCatching{JSONObject(intent.getStringExtra("milestone_seed")?:"{}").put("id",id)}.getOrDefault(JSONObject().put("id",id))
        setContent{
            val mode=getSharedPreferences("appearance",MODE_PRIVATE).getString("theme","system")
            val dark=mode=="dark"||mode!="light"&&isSystemInDarkTheme()
            SideEffect{WindowInsetsControllerCompat(window,window.decorView).apply{isAppearanceLightStatusBars=!dark;isAppearanceLightNavigationBars=!dark}}
            MaterialTheme(colorScheme=plannerColorScheme(dark)){MilestoneScreen(id,seed,resumeVersion){finish()}}
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun MilestoneScreen(id:String,seed:JSONObject,resumeVersion:Int,exit:()->Unit){
    val c=LocalContext.current;val repository=remember{PlannerRepository(c)};val dashboard=remember{DashboardRepository(c)}
    val scope=rememberCoroutineScope();val snackbar=remember{SnackbarHostState()};val generation=remember(id){repository.config.generation}
    val detailPath=remember(id){dashboard.path("milestones",row=id)}
    val tasksPath=remember(id){dashboard.path("tasks",milestone=id,includeParts=true)}
    fun compatibleTasks(data:JSONObject)=data.optString("milestone_id")==id&&data.optBoolean("includes_parts")
    var milestone by remember(id){mutableStateOf(dashboard.cached(detailPath)?.optJSONObject("record")?.takeIf{it.has("health_status")}?:seed)}
    var rows by remember(id){mutableStateOf(dashboard.cached(tasksPath)?.takeIf(::compatibleTasks)?.dashboardObjects("rows").orEmpty())}
    var rowsComplete by remember(id){mutableStateOf(dashboard.cached(tasksPath)?.takeIf(::compatibleTasks)?.let{!it.has("next_offset")||it.isNull("next_offset")}==true)}
    var needsReconcile by remember{mutableStateOf(false)}
    var planning by remember{mutableStateOf(repository.cachedPlanningContext())}
    var loading by remember{mutableStateOf(false)};var error by remember{mutableStateOf<String?>(null)}
    var filter by rememberSaveable{mutableStateOf("All")};var query by rememberSaveable{mutableStateOf("")}
    var editor by remember{mutableStateOf<Task?>(null)};var adding by remember{mutableStateOf(false)}
    var draft by remember{mutableStateOf<EditorValues?>(null)}
    var deleteTarget by remember{mutableStateOf<Task?>(null)};var splitTarget by remember{mutableStateOf<Task?>(null)}
    var editMilestone by remember{mutableStateOf(false)};var milestoneBusy by remember{mutableStateOf(false)}
    var replacement by remember{mutableStateOf<Task?>(null)}
    val pending=remember{mutableStateListOf<String>()};val mutations=PlannerRepository.mutations
    var serial by remember{mutableIntStateOf(0)};var refreshJob by remember{mutableStateOf<Job?>(null)}
    val zone=milestone.nullString("timezone")?:"Asia/Kolkata"
    val today=logicalToday(ZonedDateTime.now(ZoneId.of(zone)))
    fun decode(row:JSONObject)=Task.from(JSONObject(row.toString()).put("done",row.optString("status")=="done"||row.optBoolean("done")).put("is_habit",false))
    val tasks=rows.map(::decode)
    fun storeRows(){if(rowsComplete)dashboard.store(tasksPath,JSONObject().put("rows",JSONArray(rows)).put("next_offset",JSONObject.NULL).put("milestone_id",id).put("includes_parts",true).put("timezone",zone),generation)}
    fun updateMilestoneCounts(){
        val roots=rows.filter{it.nullString("parent_task_id")==null&&it.optString("status")!="skipped"}
        val next=JSONObject(milestone.toString())
        if(rowsComplete){
            next.put("total_tasks",roots.size).put("done_tasks",roots.count{it.optString("status")=="done"||it.optBoolean("done")})
            val span=milestoneTaskSpan(rows.map(::decode))
            next.put("tracking_start_date",span.first?:JSONObject.NULL).put("tracking_last_date",span.second?:JSONObject.NULL)
        }
        milestone=recalculateMilestoneHealth(next,LocalDate.now(ZoneId.of(zone)))
        dashboard.store(detailPath,JSONObject().put("record",milestone),generation)
        val listPath=dashboard.path("milestones")
        dashboard.cached(listPath)?.let{cached->
            val updated=cached.dashboardObjects("rows").map{if(it.optString("id")==id)milestone else it}
            dashboard.replaceRows(listPath,JSONArray(updated),generation)
        }
    }
    fun refresh(force:Boolean=false){
        if(generation!=repository.config.generation){exit();return}
        if(pending.isNotEmpty())return
        val ticket=++serial;refreshJob?.cancel()
        dashboard.cached(detailPath)?.optJSONObject("record")?.takeIf{it.has("health_status")}?.let{milestone=it}
        dashboard.cached(tasksPath)?.takeIf(::compatibleTasks)?.let{cached->
            val complete=!cached.has("next_offset")||cached.isNull("next_offset")
            if(complete||!rowsComplete){rows=cached.dashboardObjects("rows");rowsComplete=complete}
        }
        loading=true;error=null
        refreshJob=scope.launch refreshTasks@{
            try{supervisorScope{
                val revision=Reminders.revision(c)
                val details=launch{
                    try{val detail=dashboard.load(detailPath,force)
                        if(ticket==serial&&generation==repository.config.generation){
                            val record=detail.getJSONObject("record")
                            check(record.has("health_status")){"Milestone details need the latest server update. Refresh after deployment."}
                            milestone=record
                        }
                    }catch(cancel:CancellationException){throw cancel}catch(e:Exception){if(ticket==serial)error=e.message}
                }
                val all=mutableListOf<JSONObject>();var offset=0
                do{
                    val page=dashboard.load(dashboard.path("tasks",offset=offset,milestone=id,includeParts=true),force)
                    if(ticket!=serial||generation!=repository.config.generation||pending.isNotEmpty())return@supervisorScope
                    check(compatibleTasks(page)){"Milestone details need the latest server update. Refresh after deployment."}
                    all.addAll(page.dashboardObjects("rows"))
                    if(rows.isEmpty())rows=all.toList()
                    offset=if(page.has("next_offset")&&!page.isNull("next_offset"))page.getInt("next_offset")else -1
                }while(offset>=0)
                check(Reminders.revision(c)==revision){"Your plan changed while refreshing. Saved tasks are still available."}
                check(generation==repository.config.generation){"Connection changed. Reopen the milestone."}
                rows=all.distinctBy{it.optString("id")};rowsComplete=true;storeRows();details.join()
            }}catch(cancel:CancellationException){throw cancel}catch(e:Exception){if(ticket==serial)error=e.message?:"Couldn't refresh. Saved tasks are still available."}
            finally{if(ticket==serial)loading=false}
        }
    }
    fun refreshDetail(){
        val ticket=serial
        scope.launch{try{
            if(generation!=repository.config.generation)return@launch
            val detail=dashboard.load(detailPath,true)
            if(generation!=repository.config.generation||ticket!=serial)return@launch
            val record=detail.getJSONObject("record")
            check(record.has("health_status")){"Milestone details need the latest server update. Refresh after deployment."}
            milestone=record
        }catch(cancel:CancellationException){throw cancel}catch(e:Exception){if(generation==repository.config.generation)error=e.message}}
    }
    fun message(text:String){scope.launch{snackbar.showSnackbar(text)}}
    fun closeEditor(){editor=null;adding=false;draft=null}
    fun mutate(task:Task,body:JSONObject?=null,remove:Boolean=false,split:Boolean=false,onFailure:()->Unit={}){
        if(generation!=repository.config.generation){exit();return}
        if(!rowsComplete)return
        val keys=mutationKeys(task)
        if(!mutations.begin(keys))return
        serial++;refreshJob?.cancel();loading=false;pending.add(task.id)
        val old=rows.firstOrNull{it.optString("id")==task.id}?.let{JSONObject(it.toString())}
        val before=Day(today.toString(),zone,listOf(task));var after=before
        if(remove||split){rows=rows.filterNot{it.optString("id")==task.id};after=before.copy(tasks=emptyList())}
        else if(body!=null){
            val changed=JSONObject(old?.toString()?:"{}");body.keys().forEach{changed.put(it,body.get(it))}
            if(body.has("done"))changed.put("status",if(body.getBoolean("done"))"done"else"todo")
            rows=rows.map{if(it.optString("id")==task.id)changed else it};after=before.copy(tasks=listOf(decode(changed)))
        }
        repository.beginSnapshotWrite();repository.saveSnapshot(before,after)
        scope.launch{
            var reconcile=split||remove||task.parent!=null
            var serverConfirmed=false
            try{
                if(split){repository.split(task);serverConfirmed=true}
                else if(remove){repository.delete(task);serverConfirmed=true}
                else{
                    val result=repository.request("PATCH","/v2/day/tasks/${task.id}",body).getJSONObject("data").getJSONObject("task")
                    serverConfirmed=true
                    check(generation==repository.config.generation){"Connection changed. Reopen the milestone."}
                    val updated=JSONObject(old?.toString()?:"{}");result.keys().forEach{updated.put(it,result.get(it))}
                    updated.put("done",updated.optString("status")=="done").put("is_habit",false)
                    if(generation==repository.config.generation)rows=rows.map{if(it.optString("id")==task.id)updated else it}.filter{it.nullString("milestone_id")==id}
                    val corrected=before.copy(tasks=listOf(decode(updated)))
                    repository.saveSnapshot(after,corrected);after=corrected
                    if(body?.has("done")==true&&(task.parent!=null||rows.any{it.nullString("parent_task_id")==task.id})){repository.markPropagation(task);reconcile=true}
                }
                if(generation==repository.config.generation){
                    dashboard.invalidate();storeRows();updateMilestoneCounts()
                    AutoFocusScheduler.syncChanges(c,after.tasks,before.date,zone)
                    TimerStore.read(c)?.takeIf{it.taskId==task.id}?.let{if(remove)TimerStore.reset(c)else after.tasks.firstOrNull()?.let{updated->TimerStore.refresh(c,updated)}}
                    message(if(split)"Remaining work split into sessions"else if(remove)"Task deleted"else "Saved")
                }
            }catch(cancel:CancellationException){
                if(generation==repository.config.generation){
                    if(!serverConfirmed){rows=rows.filterNot{it.optString("id")==task.id}+listOfNotNull(old);repository.saveSnapshot(after,before)}
                    else{needsReconcile=true;dashboard.invalidate()}
                };throw cancel
            }catch(e:Exception){
                if(generation==repository.config.generation){
                    if(!serverConfirmed){rows=rows.filterNot{it.optString("id")==task.id}+listOfNotNull(old);repository.saveSnapshot(after,before);onFailure()}
                    else{dashboard.invalidate();needsReconcile=true}
                    error=if(serverConfirmed)"Saved on server; refreshing local progress. ${e.message.orEmpty()}"else e.message?:"Couldn't save; restored the task."
                };if(!serverConfirmed)reconcile=false
            }
            finally{
                pending.remove(task.id);mutations.end(keys);repository.endSnapshotWrite()
                if(!repository.hasPendingSnapshots()&&generation==repository.config.generation)repository.confirmSnapshots()
                if(serverConfirmed&&reconcile)needsReconcile=true
                if(needsReconcile&&pending.isEmpty()&&generation==repository.config.generation){needsReconcile=false;refresh(true)}
            }
        }
    }
    fun startTimer(task:Task){if(generation!=repository.config.generation){exit();return};val active=TimerStore.read(c);if(active!=null&&active.taskId!=task.id)replacement=task else TimerStore.start(c,task)}
    LaunchedEffect(resumeVersion){if(generation!=repository.config.generation){exit();return@LaunchedEffect};refresh();planning=repository.cachedPlanningContext()}
    BackHandler(enabled=editor!=null||adding){closeEditor()}
    val visible=milestoneVisibleTasks(tasks,filter,query)
    Scaffold(containerColor=MaterialTheme.colorScheme.background,snackbarHost={SnackbarHost(snackbar)},topBar={
        TopAppBar(title={Text("Milestone",fontSize=20.sp)},navigationIcon={IconButton(onClick=exit){Icon(Icons.AutoMirrored.Rounded.ArrowBack,"Back to milestones")}},actions={
            IconButton(onClick={editMilestone=true},enabled=!milestoneBusy){Icon(Icons.Rounded.Edit,"Edit milestone details")}
            IconButton(onClick={refresh(true)},enabled=!loading&&pending.isEmpty()){Icon(Icons.Rounded.Refresh,"Refresh milestone")}
        })
    },floatingActionButton={if(rowsComplete)ExtendedFloatingActionButton(onClick={draft=null;adding=true},icon={Icon(Icons.Rounded.Add,null)},text={Text("Add task")})}){padding->
        LazyColumn(Modifier.fillMaxSize().padding(padding),contentPadding=PaddingValues(start=20.dp,end=20.dp,bottom=100.dp)){
            item("summary"){
                Column(Modifier.fillMaxWidth().padding(bottom=16.dp)){
                    Text(milestone.optString("project_name",""),fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(rowTitle(milestone),fontSize=27.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.padding(top=4.dp,bottom=12.dp))
                    Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(10.dp)){
                        val status=milestoneHealthStatus(milestone);val color=milestoneHealthColor(status)
                        MilestoneHealthChip(status)
                        if(milestone.optString("status") in listOf("not_started","in_progress","blocked","done"))Text(humanStatus(milestone.optString("status")),fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    MilestoneProgress(milestone,Modifier.fillMaxWidth().padding(top=10.dp))
                    val health=milestone.optJSONObject("health")
                    Text("${friendlyDate(milestone.nullString("tracking_start_date")).ifBlank{"No dated tasks"}} → ${friendlyDate(milestone.nullString("target_date")?:health?.nullString("target_date")).ifBlank{"No deadline"}}",fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=8.dp))
                    milestone.nullString("notes")?.let{Text(it,fontSize=15.sp,lineHeight=22.sp,modifier=Modifier.padding(top=12.dp))}
                    TextButton(enabled=!milestoneBusy,onClick={
                        if(generation!=repository.config.generation){exit();return@TextButton}
                        milestoneBusy=true;serial++;refreshJob?.cancel();loading=false
                        scope.launch{try{
                            val body=JSONObject().put("status",if(recordDone(milestone))"in_progress"else"done")
                            val saved=repository.request("PATCH","/v2/native/milestones/$id",body).getJSONObject("data").getJSONObject("milestone")
                            if(generation!=repository.config.generation)return@launch
                            saved.keys().forEach{milestone.put(it,saved.get(it))};milestone=JSONObject(milestone.toString())
                            dashboard.invalidate();Reminders.invalidateSchedule(c);updateMilestoneCounts()
                        }catch(e:Exception){if(generation==repository.config.generation){error=e.message;refreshDetail()}}finally{milestoneBusy=false}}
                    }){Icon(if(recordDone(milestone))Icons.Rounded.Undo else Icons.Rounded.CheckCircleOutline,null,modifier=Modifier.size(18.dp));Text(if(recordDone(milestone))" Reopen milestone"else" Mark milestone complete")}
                    Text("Linked tasks keep their own completion status.",fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if(loading)item("loading"){LinearProgressIndicator(Modifier.fillMaxWidth().height(2.dp))}
            error?.let{warning->item("error"){Column(Modifier.padding(vertical=12.dp)){Text(warning,color=MaterialTheme.colorScheme.error,fontSize=13.sp);TextButton(onClick={refresh(true)}){Text("Retry refresh")}}}}
            item("tasks_header"){
                Text("Tasks · ${tasks.size}",fontSize=20.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.padding(top=12.dp))
                Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){listOf("All","Open","Done").forEach{label->FilterChip(selected=filter==label,onClick={filter=label},label={Text(label)})}}
                if(tasks.size>6||query.isNotBlank())OutlinedTextField(query,{query=it},singleLine=true,label={Text("Find a task")},leadingIcon={Icon(Icons.Rounded.Search,null)},modifier=Modifier.fillMaxWidth().padding(bottom=12.dp),shape=RoundedCornerShape(12.dp))
            }
            if(visible.isEmpty())item("empty"){Text(if(loading&&tasks.isEmpty())"Loading tasks…"else if(tasks.isEmpty())"No tasks linked yet. Add your first task."else "No tasks match this view.",color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(vertical=24.dp))}
            items(visible,key={it.id}){task->
                val raw=rows.firstOrNull{it.optString("id")==task.id}
                Row(Modifier.fillMaxWidth().padding(vertical=4.dp),verticalAlignment=Alignment.Top){
                    Checkbox(checked=task.done,onCheckedChange={mutate(task,JSONObject().put("done",it))},enabled=rowsComplete&&task.id !in pending)
                    Column(Modifier.weight(1f).clickable(enabled=rowsComplete&&task.id !in pending){draft=null;editor=task}.padding(vertical=10.dp)){
                        Text(task.title,fontSize=16.sp,fontWeight=FontWeight.Medium,textDecoration=if(task.done)TextDecoration.LineThrough else null,color=if(task.done)MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface)
                        val meta=listOfNotNull(task.date?.let(::friendlyDate)?:"Unscheduled",task.time?.take(5),durationLabel(task.minutes),raw?.nullString("priority")?.takeIf{it!="medium"}?.let(::humanStatus),if(task.parent!=null)"Session"else null,if(raw?.optString("status")=="skipped")"Skipped"else null)
                        Text(meta.joinToString(" · "),fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=4.dp))
                        task.dueDate?.let{Text("Due ${friendlyDate(it)}",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)}
                        task.notes?.let{Text(it,fontSize=13.sp,maxLines=2,overflow=TextOverflow.Ellipsis,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=4.dp))}
                    }
                    IconButton(enabled=rowsComplete&&task.id !in pending,onClick={editor=task}){Icon(Icons.Rounded.ChevronRight,"Edit ${task.title}",tint=MaterialTheme.colorScheme.onSurfaceVariant)}
                }
                HorizontalDivider(color=MaterialTheme.colorScheme.outlineVariant.copy(alpha=.5f))
            }
        }
    }
    if(adding||editor!=null){
        val original=editor
        val project=milestone.nullString("project_id")
        val projects=if(original==null)listOfNotNull(project?.let{PlanningProject(it,milestone.optString("project_name","Project"))})else planning?.projects?.let{pickerProjects(it)}?.takeIf{it.isNotEmpty()}?:listOfNotNull(project?.let{PlanningProject(it,milestone.optString("project_name","Project"))})
        PlannerEditor(original,today,null,null,original?.id in pending,draft,projects,planning?.projectAliases.orEmpty(),emptyList(),project,{},::closeEditor,
            {title,date,time,minutes,notes,projectId,explicit->
                val values=EditorValues(title,date,time,minutes,notes,projectId,explicit)
                if(original!=null){
                    val body=JSONObject().put("title",title).put("scheduled_date",date.toString()).put("start_time",time?:JSONObject.NULL).put("estimated_minutes",minutes).put("notes",notes?:JSONObject.NULL)
                    if(shouldPatchPlanningProject(original.projectId,projectId,explicit))body.put("project_id",projectId?:JSONObject.NULL)
                    closeEditor();mutate(original,body,onFailure={draft=values;editor=original})
                }else{
                    if(generation!=repository.config.generation){exit();return@PlannerEditor}
                    adding=false;serial++;refreshJob?.cancel();loading=false
                    scope.launch{var addedOnServer=false;try{
                        val body=JSONObject().put("title",title).put("date",date.toString()).put("start_time",time?:JSONObject.NULL).put("estimated_minutes",minutes).put("notes",notes?:JSONObject.NULL).put("project_id",project?:JSONObject.NULL).put("milestone_id",id)
                        val task=repository.request("POST","/v2/day/tasks",body).getJSONObject("data").getJSONObject("task")
                        addedOnServer=true
                        if(generation==repository.config.generation){rows=rows+task;dashboard.invalidate();storeRows();updateMilestoneCounts();AutoFocusScheduler.syncChanges(c,listOf(decode(task)),today.toString(),zone);message("Task added to milestone")}
                    }catch(e:Exception){if(generation==repository.config.generation){
                        if(addedOnServer){dashboard.invalidate();error="Task added; refreshing local progress.";refresh(true)}
                        else{draft=values;adding=true;error=e.message}
                    }}}
                }
            },{mutate(it,JSONObject().put("starred",!it.starred))},{splitTarget=it},{deleteTarget=it},{closeEditor();startTimer(it)},{closeEditor();if(generation==repository.config.generation)FocusWorkLogs.open(c,it.id)else exit()})
    }
    deleteTarget?.let{task->AlertDialog(onDismissRequest={deleteTarget=null},title={Text("Delete this task?")},text={Text(task.title)},confirmButton={TextButton(onClick={deleteTarget=null;closeEditor();mutate(task,remove=true)}){Text("Delete")}},dismissButton={TextButton(onClick={deleteTarget=null}){Text("Cancel")}})}
    splitTarget?.let{task->AlertDialog(onDismissRequest={splitTarget=null},title={Text("Split remaining work?")},text={Text("Two sessions will share the remaining ${workDuration(task.remainingSeconds)}. Your saved work stays recorded.")},confirmButton={TextButton(onClick={splitTarget=null;closeEditor();mutate(task,split=true)}){Text("Split")}},dismissButton={TextButton(onClick={splitTarget=null}){Text("Cancel")}})}
    replacement?.let{task->AlertDialog(onDismissRequest={replacement=null},title={Text("Switch focus?")},text={Text("End the current timer and start ${task.title}? Task completion stays unchanged.")},confirmButton={TextButton(onClick={replacement=null;if(generation==repository.config.generation)TimerStore.start(c,task)else exit()}){Text("Start timer")}},dismissButton={TextButton(onClick={replacement=null}){Text("Keep current")}})}
    if(editMilestone)MilestoneEditor(milestone,milestoneBusy,{editMilestone=false}){body->
        if(generation!=repository.config.generation){exit();return@MilestoneEditor}
        milestoneBusy=true;serial++;refreshJob?.cancel();loading=false
        scope.launch{try{
            val saved=repository.request("PATCH","/v2/native/milestones/$id",body).getJSONObject("data").getJSONObject("milestone")
            if(generation!=repository.config.generation)return@launch
            saved.keys().forEach{milestone.put(it,saved.get(it))};milestone=JSONObject(milestone.toString());editMilestone=false
            dashboard.invalidate();Reminders.invalidateSchedule(c);updateMilestoneCounts();refreshDetail()
        }catch(e:Exception){if(generation==repository.config.generation){error=e.message;refreshDetail()}}finally{milestoneBusy=false}}
    }
}

@Composable private fun MilestoneEditor(row:JSONObject,busy:Boolean,dismiss:()->Unit,save:(JSONObject)->Unit){
    var name by rememberSaveable{mutableStateOf(row.optString("name"))}
    var target by rememberSaveable{mutableStateOf(row.nullString("target_date").orEmpty())};var notes by rememberSaveable{mutableStateOf(row.nullString("notes").orEmpty())}
    var error by remember{mutableStateOf<String?>(null)}
    AlertDialog(onDismissRequest={if(!busy)dismiss()},title={Text("Milestone details")},text={Column(Modifier.verticalScroll(rememberScrollState())){
        OutlinedTextField(name,{name=it},label={Text("Name")},modifier=Modifier.fillMaxWidth())
        Text("Starts with first task · "+friendlyDate(row.nullString("tracking_start_date")).ifBlank{"Not dated yet"},fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=10.dp))
        OutlinedTextField(target,{target=it},label={Text("Deadline · YYYY-MM-DD")},modifier=Modifier.fillMaxWidth().padding(top=8.dp),singleLine=true)
        OutlinedTextField(notes,{notes=it},label={Text("Notes")},modifier=Modifier.fillMaxWidth().padding(top=8.dp))
        error?.let{Text(it,color=MaterialTheme.colorScheme.error)}
    }},confirmButton={TextButton(enabled=!busy,onClick={
        if(name.isBlank()||name.length>300||target.isNotBlank()&&runCatching{LocalDate.parse(target)}.isFailure)error="Use a name and valid dates, or leave dates blank."
        else save(JSONObject().put("name",name.trim()).put("target_date",target.takeIf{it.isNotBlank()}?:JSONObject.NULL).put("notes",notes.takeIf{it.isNotBlank()}?:JSONObject.NULL))
    }){Text(if(busy)"Saving…"else "Save")}},dismissButton={TextButton(enabled=!busy,onClick=dismiss){Text("Cancel")}})
}
