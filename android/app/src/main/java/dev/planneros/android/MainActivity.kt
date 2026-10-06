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
import org.json.JSONObject
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.UUID

class MainActivity:ComponentActivity(){
    private var finishId by mutableStateOf<String?>(null)
    private val permission=registerForActivityResult(ActivityResultContracts.RequestPermission()){Reminders.setup(this)}
    override fun onCreate(savedInstanceState:Bundle?){
        super.onCreate(savedInstanceState);enableEdgeToEdge();FocusWorkLogs.restoreNotifications(this);finishId=intent.getStringExtra("finish_timer")
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
            MaterialTheme(colorScheme=colors){PlannerScreen(finishId,{finishId=null},{if(Build.VERSION.SDK_INT>=33)permission.launch(Manifest.permission.POST_NOTIFICATIONS)},dark,appearance,{appearance=it;prefs.edit().putString("theme",it).apply()})}
        }
        Reminders.setup(this)
        if(TimerStore.read(this)!=null)TimerStore.action(this,"SHOW")
    }
    override fun onNewIntent(intent:Intent){super.onNewIntent(intent);setIntent(intent);finishId=intent.getStringExtra("finish_timer")}
    override fun onResume(){super.onResume();FocusWorkLogs.foreground++}
    override fun onPause(){FocusWorkLogs.foreground=(FocusWorkLogs.foreground-1).coerceAtLeast(0);super.onPause()}
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlannerScreen(finishId:String?,finishHandled:()->Unit,requestNotification:()->Unit,dark:Boolean,appearance:String,onAppearance:(String)->Unit){
    val lifecycle=LocalLifecycleOwner.current
    val context=LocalContext.current;val repo=remember{PlannerRepository(context)}
    val scope=rememberCoroutineScope();val snackbar=remember{SnackbarHostState()};val density=LocalDensity.current.density
    val compactNavigation=LocalConfiguration.current.screenWidthDp<360&&LocalDensity.current.fontScale>1.25f
    var selectedIso by rememberSaveable{mutableStateOf(logicalToday(ZonedDateTime.now(ZoneId.of("Asia/Kolkata"))).toString())}
    val selected=LocalDate.parse(selectedIso)
    var day by remember{mutableStateOf<Day?>(repo.cached(selected))}
    var backlog by remember{mutableStateOf(repo.cachedInbox())}
    var inboxLoading by remember{mutableStateOf(false)}
    val mutations=remember{MutationCoordinator()}
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
    val todoTasks=remember(currentTasks){currentTasks.sortedWith(compareBy<Task>{it.done}.thenBy{it.clockMinutes})}
    val unscheduled=inboxRows(day?.takeIf{it.date==selectedIso},backlog,clock)
    val unfinishedInbox=unscheduled.count{!it.done}
    val editor=editorId?.let{id->currentTasks.find{it.id==id}?:editorBackup?.takeIf{it.id==id}}
    fun closeEditor(){adding=false;editorId=null;editorBackup=null;suggestedDate=null;suggestedTime=null;recovery=null}
    fun taskBusy(task:Task)=pendingWrites.isNotEmpty()&&mutationKeys(task).any{mutations.pending(it)}
    fun openEditor(task:Task){if(taskBusy(task)||task.id.startsWith("pending:"))return;drag=null;requestSerial++;loading=false;recovery=drafts.remove(task.id);adding=false;editorId=task.id;editorBackup=task;suggestedDate=null;suggestedTime=null}
    suspend fun refresh(preserve:Boolean=true,quiet:Boolean=true,force:Boolean=false){
        if(drag!=null||editorId!=null||adding)return
        if(!repo.config.configured){settings=true;return}
        val date=selected;val serial=++requestSerial;val generation=repo.config.generation
        if(!preserve||day?.date!=date.toString())day=repo.cached(date)
        if(!force&&day!=null&&repo.isFresh(date)){
            repo.confirmedCached(date)?.let{AutoFocusScheduler.sync(context,it)}
            AutoFocusScheduler.catchUp(context);loading=false;return
        }
        loading=day==null
        if(!quiet)error=null
        try{
            val fresh=repo.day(date)
            if(selectedIso==date.toString()&&serial==requestSerial&&generation==repo.config.generation&&drag==null&&editorId==null&&!adding){
                day=pendingWrites.fold(fresh){view,(before,after)->projectChanges(view,before,after)}
                clock=ZonedDateTime.now(ZoneId.of(fresh.timezone))
                if(date==logicalToday(clock))Reminders.schedule(context,fresh)
                AutoFocusScheduler.sync(context,fresh)
                AutoFocusScheduler.catchUp(context)
                TimerStore.read(context)?.let{active->fresh.tasks.find{it.id==active.taskId}?.let{TimerStore.refresh(context,it)}}
            }
        }catch(cancel:CancellationException){throw cancel}catch(e:Exception){
            if(selectedIso==date.toString()&&serial==requestSerial&&generation==repo.config.generation){
                if(e is PlannerHttpException&&e.statusCode in listOf(401,403)){settings=true;error=e.message}
                else if((!quiet||day==null)&&e.message!="Plan changed while refreshing. Refresh this day again.")
                    error=if(e is PlannerHttpException)e.message else if(e is java.io.IOException)"Your saved day is here. Reconnect to refresh and save changes." else e.message?:"Couldn't refresh this day."
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
    fun reconcile(){
        reconcileJob?.cancel()
        reconcileJob=scope.launch{
            delay(350)
            while(pendingWrites.isNotEmpty()||drag!=null||editorId!=null||adding)delay(100)
            refresh(true,true,true)
            if(inbox)refreshInbox(true)
        }
    }
    fun optimistic(keys:Set<String>,change:(Day)->Day,write:suspend()->Unit,onSuccess:()->Unit={},onFailure:()->Unit={},needsReconcile:Boolean=false){
        val view=day?.takeIf{it.date==selectedIso}?:return
        val missing=backlog?.tasks.orEmpty().filter{it.id in keys&&view.tasks.none{row->row.id==it.id}}
        val before=view.copy(tasks=view.tasks+missing)
        if(!mutations.begin(keys))return
        val generation=repo.config.generation
        val after=change(before);val ticket=before to after
        requestSerial++;loading=false;day=projectChanges(view,before,after);error=null;pendingWrites.add(ticket)
        repo.beginSnapshotWrite();repo.saveSnapshot(before,after);backlog=repo.cachedInbox()
        scope.launch{
            var failure:String?=null
            try{write();if(generation==repo.config.generation){
                onSuccess()
                AutoFocusScheduler.syncChanges(context,after.tasks.filter{it.id in changedTaskIds(before,after)&&!it.id.startsWith("pending:")},after.date,after.timezone)
            }}
            catch(cancel:CancellationException){if(generation==repo.config.generation){day=day?.let{projectChanges(it,after,before)};repo.saveSnapshot(after,before);backlog=repo.cachedInbox()};throw cancel}
            catch(e:Exception){
                if(generation==repo.config.generation){day=day?.let{projectChanges(it,after,before)};repo.saveSnapshot(after,before);backlog=repo.cachedInbox();onFailure()}
                failure=e.message?:"Change couldn't be saved; restored the previous task."
            }finally{
                mutations.end(keys);pendingWrites.remove(ticket);repo.endSnapshotWrite()
                if(pendingWrites.isEmpty()&&generation==repo.config.generation)repo.confirmSnapshots()
                if(needsReconcile)reconcile()
                else if(pendingWrites.isEmpty()&&generation==repo.config.generation){
                    day?.let{confirmed->val current=confirmed.copy(cached=false,alarmRevision=Reminders.revision(context),connectionGeneration=generation);day=current
                        if(current.date==today.toString())Reminders.schedule(context,current)
                        // Sync every cached affected date, including a task moved off-screen.
                        (listOf(before.date,after.date,current.date)+after.tasks.filter{it.id in changedTaskIds(before,after)}.mapNotNull{it.date}).distinct().forEach{iso->repo.confirmedCached(LocalDate.parse(iso))?.let{AutoFocusScheduler.sync(context,it)}}
                        AutoFocusScheduler.catchUp(context)
                        TimerStore.read(context)?.let{active->current.tasks.find{it.id==active.taskId}?.let{TimerStore.refresh(context,it)}}
                    }
                }
            }
            // A snackbar never owns a mutation lock or blocks another editor.
            failure?.let{message->scope.launch{snackbar.showSnackbar(message)}}
        }
    }
    fun toggleDone(task:Task){optimistic(mutationKeys(task),{replaceTask(it,task.copy(done=!task.done))},{repo.patch(task,JSONObject().put("done",!task.done))},needsReconcile=task.parent!=null)}
    fun toggleStar(task:Task){
        // The backend counts actual scheduled dates, including overnight copies.
        // It owns the limit; a refused sixth rolls back this optimistic state.
        optimistic(mutationKeys(task),{replaceTask(it,task.copy(starred=!task.starred))},{repo.patch(task,JSONObject().put("starred",!task.starred))},onSuccess={editorBackup=editorBackup?.takeIf{it.id==task.id}?.copy(starred=!task.starred)?:editorBackup})
    }
    fun startTimer(task:Task){
        if(task.id.startsWith("pending:"))return
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
        if(selected!=today){selectedIso=today.toString();return}
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
        drag=null;scroll.scrollTo(0);todoScroll.scrollToItem(0);refresh(false)

    }
    LaunchedEffect(inbox,connectionRevision){if(inbox)refreshInbox()}
    LaunchedEffect(selectedIso,connectionRevision){while(true){delay(60*60*1000L);refresh(true)}}
    LaunchedEffect(Unit){while(true){timer=TimerStore.read(context);remaining=timer?.let{TimerStore.remaining(context,it)}?:0;clock=ZonedDateTime.now(ZoneId.of(day?.timezone?:"Asia/Kolkata"));FocusWorkLogs.prompt(context);delay(1000)}}
    LaunchedEffect(clock.toLocalDate(),clock.hour,clock.minute){if(lifecycle.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))AutoFocusScheduler.catchUp(context)}
    LaunchedEffect(today){if(lastToday!=today.toString()){if(selectedIso==lastToday)selectedIso=today.toString();lastToday=today.toString()}}
    LaunchedEffect(drag!=null){while(drag!=null){val y=drag!!.pointerY;if(y>0&&viewportBottom>viewportTop){if(y<viewportTop+48*density)scroll.scrollBy(-10*density)else if(y>viewportBottom-48*density)scroll.scrollBy(10*density)};delay(24)}}
    val latestResume by rememberUpdatedState({
        drag=null
        clock=ZonedDateTime.now(ZoneId.of(day?.timezone?:"Asia/Kolkata"))
        val actual=logicalToday(clock).toString()
        if(actual!=lastToday){if(selectedIso==lastToday)selectedIso=actual;lastToday=actual}
        Reminders.setup(context);AutoFocusScheduler.catchUp(context)
        if(TimerStore.read(context)!=null)TimerStore.action(context,"SHOW")
        scope.launch{refresh(true);if(inbox)refreshInbox()}
        scope.launch{if(FocusWorkLogs.entries(context).any{it.has("body")}&&FocusWorkLogs.syncReady(context)){refresh(true);if(inbox)refreshInbox()}}
    })
    DisposableEffect(lifecycle){val observer=LifecycleEventObserver{_,event->if(event==Lifecycle.Event.ON_RESUME)latestResume() else if(event==Lifecycle.Event.ON_PAUSE)drag=null};lifecycle.lifecycle.addObserver(observer);onDispose{lifecycle.lifecycle.removeObserver(observer)}}
    Scaffold(containerColor=MaterialTheme.colorScheme.background,snackbarHost={SnackbarHost(snackbar)},bottomBar={
        Column{
            timer?.let{s->Surface(color=if(dark)Color(0xFF332A23)else Color(0xFFF2E8D9)){Column{Row(Modifier.fillMaxWidth().padding(horizontal=16.dp,vertical=9.dp),verticalAlignment=Alignment.CenterVertically){
                Icon(Icons.Rounded.HourglassBottom,null,tint=if(dark)Color(0xFFD2A570)else Color(0xFF80502F));Spacer(Modifier.width(10.dp));Column(Modifier.weight(1f)){Text(s.title,maxLines=1,overflow=TextOverflow.Ellipsis,fontWeight=FontWeight.SemiBold);Text("${timerText(remaining)} · ${if(s.running)"Focus" else "Paused"}",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)}
                IconButton(onClick={TimerStore.action(context,"TOGGLE")}){Icon(if(s.running)Icons.Rounded.Pause else Icons.Rounded.PlayArrow,"Pause or resume timer")}
                IconButton(onClick={TimerStore.action(context,"STOP")}){Icon(Icons.Rounded.Close,"Cancel timer")}
                IconButton(onClick={context.startActivity(Intent(context,MainActivity::class.java).putExtra("finish_timer",s.taskId).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP))}){Icon(Icons.Rounded.Check,"Finish timer",tint=if(dark)Color(0xFFD2A570)else Color(0xFF80502F))}
            }
                LinearProgressIndicator(progress={(remaining.toFloat()/s.durationMs.coerceAtLeast(1)).coerceIn(0f,1f)},modifier=Modifier.fillMaxWidth().height(5.dp),color=if(dark)Color(0xFFD2A570)else Color(0xFF80502F),trackColor=if(dark)Color(0xFF4C3C2E)else Color(0xFFDCC7AE))
            }}}
            Surface{Row(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal=20.dp,vertical=8.dp),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically){
                TextButton(onClick={
                    drag=null
                    if(inbox)inbox=false else{todoView=!todoView;viewPrefs.edit().putBoolean("day_todo",todoView).apply()}
                },modifier=Modifier.weight(1f).height(62.dp).semantics{
                    contentDescription=if(inbox)"Return to day" else if(todoView)"Show timeline" else "Show to-do list"
                    stateDescription=if(todoView)"To-do list view" else "Timeline view"
                },contentPadding=PaddingValues(4.dp)){
                    val slashColor=MaterialTheme.colorScheme.primary
                    val slashOutline=MaterialTheme.colorScheme.surface
                    Column(horizontalAlignment=Alignment.CenterHorizontally){Icon(Icons.Rounded.ViewDay,null,modifier=Modifier.size(22.dp).drawWithContent{
                        drawContent()
                        if(todoView){
                            val start=Offset(size.width*.10f,size.height*.10f);val end=Offset(size.width*.90f,size.height*.90f)
                            drawLine(slashOutline,start,end,5.dp.toPx(),androidx.compose.ui.graphics.StrokeCap.Round)
                            drawLine(slashColor,start,end,2.dp.toPx(),androidx.compose.ui.graphics.StrokeCap.Round)
                        }
                    });Text(if(compactNavigation)"Day" else "Timeline",fontSize=12.sp,maxLines=1,overflow=TextOverflow.Ellipsis)}
                }
                FilledIconButton(onClick={closeEditor();recovery=drafts.remove("new");adding=true},modifier=Modifier.size(50.dp),shape=CircleShape){Icon(Icons.Rounded.Add,"Add a task")}
                TextButton(onClick={inbox=true},modifier=Modifier.weight(1f).height(62.dp),contentPadding=PaddingValues(4.dp)){
                    Column(horizontalAlignment=Alignment.CenterHorizontally){Icon(Icons.Rounded.Inbox,"Inbox",modifier=Modifier.size(22.dp));Text(if(compactNavigation)"Inbox" else "Inbox $unfinishedInbox",fontSize=12.sp,maxLines=1,overflow=TextOverflow.Ellipsis)}
                }
                TextButton(onClick={context.startActivity(Intent(context,DashboardActivity::class.java))},modifier=Modifier.weight(1f).height(62.dp),contentPadding=PaddingValues(4.dp)){
                    Column(horizontalAlignment=Alignment.CenterHorizontally){Icon(Icons.Rounded.Dashboard,"Dashboard",modifier=Modifier.size(22.dp));Text(if(compactNavigation)"Dash" else "Dashboard",fontSize=12.sp,maxLines=1,overflow=TextOverflow.Ellipsis)}
                }
            }}
        }
    }){padding->
        Column(Modifier.fillMaxSize().padding(padding)){
            Row(Modifier.fillMaxWidth().padding(start=16.dp,end=4.dp,top=2.dp),verticalAlignment=Alignment.CenterVertically){
                Column(Modifier.weight(1f).then(if(inbox)Modifier else Modifier.clickable{DatePickerDialog(pickerContext(context,dark),{_,y,m,d->selectedIso=LocalDate.of(y,m+1,d).toString()},selected.year,selected.monthValue-1,selected.dayOfMonth).show()})){
                    Text(if(inbox)"Inbox" else (if(selected==today)"Today · " else "")+selected.format(DateTimeFormatter.ofPattern("MMM d")),fontSize=19.sp,fontWeight=FontWeight.SemiBold,maxLines=1,overflow=TextOverflow.Ellipsis)
                    if(!inbox)Text("${currentTasks.count{it.done}} of ${currentTasks.size} complete",fontSize=10.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if(!inbox)TextButton(onClick={selectedIso=today.toString();if(selected==today)jumpNow()},contentPadding=PaddingValues(horizontal=7.dp,vertical=0.dp)){Text(if(selected==today)"Now" else "Today",fontSize=12.sp)}
                IconButton(enabled=drag==null&&editorId==null&&!adding,onClick={scope.launch{refresh(true,false,true);if(inbox)refreshInbox(true)}}){Icon(Icons.Rounded.Refresh,"Refresh day")};IconButton(onClick={settings=true}){Icon(Icons.Rounded.Tune,"Settings")}
            }
            if(!inbox)Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically){
                IconButton(onClick={selectedIso=selected.minusDays(7).toString()},modifier=Modifier.size(30.dp)){Icon(Icons.Rounded.ChevronLeft,"Previous week")}
                val start=selected.minusDays((selected.dayOfWeek.value-1).toLong())
                for(index in 0..6){val d=start.plusDays(index.toLong());val isSelected=d==selected
                    Column(Modifier.weight(1f).semantics{contentDescription=d.format(DateTimeFormatter.ofPattern("EEEE, MMMM d, yyyy"))+(if(isSelected)", selected" else "")}.background(if(isSelected)MaterialTheme.colorScheme.primary else Color.Transparent,RoundedCornerShape(10.dp)).clickable{selectedIso=d.toString()}.padding(vertical=2.dp),horizontalAlignment=Alignment.CenterHorizontally){
                        Text(d.format(DateTimeFormatter.ofPattern("EEEEE")),fontSize=10.sp,color=if(isSelected)MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(d.dayOfMonth.toString(),fontSize=15.sp,fontWeight=FontWeight.Bold,color=if(isSelected)MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface)
                        val hasTasks=if(d==selected)currentTasks.isNotEmpty()else repo.cached(d)?.tasks?.isNotEmpty()==true
                        Box(Modifier.padding(top=3.dp).size(4.dp).background(if(d==today||hasTasks)if(isSelected)MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.primary else Color.Transparent,CircleShape))
                    }
                }
                IconButton(onClick={selectedIso=selected.plusDays(7).toString()},modifier=Modifier.size(30.dp)){Icon(Icons.Rounded.ChevronRight,"Next week")}
            }
            if(!inbox&&currentTasks.isNotEmpty())LinearProgressIndicator(progress={currentTasks.count{it.done}.toFloat()/currentTasks.size},modifier=Modifier.fillMaxWidth().padding(horizontal=20.dp).height(3.dp),trackColor=MaterialTheme.colorScheme.primary.copy(alpha=.10f))
            if(!inbox)WinsPanel(currentTasks,day?.starLimit?:5){reveal(it)}
            if(inbox)InboxOverview(unscheduled,currentTasks,if(selected==today)"Today" else selected.format(DateTimeFormatter.ofPattern("MMM d")),unscheduled.count{isOverdue(it,clock)},inboxFilter){inboxFilter=it}
            if(loading||inbox&&inboxLoading)LinearProgressIndicator(Modifier.fillMaxWidth().height(1.dp))
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
                        selectedIso=selected.plusDays(if(delta.x<0)1 else -1).toString()
                }
            }
            if(inbox){
                val visible=when(inboxFilter){"Overdue"->unscheduled.filter{isOverdue(it,clock)};"Done"->currentTasks.filter{it.done};else->unscheduled.filterNot{it.done}}
                val sections=if(inboxFilter=="Open")listOf("Overdue" to visible.filter{isOverdue(it,clock)},"Unscheduled" to visible.filterNot{isOverdue(it,clock)})else listOf(inboxFilter to visible)
                LazyColumn(Modifier.weight(1f).fillMaxWidth().then(swipe),state=inboxScroll,contentPadding=PaddingValues(bottom=24.dp)){
                    if(visible.isEmpty())item{EmptyState(if(inboxFilter=="Done")"No completed inbox tasks" else "Your ${inboxFilter.lowercase()} list is clear",if(inboxFilter=="Done")"Completed tasks appear here for this day." else "Add an idea. Schedule it when you're ready.")}
                    sections.forEach{(label,rows)->if(rows.isNotEmpty()){
                        item(key="section:$label"){InboxSection(label,rows.size,rows.sumOf{it.minutes})}
                        items(rows,key={it.id}){task->InboxCard(task,dark,!taskBusy(task),{openEditor(task)},{toggleDone(task)},{toggleStar(task)},{schedule(task)},overdue=isOverdue(task,clock))}
                    }}
                }
            }else if(todoView){
                LazyColumn(Modifier.weight(1f).fillMaxWidth().then(swipe),state=todoScroll,contentPadding=PaddingValues(start=12.dp,end=12.dp,top=6.dp,bottom=24.dp),verticalArrangement=Arrangement.spacedBy(5.dp)){
                    if(todoTasks.isEmpty())item{EmptyState("A clear day","Add a task, with or without a time.")}
                    items(todoTasks,key={it.id}){task->DayTodoCard(task,dark,!taskBusy(task),timer?.taskId==task.id,{openEditor(task)},{toggleDone(task)},{toggleStar(task)},{startTimer(task)})}
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
    if(settings)ConnectionSettings(repo,appearance,onAppearance,{settings=false},requestNotification,{
        closeEditor();day=null;backlog=repo.cachedInbox();connectionRevision++;scope.launch{refresh(false)}
    })
    if(adding||editor!=null)PlannerEditor(editor,selected,suggestedDate,suggestedTime,editor?.let{taskBusy(it)}?:false,recovery,::closeEditor,{title,date,time,minutes,notes->
        val original=editor?.let{edit->currentTasks.find{it.id==edit.id}?:edit};val oldId=editorId
        val viewDate=selected
        val pending=original?.copy(title=title,date=date.toString(),time=time,minutes=minutes)
            ?:Task("pending:${UUID.randomUUID()}",title,time,minutes,false,false,false,null,date.toString(),notes,null)
        closeEditor()
        optimistic(original?.let(::mutationKeys)?:setOf(pending.id),{snapshot->
            val without=snapshot.tasks.filterNot{it.id==original?.id}
            snapshot.copy(tasks=without+pending)
        },{
            if(original==null){val id=repo.create(title,date,time,minutes,notes);val source=Day(viewDate.toString(),day?.timezone?:"Asia/Kolkata",listOf(pending))
                val resolved=source.copy(tasks=listOf(pending.copy(id=id)))
                repo.saveSnapshot(source,resolved);backlog=repo.cachedInbox();day=day?.let{projectChanges(it,source,resolved)}
                AutoFocusScheduler.syncChanges(context,resolved.tasks,source.date,source.timezone)}
            else repo.patch(original,JSONObject().put("title",title).put("scheduled_date",date.toString()).put("start_time",time?:JSONObject.NULL).put("estimated_minutes",minutes))
        },onFailure={val saved=EditorValues(title,date,time,minutes,notes);drafts[original?.id?:"new"]=saved
            if(editorId==null&&!adding){recovery=saved;if(original==null)adding=true else{editorId=oldId;editorBackup=original}}
        })
    },{toggleStar(it)},{task->splitTarget=task},{deleteTarget=it},{startTimer(it);closeEditor()},{task->closeEditor();FocusWorkLogs.open(context,task.id)})
    splitTarget?.let{task->AlertDialog(onDismissRequest={splitTarget=null},title={Text("Split remaining work?")},text={Column{
        Text(task.title,fontWeight=FontWeight.SemiBold)
        Text("Two sessions: ${workDuration((task.remainingSeconds+1)/2)} and ${workDuration(task.remainingSeconds/2)}. ${if(task.workedSeconds>0)"The first starts after the worked portion" else "The first keeps its slot"}; the second is unscheduled in Inbox.")
        if(task.workedSeconds>0)Text("Your ${workDuration(task.workedSeconds)} already worked stays recorded in a completed session.")
    }},confirmButton={TextButton(enabled=!taskBusy(task),onClick={
        splitTarget=null
        val keys=mutationKeys(task)
        if(mutations.begin(keys)){
            val snapshot=day;val ticket=snapshot?.let{it to it}
            ticket?.let{pendingWrites.add(it)};closeEditor()
            scope.launch{var message:String?=null
                try{repo.split(task)}catch(e:Exception){message=e.message?:"Split couldn't be saved."}
                finally{mutations.end(keys);ticket?.let{pendingWrites.remove(it)};reconcile()}
                message?.let{scope.launch{snackbar.showSnackbar(it)}}
            }
        }
    }){Text("Split")}},dismissButton={TextButton(onClick={splitTarget=null}){Text("Cancel")}})}
    deleteTarget?.let{task->AlertDialog(onDismissRequest={deleteTarget=null},title={Text(if(task.habit)"Skip this occurrence?" else "Delete this task?")},text={Text(task.title)},confirmButton={TextButton(enabled=!taskBusy(task),onClick={deleteTarget=null;closeEditor();optimistic(mutationKeys(task),{it.copy(tasks=it.tasks.filterNot{row->row.id==task.id})},{repo.delete(task)})}){Text(if(task.habit)"Skip" else "Delete")}},dismissButton={TextButton(onClick={deleteTarget=null}){Text("Cancel")}})}
    replacement?.let{task->AlertDialog(onDismissRequest={replacement=null},title={Text("Switch focus?")},text={Text("This ends the timer for ${timer?.title}. Its task stays as it is.")},confirmButton={TextButton(onClick={TimerStore.start(context,task);replacement=null;requestNotification()}){Text("Start new timer")}},dismissButton={TextButton(onClick={replacement=null}){Text("Keep current")}})}
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
