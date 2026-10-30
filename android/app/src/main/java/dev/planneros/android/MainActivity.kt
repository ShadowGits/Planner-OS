package dev.planneros.android

import android.Manifest
import android.app.DatePickerDialog
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.*
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ViewList
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.NonCancellable
import org.json.JSONObject
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.UUID

class MainActivity:ComponentActivity(){
    private var finishId by mutableStateOf<String?>(null)
    private var widgetOpen by mutableStateOf<WidgetOpenRequest?>(null)
    private val permission=registerForActivityResult(ActivityResultContracts.RequestPermission()){Reminders.setup(this)}
    override fun onCreate(savedInstanceState:Bundle?){
        super.onCreate(savedInstanceState);enableEdgeToEdge();FocusWorkLogs.restoreNotifications(this);finishId=intent.getStringExtra("finish_timer");widgetOpen=TimelineWidgetStore.consume(this,intent.getStringExtra("widget_open_token"))
        TimelineWidget.setup(this)
        setContent{
            val prefs=remember{getSharedPreferences("appearance",MODE_PRIVATE)}
            var appearance by remember{mutableStateOf(prefs.getString("theme","system")?:"system")}
            val dark=when(appearance){"dark"->true;"light"->false;else->isSystemInDarkTheme()}
            SideEffect{
                WindowInsetsControllerCompat(window,window.decorView).apply{
                    isAppearanceLightStatusBars=!dark;isAppearanceLightNavigationBars=!dark
                }
            }
            val colors=plannerColorScheme(dark)
            MaterialTheme(colorScheme=colors){PlannerScreen(finishId,{finishId=null},{if(Build.VERSION.SDK_INT>=33)permission.launch(Manifest.permission.POST_NOTIFICATIONS)},dark,appearance,{appearance=it;prefs.edit().putString("theme",it).apply()},widgetOpen,{widgetOpen=null})}
        }
        Reminders.setup(this)
        if(TimerStore.read(this)!=null)TimerStore.action(this,"SHOW")
    }
    override fun onNewIntent(intent:Intent){super.onNewIntent(intent);setIntent(intent);finishId=intent.getStringExtra("finish_timer");widgetOpen=TimelineWidgetStore.consume(this,intent.getStringExtra("widget_open_token"))}
    override fun onResume(){super.onResume();FocusWorkLogs.foreground++}
    override fun onPause(){FocusWorkLogs.foreground=(FocusWorkLogs.foreground-1).coerceAtLeast(0);super.onPause()}
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlannerScreen(finishId:String?,finishHandled:()->Unit,requestNotification:()->Unit,dark:Boolean,appearance:String,onAppearance:(String)->Unit,widgetOpen:WidgetOpenRequest?=null,widgetHandled:()->Unit={}){
    val lifecycle=LocalLifecycleOwner.current
    val context=LocalContext.current;val repo=remember{PlannerRepository(context.applicationContext)}
    val scope=rememberCoroutineScope();val snackbar=remember{SnackbarHostState()};val density=LocalDensity.current.density
    val compactNavigation=LocalConfiguration.current.screenWidthDp<360&&LocalDensity.current.fontScale>1.25f
    var selectedIso by rememberSaveable{mutableStateOf(logicalToday(ZonedDateTime.now(ZoneId.of("Asia/Kolkata"))).toString())}
    val selected=LocalDate.parse(selectedIso)
    var day by remember{mutableStateOf<Day?>(repo.cached(selected))}
    val dayPages=remember{mutableMapOf<String,Day>().apply{day?.let{put(it.date,it)}}}
    val pendingSnapshotCount by PlannerRepository.pendingSnapshots.collectAsState()
    val updateFailures by TaskUpdateAlerts.failures.collectAsState()
    var showUpdateFailures by remember{mutableStateOf(false)}
    var backlog by remember{mutableStateOf(repo.cachedInbox())}
    var planning by remember{mutableStateOf(repo.cachedPlanningContext())}
    var inboxProjectId by rememberSaveable{mutableStateOf<String?>(null)}
    var inboxLoading by remember{mutableStateOf(false)}
    val mutations=remember{PlannerRepository.mutations}
    val pendingWrites=remember{mutableStateListOf<Pair<Day,Day>>()}
    val drafts=remember{mutableStateMapOf<String,EditorValues>()}
    var reconcileJob by remember{mutableStateOf<Job?>(null)}
    var loading by remember{mutableStateOf(false)};var error by remember{mutableStateOf<String?>(null)}
    var requestSerial by remember{mutableIntStateOf(0)};var connectionRevision by remember{mutableIntStateOf(0)}
    var settings by remember{mutableStateOf(!repo.config.configured)}
    var editorId by rememberSaveable{mutableStateOf<String?>(null)};var editorBackup by remember{mutableStateOf<Task?>(null)}
    var recovery by remember{mutableStateOf<EditorValues?>(null)}
    var adding by rememberSaveable{mutableStateOf(false)};var suggestedDate by rememberSaveable{mutableStateOf<String?>(null)};var suggestedTime by rememberSaveable{mutableStateOf<String?>(null)}
    var inbox by rememberSaveable{mutableStateOf(false)};var timer by remember{mutableStateOf(TimerStore.read(context))};var remaining by remember{mutableLongStateOf(0L)}
    val viewPrefs=remember{context.getSharedPreferences("appearance",android.content.Context.MODE_PRIVATE)}
    var todoView by rememberSaveable{mutableStateOf(viewPrefs.getBoolean("day_todo",false))}
    var showMilestones by rememberSaveable{mutableStateOf(false)}
    // The app opens on Focus: what needs you, ranked, before the timeline.
    var focus by rememberSaveable{mutableStateOf(true)}
    var week by remember{mutableStateOf(repo.cachedWeek())}
    var menu by remember{mutableStateOf(false)}
    val dashRepo=remember{DashboardRepository(context)}
    var milestonesList by remember{mutableStateOf(dashRepo.cached(dashRepo.path("milestones"))?.dashboardObjects("rows").orEmpty())}
    var milestonesLoading by remember{mutableStateOf(false)}
    var milestonesError by remember{mutableStateOf<String?>(null)}
    var milestonesRequestSerial by remember{mutableIntStateOf(0)}
    var inboxFilter by rememberSaveable{mutableStateOf("Open")}
    var replacement by remember{mutableStateOf<Task?>(null)};var deleteTarget by remember{mutableStateOf<Task?>(null)}
    var splitTarget by remember{mutableStateOf<Task?>(null)}
    val scroll=rememberScrollState();val inboxScroll=androidx.compose.foundation.lazy.rememberLazyListState()
    val todoScroll=androidx.compose.foundation.lazy.rememberLazyListState()
    var drag by remember{mutableStateOf<DragState?>(null)};var viewportTop by remember{mutableFloatStateOf(0f)};var viewportBottom by remember{mutableFloatStateOf(0f)}
    var clock by remember{mutableStateOf(ZonedDateTime.now(ZoneId.of(day?.timezone?:"Asia/Kolkata")))}
    val today=logicalToday(clock);val nowMinute=logicalNowMinute(clock)
    var lastToday by rememberSaveable{mutableStateOf(today.toString())}
    val currentTasks=day?.takeIf{it.date==selectedIso}?.tasks.orEmpty()
    val timed=currentTasks.filter{it.time!=null}.sortedBy{it.clockMinutes}
    val openTasks=remember(currentTasks){currentTasks.filterNot{it.done}.sortedBy{it.clockMinutes}}
    val completedTasks=remember(currentTasks){currentTasks.filter{it.done}.sortedBy{it.clockMinutes}}
    val todoTasks=remember(openTasks,completedTasks){openTasks+completedTasks}
    val unscheduled=inboxRows(day?.takeIf{it.date==selectedIso},backlog,clock)
    val unfinishedInbox=unscheduled.count{!it.done}
    val focusMilestones=remember(milestonesList){milestonesList.mapNotNull{row->row.nullString("id")?.let{FocusMilestone(it,row.optString("name"),row.nullString("target_date"))}}.associateBy{it.id}}
    val focusProjectNames=remember(planning){planning?.projects.orEmpty().associate{it.id to it.name}}
    val focusOverdue=rankOverdue(unscheduled,focusMilestones,clock)
    val focusTodayTasks=focusToday(dayPages[today.toString()]?:day?.takeIf{it.date==today.toString()},unscheduled,clock)
    val onDay=!focus&&!inbox&&!showMilestones
    val projectAliases=planning?.projectAliases.orEmpty()
    val planningAssignments=remember(planning){planning?.tasks.orEmpty().associate{it.id to it.projectId}}
    val resolvedInboxProjectId=resolvePlanningProject(inboxProjectId,projectAliases)
    val filteredInbox=unscheduled.map{canonicalPlanningTask(it,projectAliases,planningAssignments[it.id])}.filter{resolvedInboxProjectId==null||it.projectId==resolvedInboxProjectId}
    val projectDayTasks=currentTasks.map{canonicalPlanningTask(it,projectAliases,planningAssignments[it.id])}.filter{resolvedInboxProjectId==null||it.projectId==resolvedInboxProjectId}
    val planningProjects=planning?.projects.orEmpty()
    val suggestionRows=remember(planning,day,selectedIso,backlog){planningRows(planning,day?.takeIf{it.date==selectedIso},backlog)}
    val editor=editorId?.let{id->currentTasks.find{it.id==id}?:editorBackup?.takeIf{it.id==id}}?.let{canonicalPlanningTask(it,projectAliases,planningAssignments[it.id])}
    fun closeEditor(){adding=false;editorId=null;editorBackup=null;suggestedDate=null;suggestedTime=null;recovery=null}
    fun paintDay(value:Day?){
        if(value!=null)dayPages[value.date]=value
        if(value==null||value.date==selectedIso)day=value
    }
    fun selectDate(iso:String){
        val saved=dayPages[iso]?:DayCachePolicy.saved(iso,repo.cached(LocalDate.parse(iso)),pendingWrites.toList())
        selectedIso=iso;requestSerial++;drag=null;error=null
        paintDay(saved);loading=saved==null
    }
    fun projectLocal(before:Day,after:Day){
        day?.let{dayPages[it.date]=it}
        val views=dayPages.toMutableMap()
        DayCachePolicy.project(emptyMap(),before,after).keys.filterNot{it in views}.forEach{iso->
            repo.cached(LocalDate.parse(iso))?.let{views[iso]=it}
        }
        val projected=DayCachePolicy.project(views,before,after)
        dayPages.clear();dayPages.putAll(projected);day=dayPages[selectedIso]
        backlog=backlog?.let{applyInboxChanges(it,before,after,clock)}
        planning=planning?.let{applyPlanningChanges(it,before,after)}
    }
    fun taskBusy(task:Task)=mutationKeys(task).any{mutations.pending(it)}
    fun openEditor(task:Task){if(taskBusy(task)||task.id.startsWith("pending:"))return;drag=null;requestSerial++;loading=false;recovery=drafts.remove(task.id);adding=false;editorId=task.id;editorBackup=task;suggestedDate=null;suggestedTime=null}
    suspend fun refresh(preserve:Boolean=true,quiet:Boolean=true,force:Boolean=false){
        if(drag!=null||editorId!=null||adding)return
        if(!repo.config.configured){settings=true;return}
        val date=LocalDate.parse(selectedIso);val serial=++requestSerial;val generation=repo.config.generation
        if(!preserve||day?.date!=date.toString())paintDay(dayPages[date.toString()]?:DayCachePolicy.saved(date.toString(),repo.cached(date),pendingWrites.toList()))
        if(repo.hasPendingSnapshots()){loading=false;return}
        if(!force&&day!=null&&repo.isFresh(date)){
            repo.confirmedCached(date)?.let{AutoFocusScheduler.sync(context,it)}
            AutoFocusScheduler.catchUp(context);loading=false;return
        }
        loading=day==null
        if(!quiet)error=null
        try{
            val fresh=repo.day(date)
            if(selectedIso==date.toString()&&serial==requestSerial&&generation==repo.config.generation&&drag==null&&editorId==null&&!adding){
                paintDay(pendingWrites.fold(fresh){view,(before,after)->projectChanges(view,before,after)})
                clock=ZonedDateTime.now(ZoneId.of(fresh.timezone));error=null
                withContext(Dispatchers.IO){
                    if(date==logicalToday(ZonedDateTime.now(ZoneId.of(fresh.timezone))))Reminders.schedule(context,fresh)
                    AutoFocusScheduler.sync(context,fresh)
                    AutoFocusScheduler.catchUp(context)
                    TimerStore.read(context)?.let{active->fresh.tasks.find{it.id==active.taskId}?.let{TimerStore.refresh(context,it)}}
                }
            }
        }catch(cancel:CancellationException){throw cancel}catch(e:Exception){
            if(selectedIso==date.toString()&&serial==requestSerial&&generation==repo.config.generation){
                if(e is DayRefreshSuperseded){
                    scope.launch{while(repo.hasPendingSnapshots())delay(100);refresh(true,true,true)}
                }
                else if(e is PlannerHttpException&&e.statusCode in listOf(401,403)){settings=true;error=e.message}
                else if(e !is DayRefreshSuperseded&&(!quiet||day==null))
                    error=if(e is PlannerHttpException)e.message else if(e is java.io.IOException)if(day==null)"This day hasn’t been saved here yet. Reconnect to load it."else"Your saved day is here. Reconnect to refresh and save changes." else e.message?:"Couldn't refresh this day."
            }
        }finally{if(serial==requestSerial)loading=false}
    }
    suspend fun refreshInbox(force:Boolean=false){
        if(!repo.config.configured)return
        val generation=repo.config.generation
        inboxLoading=backlog==null
        try{
            val fresh=repo.inbox(force)
            if(generation==repo.config.generation)backlog=pendingWrites.fold(fresh){view,(before,after)->applyInboxChanges(view,before,after,clock)}
        }catch(cancel:CancellationException){throw cancel}catch(e:Exception){
            if(generation==repo.config.generation&&e.message!="Plan changed while refreshing. Refresh Inbox again."){
                error=if(backlog==null)e.message?:"Couldn't load Inbox." else "Saved Inbox is here. Reconnect to refresh."
            }
        }finally{inboxLoading=false}
    }
    suspend fun refreshPlanning(force:Boolean=false){
        if(!repo.config.configured||pendingWrites.isNotEmpty())return
        val generation=repo.config.generation
        try{
            val fresh=repo.planningContext(force)
            if(generation==repo.config.generation&&pendingWrites.isEmpty())planning=fresh
        }catch(cancel:CancellationException){throw cancel}catch(_:Exception){
            // The editor keeps its cached picker and draft. Offline refresh is never a gate.
        }
    }
    suspend fun refreshMilestones(force:Boolean=false){
        if(!repo.config.configured)return
        val ticket=++milestonesRequestSerial;val generation=dashRepo.generation;val revision=Reminders.revision(context)
        milestonesLoading=milestonesList.isEmpty()
        try{
            val path=dashRepo.path("milestones")
            dashRepo.cached(path)?.let{milestonesList=it.dashboardObjects("rows")}
            val rows=mutableListOf<JSONObject>()
            var offset=0
            do {
                val data=dashRepo.load(dashRepo.path("milestones",offset=offset),force)
                if(generation!=dashRepo.generation||ticket!=milestonesRequestSerial||revision!=Reminders.revision(context))return
                rows.addAll(data.dashboardObjects("rows"))
                offset=if(data.has("next_offset")&&!data.isNull("next_offset"))data.getInt("next_offset")else -1
            }while(offset>=0)
            milestonesList=rows
            dashRepo.store(path,JSONObject().put("rows",org.json.JSONArray(rows)).put("next_offset",JSONObject.NULL),generation,revision)
            milestonesError=null
        }catch(cancel:CancellationException){throw cancel}catch(e:Exception){
            if(generation==dashRepo.generation&&ticket==milestonesRequestSerial)milestonesError=e.message?:"Couldn't load milestones."
        }finally{if(ticket==milestonesRequestSerial)milestonesLoading=false}
    }
    suspend fun refreshWeek(anchor:LocalDate=week?.date?.let(LocalDate::parse)?:today){
        if(!repo.config.configured)return
        val generation=repo.config.generation
        try{val fresh=repo.week(anchor);if(generation==repo.config.generation)week=fresh}
        catch(cancel:CancellationException){throw cancel}catch(_:Exception){/* The saved week stays on screen. */}
    }
    fun reconcile(){
        reconcileJob?.cancel()
        reconcileJob=scope.launch{
            delay(350)
            while(pendingWrites.isNotEmpty()||drag!=null||editorId!=null||adding)delay(100)
            refresh(true,true,true)
            if(inbox||focus)refreshInbox(true)
            if(focus)refreshWeek()
            refreshPlanning(true)
        }
    }
    fun optimistic(keys:Set<String>,change:(Day)->Day,write:suspend()->Unit,onSuccess:suspend()->Unit={},onFailure:()->Unit={}){
        val view=day?.takeIf{it.date==selectedIso}?:Day(selectedIso,planning?.timezone?:"Asia/Kolkata",emptyList())
        val available=(planning?.tasks.orEmpty()+backlog?.tasks.orEmpty()+listOfNotNull(editorBackup)).associateBy{it.id}.values
        val missing=available.filter{it.id in keys&&view.tasks.none{row->row.id==it.id}}
        val before=view.copy(tasks=view.tasks+missing)
        if(!mutations.begin(keys))return
        val generation=repo.config.generation
        val after=change(before);val ticket=before to after
        requestSerial++;loading=false;error=null;pendingWrites.add(ticket)
        projectLocal(before,after)
        repo.beginSnapshotWrite()
        TaskUpdateAlerts.scope.launch{
            var serverConfirmed=false
            var failure:Exception?=null
            try{
                withContext(Dispatchers.IO){repo.saveSnapshot(before,after,generation)}
                check(generation==repo.config.generation){"Connection changed before saving."}
                write();serverConfirmed=true
                if(generation==repo.config.generation){
                    onSuccess()
                    withContext(Dispatchers.IO){AutoFocusScheduler.syncChanges(context,after.tasks.filter{it.id in changedTaskIds(before,after)&&!it.id.startsWith("pending:")},after.date,after.timezone)}
                }
            }catch(e:Exception){
                if(generation==repo.config.generation&&!serverConfirmed){
                    projectLocal(after,before)
                    withContext(NonCancellable+Dispatchers.IO){repo.saveSnapshot(after,before,generation)}
                    onFailure();failure=e
                    TaskUpdateAlerts.reverted(context.applicationContext,generation,before,after,e)
                }
            }finally{
                mutations.end(keys);pendingWrites.remove(ticket);repo.endSnapshotWrite()
                if(generation==repo.config.generation){
                    withContext(NonCancellable+Dispatchers.IO){if(!repo.hasPendingSnapshots())repo.confirmSnapshots()}
                    // Every save or rejection quietly reconciles the currently visible day.
                    // A stale refresh must never leave the user needing to press Refresh.
                    reconcile()
                }
            }
            failure?.let{scope.launch{snackbar.showSnackbar(revertedUpdateMessage(before,after))}}
        }
    }

    fun toggleDone(task:Task){
        val prevIndex=todoScroll.firstVisibleItemIndex
        val prevOffset=todoScroll.firstVisibleItemScrollOffset
        optimistic(mutationKeys(task),{replaceTask(it,task.copy(done=!task.done))},{repo.patch(task,JSONObject().put("done",!task.done))})
        if(todoView){scope.launch{todoScroll.scrollToItem(prevIndex,prevOffset)}}
    }
    fun openFocus(){drag=null;inbox=false;showMilestones=false;focus=true;if(selectedIso!=today.toString())selectDate(today.toString())}
    fun plural(n:Int,word:String)="$n $word${if(n==1)"" else "s"}"
    // Focus moves and drops go through the same optimistic path as every other
    // edit, so day caches, the backlog, alarms and timers follow them.
    fun moveTasks(tasks:List<Task>,to:LocalDate){
        val live=tasks.filterNot{it.id.startsWith("pending:")};if(live.isEmpty())return
        val ids=live.map{it.id};val calendarToday=clock.toLocalDate()
        var extended=emptyList<String>()
        optimistic(live.flatMap{mutationKeys(it)}.toSet(),{view->live.fold(view){v,t->replaceTask(v,movedForFocus(t,to,calendarToday))}},
            {extended=milestoneNotes(repo.triage(ids,"move",to))},
            onSuccess={
                val label=if(to==today)"today" else to.format(DateTimeFormatter.ofPattern("EEE d MMM",java.util.Locale.ENGLISH))
                scope.launch{snackbar.showSnackbar("Moved ${plural(ids.size,"task")} to $label"+extended.joinToString(""){". $it"})}
                if(extended.isNotEmpty())refreshMilestones(true)
                refreshWeek()
            })
    }
    fun dropTasks(tasks:List<Task>){
        val live=tasks.filterNot{it.id.startsWith("pending:")};if(live.isEmpty())return
        val ids=live.map{it.id}
        optimistic(live.flatMap{mutationKeys(it)}.toSet(),{view->live.fold(view){v,t->replaceTask(v,t.copy(done=true))}},
            {repo.triage(ids,"drop");if(TimerStore.read(context)?.taskId in ids)TimerStore.reset(context)},
            onSuccess={scope.launch{snackbar.showSnackbar("Dropped ${plural(ids.size,"task")} — kept as skipped, not deleted")};refreshWeek()})
    }
    fun toggleStar(task:Task){
        // The backend counts actual scheduled dates, including overnight copies.
        // It owns the limit; a refused sixth rolls back this optimistic state.
        optimistic(mutationKeys(task),{replaceTask(it,task.copy(starred=!task.starred))},{repo.patch(task,JSONObject().put("starred",!task.starred))},onSuccess={editorBackup=editorBackup?.takeIf{it.id==task.id}?.copy(starred=!task.starred)?:editorBackup})
    }
    fun startTimer(task:Task){
        if(!TimerPreferences.enabled(context)||task.id.startsWith("pending:"))return
        if(timer!=null&&timer?.taskId!=task.id){replacement=task;return}
        requestNotification();TimerStore.start(context,task)
        if(!Settings.canDrawOverlays(context))scope.launch{snackbar.showSnackbar("Timer started. Enable floating timer in Settings to see it across apps.")}
    }
    fun schedule(task:Task){
        val slot=nextFreeSlot(selected,today,nowMinute,task.minutes,taskBlocks(currentTasks))
        openEditor(task);suggestedDate=slot.date.toString();suggestedTime=slot.clock
    }
    fun reveal(task:Task){
        if(todoView&&todoTasks.any{it.id==task.id}){inbox=false;scope.launch{delay(80);val index=todoTasks.indexOfFirst{it.id==task.id};if(index>=0)todoScroll.animateScrollToItem(index)}}
        else if(task.time==null){inbox=true;scope.launch{delay(80);val index=unscheduled.indexOfFirst{it.id==task.id};if(index>=0)inboxScroll.animateScrollToItem(index)}}
        else{inbox=false;scope.launch{delay(80);val bounds=timelineBounds(taskBlocks(timed));scroll.animateScrollTo(((task.clockMinutes-bounds.start)*TIMELINE_DP_PER_MINUTE*density-80*density).toInt().coerceAtLeast(0))}}
    }
    fun jumpNow(){
        if(selected!=today){selectDate(today.toString());return}
        inbox=false
        val target=timed.find{!it.done&&nowMinute>=it.clockMinutes&&nowMinute<it.clockMinutes+it.minutes}?:timed.find{it.clockMinutes>=nowMinute}?:timed.lastOrNull()
        target?.let{reveal(it)}
    }
    val dragPreview=drag?.let{d->
        val deltaDp=d.deltaY/density+(scroll.value-d.originScroll)/density
        val shift=if(d.deltaX>100*density)1 else if(d.deltaX< -100*density)-1 else 0
        val bounds=timelineBounds(taskBlocks(timed))
        DragPreview(d.task.id,deltaDp,shift,dragSlot(d.originDate,d.task.clockMinutes,deltaDp,shift,bounds.start,maxOf(1675,bounds.end-5)))
    }
    fun finishDrag(task:Task){
        val preview=dragPreview;val origin=drag?.originDate;drag=null
        if(preview==null||origin==null||selected!=origin)return
        val previous=normalizeSlot(origin,task.clockMinutes)
        if(preview.target==previous)return
        val target=preview.target
        optimistic(mutationKeys(task),{snapshot->replaceTask(snapshot,task.copy(time=target.clock,date=target.date.toString()))},
            {repo.patch(task,JSONObject().put("scheduled_date",target.date.toString()).put("start_time",target.clock))})
    }
    LaunchedEffect(selectedIso,connectionRevision){
        drag=null
        // Hydration happens synchronously in selectDate, before either scroll or network work.
        launch{scroll.scrollTo(0);todoScroll.scrollToItem(0)}
    }
    LaunchedEffect(selectedIso,connectionRevision,pendingSnapshotCount==0){
        if(pendingSnapshotCount==0)refresh(false,true,true)
    }
    LaunchedEffect(connectionRevision){TaskUpdateAlerts.restore(context.applicationContext)}
    LaunchedEffect(selectedIso,connectionRevision,pendingSnapshotCount==0){if(pendingSnapshotCount==0){delay(500);if(repo.config.configured)repo.warmDays(LocalDate.parse(selectedIso))}}
    LaunchedEffect(widgetOpen){
        val request=widgetOpen?:return@LaunchedEffect
        if(request.generation!=repo.config.generation){widgetHandled();return@LaunchedEffect}
        closeEditor();focus=false;inbox=false;showMilestones=false;drag=null
        selectDate(request.date)
        val task=request.task?.let{id->day?.tasks?.find{it.id==id}}
        if(task!=null)openEditor(task)
        else if(request.task!=null)error="This task is no longer in the saved day. Refresh to find its latest schedule."
        widgetHandled()
    }
    val widgetCacheChanged by rememberUpdatedState({
        if(pendingWrites.isEmpty()&&drag==null&&editorId==null&&!adding&&repo.config.configured){
            repo.cached(LocalDate.parse(selectedIso))?.let{paintDay(it)};backlog=repo.cachedInbox();planning=repo.cachedPlanningContext()
        }
    })
    DisposableEffect(context){
        val cache=context.getSharedPreferences("day-cache",android.content.Context.MODE_PRIVATE)
        val listener=android.content.SharedPreferences.OnSharedPreferenceChangeListener{_,_->widgetCacheChanged()}
        cache.registerOnSharedPreferenceChangeListener(listener)
        onDispose{cache.unregisterOnSharedPreferenceChangeListener(listener)}
    }
    LaunchedEffect(connectionRevision){refreshPlanning()}
    LaunchedEffect(adding,editorId,connectionRevision){if(adding||editorId!=null)refreshPlanning()}
    LaunchedEffect(inbox,connectionRevision){if(inbox){refreshInbox();refreshPlanning()}}
    LaunchedEffect(showMilestones,connectionRevision){if(showMilestones)refreshMilestones()}
    LaunchedEffect(focus,connectionRevision){if(focus){refreshInbox();refreshWeek();refreshMilestones()}}
    LaunchedEffect(selectedIso,connectionRevision){while(true){delay(60*60*1000L);refresh(true)}}
    LaunchedEffect(Unit){while(true){timer=TimerStore.read(context);remaining=timer?.let{TimerStore.remaining(context,it)}?:0;clock=ZonedDateTime.now(ZoneId.of(day?.timezone?:"Asia/Kolkata"));FocusWorkLogs.prompt(context);delay(1000)}}
    LaunchedEffect(clock.toLocalDate(),clock.hour,clock.minute){if(lifecycle.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))AutoFocusScheduler.catchUp(context)}
    LaunchedEffect(today){if(lastToday!=today.toString()){if(selectedIso==lastToday)selectDate(today.toString());lastToday=today.toString()}}
    LaunchedEffect(drag!=null){while(drag!=null){val y=drag!!.pointerY;if(y>0&&viewportBottom>viewportTop){if(y<viewportTop+48*density)scroll.scrollBy(-10*density)else if(y>viewportBottom-48*density)scroll.scrollBy(10*density)};delay(24)}}
    val latestResume by rememberUpdatedState({
        drag=null
        clock=ZonedDateTime.now(ZoneId.of(day?.timezone?:"Asia/Kolkata"))
        val actual=logicalToday(clock).toString()
        if(actual!=lastToday){if(selectedIso==lastToday)selectDate(actual);lastToday=actual}
        Reminders.setup(context);AutoFocusScheduler.catchUp(context)
        if(TimerStore.read(context)!=null)TimerStore.action(context,"SHOW")
        scope.launch{refresh(true);if(inbox||focus)refreshInbox();if(showMilestones||focus)refreshMilestones();if(focus)refreshWeek()}
        scope.launch{refreshPlanning()}
        scope.launch{if(FocusWorkLogs.entries(context).any{it.has("body")}&&FocusWorkLogs.syncReady(context)){refresh(true);if(inbox)refreshInbox()}}
    })
    DisposableEffect(lifecycle){val observer=LifecycleEventObserver{_,event->if(event==Lifecycle.Event.ON_RESUME)latestResume() else if(event==Lifecycle.Event.ON_PAUSE)drag=null};lifecycle.lifecycle.addObserver(observer);onDispose{lifecycle.lifecycle.removeObserver(observer)}}
    Scaffold(containerColor=MaterialTheme.colorScheme.background,snackbarHost={SnackbarHost(snackbar)},bottomBar={
        Column{
            timer?.takeIf{TimerPreferences.enabled(context)}?.let{s->Surface(color=if(dark)Color(0xFF332A23)else Color(0xFFF2E8D9)){Column{Row(Modifier.fillMaxWidth().padding(horizontal=16.dp,vertical=9.dp),verticalAlignment=Alignment.CenterVertically){
                Icon(Icons.Rounded.HourglassBottom,null,tint=if(dark)Color(0xFFD2A570)else Color(0xFF80502F));Spacer(Modifier.width(10.dp));Column(Modifier.weight(1f)){Text(s.title,maxLines=1,overflow=TextOverflow.Ellipsis,fontWeight=FontWeight.SemiBold);Text("${timerText(remaining)} · ${if(s.running)"Focus" else "Paused"}",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)}
                IconButton(onClick={TimerStore.action(context,"TOGGLE")}){Icon(if(s.running)Icons.Rounded.Pause else Icons.Rounded.PlayArrow,"Pause or resume timer")}
                IconButton(onClick={TimerStore.action(context,"STOP")}){Icon(Icons.Rounded.Close,"Cancel timer")}
                IconButton(onClick={context.startActivity(Intent(context,MainActivity::class.java).putExtra("finish_timer",s.taskId).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP))}){Icon(Icons.Rounded.Check,"Finish timer",tint=if(dark)Color(0xFFD2A570)else Color(0xFF80502F))}
            }
                LinearProgressIndicator(progress={(remaining.toFloat()/s.durationMs.coerceAtLeast(1)).coerceIn(0f,1f)},modifier=Modifier.fillMaxWidth().height(5.dp),color=if(dark)Color(0xFFD2A570)else Color(0xFF80502F),trackColor=if(dark)Color(0xFF4C3C2E)else Color(0xFFDCC7AE))
            }}}
            // Two places to be: what needs you (Focus) and the day itself (Today).
            // Inbox, Milestones and Dashboard moved to the top bar's menu, so the
            // bar no longer mixes destinations with a view toggle.
            Surface{Row(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal=10.dp,vertical=8.dp),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically){
                val onDayTab=!focus&&!inbox&&!showMilestones
                TextButton(onClick={drag=null;focus=false;inbox=false;showMilestones=false},modifier=Modifier.weight(1f).height(62.dp),contentPadding=PaddingValues(2.dp)){
                    Column(horizontalAlignment=Alignment.CenterHorizontally){
                        Icon(Icons.Rounded.ViewDay,null,modifier=Modifier.size(22.dp),tint=if(onDayTab)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                        Text("Today",fontSize=11.sp,color=if(onDayTab)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,maxLines=1)
                    }
                }
                FilledIconButton(onClick={closeEditor();recovery=drafts.remove("new");adding=true},modifier=Modifier.size(48.dp),shape=CircleShape){Icon(Icons.Rounded.Add,"Add a task")}
                TextButton(onClick={openFocus()},modifier=Modifier.weight(1f).height(62.dp),contentPadding=PaddingValues(2.dp)){
                    Column(horizontalAlignment=Alignment.CenterHorizontally){
                        Icon(Icons.Rounded.CenterFocusStrong,null,modifier=Modifier.size(22.dp),tint=if(focus)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                        Text("Focus",fontSize=11.sp,color=if(focus)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,maxLines=1)
                    }
                }
            }}
        }
    }){padding->
        Column(Modifier.fillMaxSize().padding(padding)){
            Row(Modifier.fillMaxWidth().padding(start=16.dp,end=4.dp,top=2.dp),verticalAlignment=Alignment.CenterVertically){
                Column(Modifier.weight(1f).then(if(!onDay)Modifier else Modifier.clickable{DatePickerDialog(pickerContext(context,dark),{_,y,m,d->selectDate(LocalDate.of(y,m+1,d).toString())},selected.year,selected.monthValue-1,selected.dayOfMonth).show()})){
                    Text(if(focus)"Focus" else if(showMilestones)"Milestones" else if(inbox)"Inbox" else (if(selected==today)"Today · " else "")+selected.format(DateTimeFormatter.ofPattern("MMM d")),fontSize=19.sp,fontWeight=FontWeight.SemiBold,maxLines=1,overflow=TextOverflow.Ellipsis)
                    if(focus)Text("${focusOverdue.size} overdue · ${focusTodayTasks.size} left today",fontSize=10.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                    else if(onDay)Text("${currentTasks.count{it.done}} of ${currentTasks.size} complete",fontSize=10.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                    else if(showMilestones)Text("${milestonesList.count{milestoneIsComplete(it)}} of ${milestonesList.size} milestones finished",fontSize=10.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if(onDay)TextButton(onClick={selectDate(today.toString());if(selected==today)jumpNow()},contentPadding=PaddingValues(horizontal=7.dp,vertical=0.dp)){Text(if(selected==today)"Now" else "Today",fontSize=12.sp)}
                IconButton(enabled=drag==null&&editorId==null&&!adding,onClick={scope.launch{
                    if(showMilestones)refreshMilestones(true) else refresh(true,false,true)
                    if(inbox||focus)refreshInbox(true)
                    if(focus){refreshWeek();refreshMilestones(true)}
                    refreshPlanning(true)
                }}){Icon(Icons.Rounded.Refresh,"Refresh")}
                // Timeline or list is a view of the day, so it sits with the day
                // rather than doubling as a tab.
                if(onDay)IconButton(onClick={todoView=!todoView;viewPrefs.edit().putBoolean("day_todo",todoView).apply()}){
                    Icon(if(todoView)Icons.Rounded.ViewTimeline else Icons.AutoMirrored.Rounded.ViewList,if(todoView)"Show timeline" else "Show list")
                }
                Box{
                    IconButton(onClick={menu=true}){Icon(Icons.Rounded.MoreVert,"More")}
                    DropdownMenu(expanded=menu,onDismissRequest={menu=false}){
                        DropdownMenuItem(text={Text("Inbox")},leadingIcon={Icon(Icons.Rounded.Inbox,null)},onClick={menu=false;drag=null;focus=false;showMilestones=false;inbox=true})
                        DropdownMenuItem(text={Text("Milestones")},leadingIcon={Icon(Icons.Rounded.Flag,null)},onClick={menu=false;drag=null;focus=false;inbox=false;showMilestones=true})
                        DropdownMenuItem(text={Text("Dashboard")},leadingIcon={Icon(Icons.Rounded.Dashboard,null)},onClick={menu=false;context.startActivity(Intent(context,DashboardActivity::class.java))})
                        DropdownMenuItem(text={Text("Settings")},leadingIcon={Icon(Icons.Rounded.Tune,null)},onClick={menu=false;settings=true})
                    }
                }
            }
            if(onDay)Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically){
                IconButton(onClick={selectDate(selected.minusDays(7).toString())},modifier=Modifier.size(30.dp)){Icon(Icons.Rounded.ChevronLeft,"Previous week")}
                val start=selected.minusDays((selected.dayOfWeek.value-1).toLong())
                for(index in 0..6){val d=start.plusDays(index.toLong());val isSelected=d==selected
                    Column(Modifier.weight(1f).semantics{contentDescription=d.format(DateTimeFormatter.ofPattern("EEEE, MMMM d, yyyy"))+(if(isSelected)", selected" else "")}.background(if(isSelected)MaterialTheme.colorScheme.primary else Color.Transparent,RoundedCornerShape(10.dp)).clickable{selectDate(d.toString())}.padding(vertical=2.dp),horizontalAlignment=Alignment.CenterHorizontally){
                        Text(d.format(DateTimeFormatter.ofPattern("EEEEE")),fontSize=10.sp,color=if(isSelected)MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(d.dayOfMonth.toString(),fontSize=15.sp,fontWeight=FontWeight.Bold,color=if(isSelected)MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface)
                        val hasTasks=if(d==selected)currentTasks.isNotEmpty()else repo.cached(d)?.tasks?.isNotEmpty()==true
                        Box(Modifier.padding(top=3.dp).size(4.dp).background(if(d==today||hasTasks)if(isSelected)MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.primary else Color.Transparent,CircleShape))
                    }
                }
                IconButton(onClick={selectDate(selected.plusDays(7).toString())},modifier=Modifier.size(30.dp)){Icon(Icons.Rounded.ChevronRight,"Next week")}
            }
            if(onDay&&currentTasks.isNotEmpty())LinearProgressIndicator(progress={currentTasks.count{it.done}.toFloat()/currentTasks.size},modifier=Modifier.fillMaxWidth().padding(horizontal=20.dp).height(3.dp),trackColor=MaterialTheme.colorScheme.primary.copy(alpha=.10f))
            if(onDay)WinsPanel(currentTasks,day?.starLimit?:5){reveal(it)}
            if(inbox)InboxOverview(filteredInbox,projectDayTasks,if(selected==today)"Today" else selected.format(DateTimeFormatter.ofPattern("MMM d")),filteredInbox.count{isOverdue(it,clock)},inboxFilter,{inboxFilter=it},pickerProjects(planningProjects,resolvedInboxProjectId),resolvedInboxProjectId,{inboxProjectId=it})
            if(pendingSnapshotCount>0)Row(Modifier.fillMaxWidth().padding(horizontal=20.dp,vertical=4.dp),verticalAlignment=Alignment.CenterVertically){
                Icon(Icons.Rounded.CloudUpload,null,Modifier.size(15.dp),tint=MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(6.dp));Text("Saving in background…",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
            }
            updateFailures.firstOrNull{it.generation==repo.config.generation}?.let{failure->
                Surface(color=MaterialTheme.colorScheme.errorContainer,shape=RoundedCornerShape(10.dp),modifier=Modifier.fillMaxWidth().padding(horizontal=18.dp,vertical=5.dp)){
                    Row(Modifier.padding(start=10.dp,top=4.dp,bottom=4.dp),verticalAlignment=Alignment.CenterVertically){
                        Icon(Icons.Rounded.ErrorOutline,null,Modifier.size(20.dp),tint=MaterialTheme.colorScheme.onErrorContainer)
                        Text(failure.message,fontSize=13.sp,color=MaterialTheme.colorScheme.onErrorContainer,modifier=Modifier.weight(1f).padding(horizontal=8.dp))
                        TextButton(onClick={showUpdateFailures=true}){Text("Details")}
                    }
                }
            }
            if(loading||inbox&&inboxLoading||showMilestones&&milestonesLoading)LinearProgressIndicator(Modifier.fillMaxWidth().height(1.dp))
            error?.let{Surface(color=MaterialTheme.colorScheme.primary.copy(alpha=.055f),shape=RoundedCornerShape(12.dp),modifier=Modifier.fillMaxWidth().padding(horizontal=18.dp,vertical=5.dp)){Text((if(day?.cached==true)"Offline · " else "")+it,fontSize=11.sp,modifier=Modifier.padding(8.dp))}}
            val swipe=Modifier.pointerInput(selectedIso,drag!=null){
                if(drag==null)awaitEachGesture{
                    val down=awaitFirstDown(requireUnconsumed=false);val origin=down.position
                    var last=origin;var canceled=false
                    do{val event=awaitPointerEvent()
                        if(event.changes.count{it.pressed}>1||event.changes.any{it.isConsumed})canceled=true
                        event.changes.find{it.id==down.id}?.let{last=it.position}
                    }while(event.changes.any{it.pressed})
                    val delta=last-origin
                    if(!canceled&&kotlin.math.abs(delta.x)>70*density&&kotlin.math.abs(delta.x)>kotlin.math.abs(delta.y)*1.6f)
                        selectDate(selected.plusDays(if(delta.x<0)1 else -1).toString())
                }
            }
            if(focus){
                FocusScreen(focusOverdue,focusTodayTasks,week,focusMilestones,focusProjectNames,clock,today,dark,backlog!=null,
                    busy={taskBusy(it)},onOpen={openEditor(it)},onDone={toggleDone(it)},
                    onMove={tasks,to->moveTasks(tasks,to)},onDrop={dropTasks(it)},
                    onWeek={anchor->scope.launch{refreshWeek(anchor)}},
                    onOpenDay={date->drag=null;focus=false;inbox=false;showMilestones=false;selectDate(date.toString())},
                    modifier=Modifier.weight(1f).fillMaxWidth())
            }else if(showMilestones){
                DayMilestonesView(
                    milestones=milestonesList,
                    loading=milestonesLoading,
                    error=milestonesError,
                    modifier=Modifier.weight(1f),
                    onRefresh={scope.launch{refreshMilestones(true)}},
                    onMilestoneClick={row->context.startActivity(MilestoneActivity.intent(context,row))}
                )
            }else if(inbox){
                val visible=when(inboxFilter){"Overdue"->filteredInbox.filter{isOverdue(it,clock)};"Done"->projectDayTasks.filter{it.done};else->filteredInbox.filterNot{it.done}}
                val sections=if(inboxFilter=="Open")listOf("Overdue" to visible.filter{isOverdue(it,clock)},"Unscheduled" to visible.filterNot{isOverdue(it,clock)})else listOf(inboxFilter to visible)
                LazyColumn(Modifier.weight(1f).fillMaxWidth().then(swipe),state=inboxScroll,contentPadding=PaddingValues(bottom=24.dp)){
                    if(visible.isEmpty())item{EmptyState(if(inboxFilter=="Done")"No completed inbox tasks" else "Your ${inboxFilter.lowercase()} list is clear",if(inboxFilter=="Done")"Completed tasks appear here for this day." else "Add an idea. Schedule it when you're ready.")}
                    sections.forEach{(label,rows)->if(rows.isNotEmpty()){
                        item(key="section:$label"){InboxSection(label,rows.size,rows.sumOf{it.minutes})}
                        items(rows,key={it.id}){task->InboxCard(task,dark,!taskBusy(task),{openEditor(task)},{toggleDone(task)},{toggleStar(task)},{schedule(task)},overdue=isOverdue(task,clock))}
                    }}
                }
            }else if(todoView){
                LazyColumn(Modifier.weight(1f).fillMaxWidth().then(swipe),state=todoScroll,contentPadding=PaddingValues(start=12.dp,end=12.dp,top=6.dp,bottom=24.dp)){
                    if(openTasks.isEmpty()&&completedTasks.isEmpty())item(key="empty"){EmptyState("A clear day","Add a task, with or without a time.")}
                    items(openTasks,key={"open:${it.id}"}){task->DayTodoCard(task,dark,!taskBusy(task),timer?.taskId==task.id,{openEditor(task)},{toggleDone(task)},{toggleStar(task)},{startTimer(task)})}
                    if(completedTasks.isNotEmpty()){
                        item(key="header:completed"){
                            Row(Modifier.fillMaxWidth().padding(top=10.dp,bottom=2.dp),verticalAlignment=Alignment.CenterVertically){
                                Text("Completed · ${completedTasks.size}",fontSize=12.sp,fontWeight=FontWeight.SemiBold,color=MaterialTheme.colorScheme.onSurfaceVariant)
                                HorizontalDivider(Modifier.padding(start=10.dp).weight(1f),color=MaterialTheme.colorScheme.outlineVariant.copy(alpha=.5f))
                            }
                        }
                        items(completedTasks,key={"done:${it.id}"}){task->DayTodoCard(task,dark,!taskBusy(task),timer?.taskId==task.id,{openEditor(task)},{toggleDone(task)},{toggleStar(task)},{startTimer(task)})}
                    }
                }
            }else if(timed.isEmpty()){
                Box(Modifier.weight(1f).fillMaxWidth().then(swipe),contentAlignment=Alignment.Center){EmptyState("A little space to breathe",if(unscheduled.isEmpty())"Add your first block for this day." else "${unfinishedInbox} inbox items are ready to schedule.")}
            }else{
                ProportionalTimeline(timed,selected,selected==today,nowMinute,timer?.taskId,dark,true,scroll,dragPreview,
                    Modifier.weight(1f).fillMaxWidth().then(swipe),
                    {openEditor(it)},{toggleDone(it)},{toggleStar(it)},{startTimer(it)},
                    {minute->closeEditor();adding=true;val slot=normalizeSlot(selected,minute);suggestedDate=slot.date.toString();suggestedTime=slot.clock},
                    {task->requestSerial++;loading=false;drag=DragState(task,selected,scroll.value)},
                    {_,offset,y->drag=drag?.let{it.copy(deltaX=it.deltaX+offset.x,deltaY=it.deltaY+offset.y,pointerY=y)}},
                    {finishDrag(it)},{drag=null},{top,bottom->viewportTop=top;viewportBottom=bottom})
            }
        }
    }
    if(showUpdateFailures)AlertDialog(onDismissRequest={showUpdateFailures=false},title={Text("Changes that couldn't be saved")},text={
        LazyColumn(verticalArrangement=Arrangement.spacedBy(12.dp)){
            items(updateFailures.filter{it.generation==repo.config.generation},key={it.id}){failure->
                Column{
                    Text(failure.message,fontWeight=FontWeight.SemiBold)
                    Text(failure.detail,fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                    TextButton(onClick={TaskUpdateAlerts.scope.launch{TaskUpdateAlerts.dismiss(context.applicationContext,failure.id)}}){Text("Dismiss")}
                }
            }
        }
    },confirmButton={TextButton(onClick={showUpdateFailures=false}){Text("Close")}})
    if(settings)ConnectionSettings(repo,appearance,onAppearance,{settings=false},requestNotification,{
        closeEditor();drafts.clear();dayPages.clear();day=null;milestonesList=emptyList();milestonesRequestSerial++;backlog=repo.cachedInbox();planning=repo.cachedPlanningContext();inboxProjectId=null;connectionRevision++;scope.launch{refresh(false)}
    })
    if(adding||editor!=null)PlannerEditor(editor,selected,suggestedDate,suggestedTime,editor?.let{taskBusy(it)}?:false,recovery,
        planningProjects,projectAliases,suggestionRows,resolvedInboxProjectId,{task->schedule(task)},::closeEditor,{title,date,time,minutes,notes,projectId,projectExplicit->
        val original=editor?.let{edit->currentTasks.find{it.id==edit.id}?:edit}
        val viewDate=selected
        val pending=original?.copy(title=title,date=date.toString(),time=time,minutes=minutes,notes=notes,projectId=projectId)
            ?:Task("pending:${UUID.randomUUID()}",title,time,minutes,false,false,false,null,date.toString(),notes,projectId)
        val writeGeneration=repo.config.generation
        var createdId:String?=null
        closeEditor()
        optimistic(original?.let(::mutationKeys)?:setOf(pending.id),{snapshot->
            val without=snapshot.tasks.filterNot{it.id==original?.id}
            snapshot.copy(tasks=without+pending)
        },{
            if(original==null)createdId=repo.create(title,date,time,minutes,notes,projectId=projectId)
            else {
                val patch=JSONObject().put("title",title).put("scheduled_date",date.toString()).put("start_time",time?:JSONObject.NULL).put("estimated_minutes",minutes)
                    .put("notes",notes?:JSONObject.NULL)
                if(shouldPatchPlanningProject(original.projectId,projectId,projectExplicit))patch.put("project_id",projectId?:JSONObject.NULL)
                repo.patch(original,patch)
            }
        },onSuccess={
            if(original==null){
                val source=Day(viewDate.toString(),day?.timezone?:"Asia/Kolkata",listOf(pending))
                val resolved=source.copy(tasks=listOf(pending.copy(id=requireNotNull(createdId))))
                val resolvedKeys=resolved.tasks.map{it.id}.toSet()
                val acquired=mutations.begin(resolvedKeys)
                try{
                    projectLocal(source,resolved)
                    withContext(Dispatchers.IO){
                        repo.saveSnapshot(source,resolved,writeGeneration)
                        AutoFocusScheduler.syncChanges(context,resolved.tasks,source.date,source.timezone)
                    }
                }finally{if(acquired)mutations.end(resolvedKeys)}
            }
        },onFailure={drafts[original?.id?:"new"]=EditorValues(title,date,time,minutes,notes,projectId,projectExplicit)})
    },{toggleStar(it)},{task->splitTarget=task},{deleteTarget=it},{startTimer(it);closeEditor()},{task->closeEditor();FocusWorkLogs.open(context,task.id)})
    splitTarget?.let{task->AlertDialog(onDismissRequest={splitTarget=null},title={Text("Split remaining work?")},text={Column{
        Text(task.title,fontWeight=FontWeight.SemiBold)
        Text("Two sessions: ${workDuration((task.remainingSeconds+1)/2)} and ${workDuration(task.remainingSeconds/2)}. ${if(TimerPreferences.enabled(context)&&task.workedSeconds>0)"The first starts after the worked portion" else "The first keeps its slot"}; the second is unscheduled in Inbox.")
        if(TimerPreferences.enabled(context)&&task.workedSeconds>0)Text("Your ${workDuration(task.workedSeconds)} already worked stays recorded in a completed session.")
    }},confirmButton={TextButton(enabled=!taskBusy(task),onClick={
        splitTarget=null
        val generation=repo.config.generation
        val sourceDate=selectedIso
        val preview=splitTaskPreview(task,sourceDate,UUID.randomUUID().toString())
        var result:JSONObject?=null
        closeEditor()
        optimistic(mutationKeys(task),{snapshot->snapshot.copy(tasks=snapshot.tasks.filterNot{it.id==task.id}+preview)},
            {result=repo.split(task)},onSuccess={
                val response=requireNotNull(result)
                val first=preview.first{!it.done}
                val second=preview.last()
                val resolved=preview.map{row->row.copy(id=when(row.id){
                    first.id->response.getString("first_id")
                    second.id->response.getString("second_id")
                    else->response.getString("worked_id")
                })}
                val before=Day(sourceDate,day?.timezone?:"Asia/Kolkata",preview)
                val after=before.copy(tasks=resolved)
                val resolvedKeys=resolved.map{it.id}.toSet()-mutationKeys(task)
                val acquired=mutations.begin(resolvedKeys)
                try{
                    projectLocal(before,after)
                    withContext(Dispatchers.IO){repo.saveSnapshot(before,after,generation);AutoFocusScheduler.syncChanges(context,resolved,sourceDate,after.timezone)}
                }finally{if(acquired)mutations.end(resolvedKeys)}
            })
    }){Text("Split")}},dismissButton={TextButton(onClick={splitTarget=null}){Text("Cancel")}})}
    deleteTarget?.let{task->AlertDialog(onDismissRequest={deleteTarget=null},title={Text(if(task.habit)"Skip this occurrence?" else "Delete this task?")},text={Text(task.title)},confirmButton={TextButton(enabled=!taskBusy(task),onClick={deleteTarget=null;closeEditor();optimistic(mutationKeys(task),{it.copy(tasks=it.tasks.filterNot{row->row.id==task.id})},{repo.delete(task)})}){Text(if(task.habit)"Skip" else "Delete")}},dismissButton={TextButton(onClick={deleteTarget=null}){Text("Cancel")}})}
    replacement?.takeIf{TimerPreferences.enabled(context)}?.let{task->AlertDialog(onDismissRequest={replacement=null},title={Text("Switch focus?")},text={Text("This ends the timer for ${timer?.title}. Its task stays as it is.")},confirmButton={TextButton(onClick={TimerStore.start(context,task);replacement=null;requestNotification()}){Text("Start new timer")}},dismissButton={TextButton(onClick={replacement=null}){Text("Keep current")}})}
    LaunchedEffect(finishId){if(finishId!=null){
        val state=TimerStore.read(context)
        if(state!=null&&state.taskId==finishId){
            try{
                val needsEntry=FocusWorkLogs.finishTimer(context,state)
                if(!needsEntry){
                    val entry=FocusWorkLogs.entries(context).firstOrNull{it.optString("id")==state.sessionId}
                    if(entry==null){finishHandled();return@LaunchedEffect}
                    try{FocusWorkLogs.submit(context,entry);refresh(true,true,true);snackbar.showSnackbar("${workDuration(entry.optInt("seconds"))} logged")}
                    catch(e:Exception){snackbar.showSnackbar("${workDuration(entry.optInt("seconds"))} saved on this device. Open Log time to retry.")}
                }
            }catch(e:Exception){snackbar.showSnackbar(e.message?:"Couldn't save time. The timer is still available.")}
        }
        finishHandled()
    }}
}

@Composable internal fun EmptyState(title:String,message:String){Column(Modifier.fillMaxWidth().padding(vertical=42.dp,horizontal=24.dp),horizontalAlignment=Alignment.CenterHorizontally){Icon(Icons.Rounded.WbSunny,null,tint=MaterialTheme.colorScheme.primary,modifier=Modifier.size(38.dp));Spacer(Modifier.height(14.dp));Text(title,fontSize=21.sp,fontWeight=FontWeight.SemiBold);Text(message,fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=9.dp))}}
