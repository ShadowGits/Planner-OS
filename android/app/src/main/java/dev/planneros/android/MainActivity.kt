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
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.platform.LocalContext
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
        super.onCreate(savedInstanceState);enableEdgeToEdge();finishId=intent.getStringExtra("finish_timer")
        setContent{
            val prefs=remember{getSharedPreferences("appearance",MODE_PRIVATE)}
            var appearance by remember{mutableStateOf(prefs.getString("theme","system")?:"system")}
            val dark=when(appearance){"dark"->true;"light"->false;else->isSystemInDarkTheme()}
            SideEffect{
                WindowInsetsControllerCompat(window,window.decorView).apply{
                    isAppearanceLightStatusBars=!dark;isAppearanceLightNavigationBars=!dark
                }
            }
            val colors=if(dark)darkColorScheme(primary=Color(0xFFF286A8),onPrimary=Color(0xFF451027),background=Color(0xFF17181C),surface=Color(0xFF202127),onSurface=Color(0xFFF7F2F5),onSurfaceVariant=Color(0xFFCAC0C7))
                else lightColorScheme(primary=Wine,onPrimary=Color.White,background=Color.White,surface=Color.White,onSurface=Color(0xFF292A35),onSurfaceVariant=Color(0xFF77707A),secondary=Color(0xFFB45172))
            MaterialTheme(colorScheme=colors){PlannerScreen(finishId,{finishId=null},{if(Build.VERSION.SDK_INT>=33)permission.launch(Manifest.permission.POST_NOTIFICATIONS)},dark,appearance,{appearance=it;prefs.edit().putString("theme",it).apply()})}
        }
        Reminders.setup(this)
        if(TimerStore.read(this)!=null)TimerStore.action(this,"SHOW")
    }
    override fun onNewIntent(intent:Intent){super.onNewIntent(intent);setIntent(intent);finishId=intent.getStringExtra("finish_timer")}
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlannerScreen(finishId:String?,finishHandled:()->Unit,requestNotification:()->Unit,dark:Boolean,appearance:String,onAppearance:(String)->Unit){
    val context=LocalContext.current;val repo=remember{PlannerRepository(context)}
    val scope=rememberCoroutineScope();val snackbar=remember{SnackbarHostState()};val density=LocalDensity.current.density
    var selectedIso by rememberSaveable{mutableStateOf(logicalToday(ZonedDateTime.now(ZoneId.of("Asia/Kolkata"))).toString())}
    val selected=LocalDate.parse(selectedIso)
    var day by remember{mutableStateOf<Day?>(repo.cached(selected))}
    var loading by remember{mutableStateOf(false)};var busy by remember{mutableStateOf(false)};var error by remember{mutableStateOf<String?>(null)}
    var requestSerial by remember{mutableIntStateOf(0)};var connectionRevision by remember{mutableIntStateOf(0)}
    var settings by remember{mutableStateOf(!repo.config.configured)}
    var editorId by rememberSaveable{mutableStateOf<String?>(null)};var editorBackup by remember{mutableStateOf<Task?>(null)}
    var recovery by remember{mutableStateOf<EditorValues?>(null)}
    var adding by rememberSaveable{mutableStateOf(false)};var suggestedDate by rememberSaveable{mutableStateOf<String?>(null)};var suggestedTime by rememberSaveable{mutableStateOf<String?>(null)}
    var inbox by rememberSaveable{mutableStateOf(false)};var timer by remember{mutableStateOf(TimerStore.read(context))};var remaining by remember{mutableLongStateOf(0L)}
    var replacement by remember{mutableStateOf<Task?>(null)};var deleteTarget by remember{mutableStateOf<Task?>(null)}
    val scroll=rememberScrollState();val inboxScroll=androidx.compose.foundation.lazy.rememberLazyListState()
    var drag by remember{mutableStateOf<DragState?>(null)};var viewportTop by remember{mutableFloatStateOf(0f)};var viewportBottom by remember{mutableFloatStateOf(0f)}
    var clock by remember{mutableStateOf(ZonedDateTime.now(ZoneId.of(day?.timezone?:"Asia/Kolkata")))}
    val today=logicalToday(clock);val nowMinute=logicalNowMinute(clock)
    var lastToday by rememberSaveable{mutableStateOf(today.toString())}
    val currentTasks=day?.takeIf{it.date==selectedIso}?.tasks.orEmpty()
    val timed=currentTasks.filter{it.time!=null}.sortedBy{it.clockMinutes}
    val unscheduled=currentTasks.filter{it.time==null}.sortedWith(compareByDescending<Task>{it.starred}.thenBy{it.done}.thenBy{it.title})
    val unfinishedInbox=unscheduled.count{!it.done}
    val editor=editorId?.let{id->currentTasks.find{it.id==id}?:editorBackup?.takeIf{it.id==id}}
    fun closeEditor(){adding=false;editorId=null;editorBackup=null;suggestedDate=null;suggestedTime=null;recovery=null}
    fun openEditor(task:Task){if(busy||task.id.startsWith("pending:"))return;drag=null;requestSerial++;loading=false;recovery=null;adding=false;editorId=task.id;editorBackup=task;suggestedDate=null;suggestedTime=null}
    suspend fun refresh(preserve:Boolean=true,allowBusy:Boolean=false){
        if(drag!=null||editorId!=null||adding||(busy&&!allowBusy))return
        if(!repo.config.configured){settings=true;return}
        val date=selected;val serial=++requestSerial;val generation=repo.config.generation
        loading=true;error=null
        if(!preserve||day?.date!=date.toString())day=repo.cached(date)
        try{
            val fresh=repo.day(date)
            if(selectedIso==date.toString()&&serial==requestSerial&&generation==repo.config.generation&&drag==null&&(!busy||allowBusy)&&editorId==null&&!adding){
                day=fresh;clock=ZonedDateTime.now(ZoneId.of(fresh.timezone))
                if(date==logicalToday(clock))Reminders.schedule(context,fresh)
                TimerStore.read(context)?.let{active->fresh.tasks.find{it.id==active.taskId}?.let{TimerStore.refresh(context,it)}}
            }
        }catch(cancel:CancellationException){throw cancel}catch(e:Exception){
            if(selectedIso==date.toString()&&serial==requestSerial&&generation==repo.config.generation){
                error=if(e is PlannerHttpException)e.message else if(e is java.io.IOException)"Your saved day is here. Reconnect to refresh and save changes." else e.message?:"Couldn't refresh this day."
                if(e is PlannerHttpException&&e.statusCode in listOf(401,403))settings=true
            }
        }finally{if(serial==requestSerial)loading=false}
    }
    fun optimistic(change:(Day)->Day,write:suspend()->Unit,onSuccess:()->Unit={},onFailure:()->Unit={}){
        val before=day?.takeIf{it.date==selectedIso}?:return
        if(busy)return
        requestSerial++;loading=false;day=change(before);busy=true;error=null
        scope.launch{
            try{write();onSuccess();refresh(true,true)}catch(cancel:CancellationException){day=rollbackForDate(before,day);throw cancel}catch(e:Exception){day=rollbackForDate(before,day);onFailure();snackbar.showSnackbar(e.message?:"Change couldn't be saved; restored the previous plan.")}
            finally{busy=false;if(day?.date!=selectedIso)refresh(false)}
        }
    }
    fun toggleDone(task:Task){optimistic({replaceTask(it,task.copy(done=!task.done))},{repo.patch(task,JSONObject().put("done",!task.done))})}
    fun toggleStar(task:Task){
        // The backend counts actual scheduled dates, including overnight copies.
        // It owns the limit; a refused sixth rolls back this optimistic state.
        optimistic({replaceTask(it,task.copy(starred=!task.starred))},{repo.patch(task,JSONObject().put("starred",!task.starred))},onSuccess={editorBackup=editorBackup?.takeIf{it.id==task.id}?.copy(starred=!task.starred)?:editorBackup})
    }
    fun startTimer(task:Task){
        if(busy||task.id.startsWith("pending:"))return
        if(timer!=null&&timer?.taskId!=task.id){replacement=task;return}
        requestNotification();TimerStore.start(context,task)
        if(!Settings.canDrawOverlays(context))scope.launch{snackbar.showSnackbar("Timer started. Enable floating timer in Settings to see it across apps.")}
    }
    fun schedule(task:Task){
        val slot=nextFreeSlot(selected,today,nowMinute,task.minutes,taskBlocks(currentTasks))
        openEditor(task);suggestedDate=slot.date.toString();suggestedTime=slot.clock
    }
    fun reveal(task:Task){
        if(task.time==null){inbox=true;scope.launch{delay(80);val index=unscheduled.indexOfFirst{it.id==task.id};if(index>=0)inboxScroll.animateScrollToItem(index)}}
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
        val shown=visibleMinute(selected,target)
        optimistic({snapshot->if(shown==null)snapshot.copy(tasks=snapshot.tasks.filterNot{it.id==task.id})else replaceTask(snapshot,task.copy(time="%02d:%02d".format(shown/60,shown%60),date=target.date.toString()))},
            {repo.patch(task,JSONObject().put("scheduled_date",target.date.toString()).put("start_time",target.clock))})
    }
    LaunchedEffect(selectedIso,connectionRevision){
        drag=null;scroll.scrollTo(0);refresh(false)
        if(repo.config.configured){val generation=repo.config.generation
            for(offset in -3..3){if(offset==0)continue;launch{try{if(generation==repo.config.generation)repo.day(selected.plusDays(offset.toLong()))}catch(_:Exception){}}}
        }
    }
    LaunchedEffect(selectedIso,connectionRevision){while(true){delay(60*60*1000L);refresh(true)}}
    LaunchedEffect(Unit){while(true){timer=TimerStore.read(context);remaining=timer?.let{TimerStore.remaining(context,it)}?:0;clock=ZonedDateTime.now(ZoneId.of(day?.timezone?:"Asia/Kolkata"));delay(1000)}}
    LaunchedEffect(today){if(lastToday!=today.toString()){if(selectedIso==lastToday)selectedIso=today.toString();lastToday=today.toString()}}
    LaunchedEffect(drag!=null){while(drag!=null){val y=drag!!.pointerY;if(y>0&&viewportBottom>viewportTop){if(y<viewportTop+48*density)scroll.scrollBy(-10*density)else if(y>viewportBottom-48*density)scroll.scrollBy(10*density)};delay(24)}}
    val lifecycle=LocalLifecycleOwner.current
    val latestResume by rememberUpdatedState({
        drag=null
        clock=ZonedDateTime.now(ZoneId.of(day?.timezone?:"Asia/Kolkata"))
        val actual=logicalToday(clock).toString()
        if(actual!=lastToday){if(selectedIso==lastToday)selectedIso=actual;lastToday=actual}
        Reminders.setup(context)
        if(TimerStore.read(context)!=null)TimerStore.action(context,"SHOW")
        if(!busy)scope.launch{refresh(true)}
    })
    DisposableEffect(lifecycle){val observer=LifecycleEventObserver{_,event->if(event==Lifecycle.Event.ON_RESUME)latestResume() else if(event==Lifecycle.Event.ON_PAUSE)drag=null};lifecycle.lifecycle.addObserver(observer);onDispose{lifecycle.lifecycle.removeObserver(observer)}}
    Scaffold(containerColor=MaterialTheme.colorScheme.background,snackbarHost={SnackbarHost(snackbar)},bottomBar={
        Column{
            timer?.let{s->Surface(color=MaterialTheme.colorScheme.primary.copy(alpha=.08f)){Row(Modifier.fillMaxWidth().padding(horizontal=16.dp,vertical=9.dp),verticalAlignment=Alignment.CenterVertically){
                Icon(Icons.Rounded.HourglassBottom,null,tint=MaterialTheme.colorScheme.primary);Spacer(Modifier.width(10.dp));Column(Modifier.weight(1f)){Text(s.title,maxLines=1,overflow=TextOverflow.Ellipsis,fontWeight=FontWeight.SemiBold);Text("${timerText(remaining)} · ${if(s.running)"Focus" else "Paused"}",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)}
                IconButton(onClick={TimerStore.action(context,"TOGGLE")}){Icon(if(s.running)Icons.Rounded.Pause else Icons.Rounded.PlayArrow,"Pause or resume timer")}
                IconButton(onClick={context.startActivity(Intent(context,MainActivity::class.java).putExtra("finish_timer",s.taskId).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP))}){Icon(Icons.Rounded.Check,"Finish timer",tint=MaterialTheme.colorScheme.primary)}
            }}}
            Surface{Row(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal=20.dp,vertical=8.dp),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically){
                TextButton(onClick={inbox=false},modifier=Modifier.weight(1f).height(62.dp),contentPadding=PaddingValues(4.dp)){
                    Column(horizontalAlignment=Alignment.CenterHorizontally){Icon(Icons.Rounded.ViewDay,null,modifier=Modifier.size(22.dp));Text("Timeline",fontSize=12.sp,maxLines=1,overflow=TextOverflow.Ellipsis)}
                }
                FilledIconButton(enabled=!busy,onClick={closeEditor();adding=true},modifier=Modifier.size(50.dp),shape=CircleShape){Icon(Icons.Rounded.Add,"Add a task")}
                TextButton(onClick={inbox=true},modifier=Modifier.weight(1f).height(62.dp),contentPadding=PaddingValues(4.dp)){
                    Column(horizontalAlignment=Alignment.CenterHorizontally){Icon(Icons.Rounded.Inbox,null,modifier=Modifier.size(22.dp));Text("Inbox $unfinishedInbox",fontSize=12.sp,maxLines=1,overflow=TextOverflow.Ellipsis)}
                }
            }}
        }
    }){padding->
        Column(Modifier.fillMaxSize().padding(padding)){
            Row(Modifier.fillMaxWidth().padding(start=20.dp,end=8.dp,top=9.dp),verticalAlignment=Alignment.CenterVertically){
                Column(Modifier.weight(1f).clickable{DatePickerDialog(pickerContext(context,dark),{_,y,m,d->selectedIso=LocalDate.of(y,m+1,d).toString()},selected.year,selected.monthValue-1,selected.dayOfMonth).show()}){
                    Text(when(selected){today->"TODAY";today.minusDays(1)->"YESTERDAY";today.plusDays(1)->"TOMORROW";else->selected.dayOfWeek.name},fontSize=10.sp,letterSpacing=1.5.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,fontWeight=FontWeight.Bold)
                    Text(selected.format(DateTimeFormatter.ofPattern("MMMM d")),fontSize=29.sp,fontWeight=FontWeight.Bold)
                }
                IconButton(enabled=!busy&&drag==null&&editorId==null&&!adding,onClick={scope.launch{refresh(true)}}){Icon(Icons.Rounded.Refresh,"Refresh day")};IconButton(onClick={settings=true}){Icon(Icons.Rounded.Tune,"Settings")}
            }
            Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically){
                IconButton(onClick={selectedIso=selected.minusDays(7).toString()},modifier=Modifier.size(30.dp)){Icon(Icons.Rounded.ChevronLeft,"Previous week")}
                val start=selected.minusDays((selected.dayOfWeek.value-1).toLong())
                for(index in 0..6){val d=start.plusDays(index.toLong());val isSelected=d==selected
                    Column(Modifier.weight(1f).semantics{contentDescription=d.format(DateTimeFormatter.ofPattern("EEEE, MMMM d, yyyy"))+(if(isSelected)", selected" else "")}.background(if(isSelected)MaterialTheme.colorScheme.primary else Color.Transparent,RoundedCornerShape(16.dp)).clickable{selectedIso=d.toString()}.padding(vertical=8.dp),horizontalAlignment=Alignment.CenterHorizontally){
                        Text(d.format(DateTimeFormatter.ofPattern("EEEEE")),fontSize=10.sp,color=if(isSelected)MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(d.dayOfMonth.toString(),fontSize=15.sp,fontWeight=FontWeight.Bold,color=if(isSelected)MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface)
                        val hasTasks=if(d==selected)currentTasks.isNotEmpty()else repo.cached(d)?.tasks?.isNotEmpty()==true
                        Box(Modifier.padding(top=3.dp).size(4.dp).background(if(d==today||hasTasks)if(isSelected)MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.primary else Color.Transparent,CircleShape))
                    }
                }
                IconButton(onClick={selectedIso=selected.plusDays(7).toString()},modifier=Modifier.size(30.dp)){Icon(Icons.Rounded.ChevronRight,"Next week")}
            }
            Row(Modifier.fillMaxWidth().padding(horizontal=20.dp),verticalAlignment=Alignment.CenterVertically){
                Text("${currentTasks.count{it.done}} of ${currentTasks.size} complete",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.weight(1f))
                TextButton(onClick={selectedIso=today.toString();if(selected==today)jumpNow()},contentPadding=PaddingValues(horizontal=7.dp,vertical=0.dp)){Text(if(selected==today)"Now" else "Today",fontSize=12.sp)}
            }
            if(currentTasks.isNotEmpty())LinearProgressIndicator(progress={currentTasks.count{it.done}.toFloat()/currentTasks.size},modifier=Modifier.fillMaxWidth().padding(horizontal=20.dp).height(3.dp),trackColor=MaterialTheme.colorScheme.primary.copy(alpha=.10f))
            WinsPanel(currentTasks,day?.starLimit?:5){reveal(it)}
            if(loading)LinearProgressIndicator(Modifier.fillMaxWidth().height(1.dp))
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
                LazyColumn(Modifier.weight(1f).fillMaxWidth().then(swipe),state=inboxScroll,contentPadding=PaddingValues(bottom=24.dp)){
                    if(unscheduled.isEmpty())item{EmptyState("Your inbox is clear","Add an idea. Schedule it when you're ready.")}
                    items(unscheduled,key={it.id}){task->InboxCard(task,dark,!busy,{openEditor(task)},{toggleDone(task)},{toggleStar(task)},{schedule(task)})}
                }
            }else if(timed.isEmpty()){
                Box(Modifier.weight(1f).fillMaxWidth().then(swipe),contentAlignment=Alignment.Center){EmptyState("A little space to breathe",if(unscheduled.isEmpty())"Add your first block for this day." else "${unfinishedInbox} inbox items are ready to schedule.")}
            }else{
                ProportionalTimeline(timed,selected,selected==today,nowMinute,timer?.taskId,dark,!busy,scroll,dragPreview,
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
        closeEditor();day=null;connectionRevision++;scope.launch{refresh(false)}
    })
    if(adding||editor!=null)PlannerEditor(editor,selected,suggestedDate,suggestedTime,busy,recovery,::closeEditor,{title,date,time,minutes,notes->
        val original=editor?.let{edit->currentTasks.find{it.id==edit.id}?:edit};val oldId=editorId
        val viewDate=selected;val slot=time?.split(":")?.let{ScheduleSlot(date,it[0].toInt()*60+it[1].toInt())}
        val shown=slot?.let{visibleMinute(viewDate,it)}
        val pending=original?.copy(title=title,date=date.toString(),time=shown?.let{"%02d:%02d".format(it/60,it%60)},minutes=minutes)
            ?:Task("pending:${UUID.randomUUID()}",title,shown?.let{"%02d:%02d".format(it/60,it%60)},minutes,false,false,false,null,date.toString(),notes,null)
        closeEditor()
        optimistic({snapshot->
            val visible=if(time==null)date==viewDate else shown!=null
            val without=snapshot.tasks.filterNot{it.id==original?.id}
            snapshot.copy(tasks=if(visible)without+pending else without)
        },{
            if(original==null){val id=repo.create(title,date,time,minutes,notes);if(day?.date==viewDate.toString())day=day?.copy(tasks=day!!.tasks.map{if(it.id==pending.id)it.copy(id=id)else it})}
            else repo.patch(original,JSONObject().put("title",title).put("scheduled_date",date.toString()).put("start_time",time?:JSONObject.NULL).put("estimated_minutes",minutes))
        },onFailure={recovery=EditorValues(title,date,time,minutes,notes);if(original==null)adding=true else{editorId=oldId;editorBackup=original}})
    },{toggleStar(it)},{task->
        if(!busy){busy=true;closeEditor();scope.launch{try{repo.split(task,selected);refresh(true,true)}catch(e:Exception){snackbar.showSnackbar(e.message?:"Split couldn't be saved.");refresh(true,true)}finally{busy=false}}}
    },{deleteTarget=it},{startTimer(it);closeEditor()})
    deleteTarget?.let{task->AlertDialog(onDismissRequest={deleteTarget=null},title={Text(if(task.habit)"Skip this occurrence?" else "Delete this task?")},text={Text(task.title)},confirmButton={TextButton(enabled=!busy,onClick={deleteTarget=null;closeEditor();optimistic({it.copy(tasks=it.tasks.filterNot{row->row.id==task.id})},{repo.delete(task)})}){Text(if(task.habit)"Skip" else "Delete")}},dismissButton={TextButton(onClick={deleteTarget=null}){Text("Cancel")}})}
    replacement?.let{task->AlertDialog(onDismissRequest={replacement=null},title={Text("Switch focus?")},text={Text("This ends the timer for ${timer?.title}. Its task stays as it is.")},confirmButton={TextButton(onClick={TimerStore.start(context,task);replacement=null;requestNotification()}){Text("Start new timer")}},dismissButton={TextButton(onClick={replacement=null}){Text("Keep current")}})}
    if(finishId!=null){val s=TimerStore.read(context)
        if(s==null||s.taskId!=finishId)LaunchedEffect(finishId){finishHandled()}
        else AlertDialog(onDismissRequest=finishHandled,title={Text("Finish ${s.title}?")},text={Text("${timerText(TimerStore.remaining(context,s))} remaining. Mark the task complete, or just end this timer.")},confirmButton={TextButton(enabled=!busy,onClick={busy=true;scope.launch{try{repo.request("PATCH","/v2/day/tasks/${java.net.URLEncoder.encode(s.taskId,"UTF-8")}",JSONObject().put("done",true));if(TimerStore.read(context)?.taskId==s.taskId)TimerStore.action(context,"STOP");finishHandled();refresh(true,true)}catch(e:Exception){snackbar.showSnackbar(e.message?:"Couldn't mark done. Your timer is still available.")}finally{busy=false}}}){Text("Mark done")}},dismissButton={Row{TextButton(onClick={TimerStore.action(context,"STOP");finishHandled()}){Text("End timer")};TextButton(onClick=finishHandled){Text("Continue")}}})
    }
}

@Composable internal fun EmptyState(title:String,message:String){Column(Modifier.fillMaxWidth().padding(vertical=42.dp,horizontal=24.dp),horizontalAlignment=Alignment.CenterHorizontally){Icon(Icons.Rounded.WbSunny,null,tint=MaterialTheme.colorScheme.primary,modifier=Modifier.size(38.dp));Spacer(Modifier.height(14.dp));Text(title,fontSize=21.sp,fontWeight=FontWeight.SemiBold);Text(message,fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=9.dp))}}
