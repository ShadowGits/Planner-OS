package dev.planneros.android

import android.Manifest
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
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val Coral=Color(0xFF8C63E8)
private val Ink=Color(0xFF292A35)
private val Paper=Color.White
private val Muted=Color(0xFF767887)
private val hues=listOf(Color(0xFFFFDCE9),Color(0xFFE7DDFF),Color(0xFFD8F3E8),Color(0xFFFFF0C7),Color(0xFFDDEFFF),Color(0xFFFFE2CF),Color(0xFFD7F3F8))

class MainActivity:ComponentActivity(){
    private var finishId by mutableStateOf<String?>(null)
    private val permission=registerForActivityResult(ActivityResultContracts.RequestPermission()){Reminders.setup(this)}
    override fun onCreate(savedInstanceState:Bundle?){super.onCreate(savedInstanceState);enableEdgeToEdge();finishId=intent.getStringExtra("finish_timer")
        setContent{MaterialTheme(colorScheme=lightColorScheme(primary=Coral,onPrimary=Color.White,background=Paper,surface=Paper,onBackground=Ink,onSurface=Ink,secondary=Color(0xFF8A7FA2))){PlannerScreen(finishId,{finishId=null},{if(Build.VERSION.SDK_INT>=33)permission.launch(Manifest.permission.POST_NOTIFICATIONS)})}}
        Reminders.setup(this)
        // User returns after OS reclaim or reboot: restore stored focus only while the activity is visible.
        if(TimerStore.read(this)!=null)TimerStore.action(this,"SHOW")
    }
    override fun onNewIntent(intent:Intent){super.onNewIntent(intent);finishId=intent.getStringExtra("finish_timer")}
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlannerScreen(finishId:String?,finishHandled:()->Unit,requestNotification:()->Unit){
    val context=androidx.compose.ui.platform.LocalContext.current
    val repo=remember{PlannerRepository(context)}
    val scope=rememberCoroutineScope();val snackbar=remember{SnackbarHostState()}
    var selected by remember{mutableStateOf(LocalDate.now(ZoneId.of("Asia/Kolkata")))}
    var day by remember{mutableStateOf<Day?>(null)}
    var loading by remember{mutableStateOf(false)};var busy by remember{mutableStateOf(false)}
    var error by remember{mutableStateOf<String?>(null)}
    var settings by remember{mutableStateOf(!repo.config.configured)}
    var editor by remember{mutableStateOf<Task?>(null)};var adding by remember{mutableStateOf(false)}
    var inbox by remember{mutableStateOf(false)};var timer by remember{mutableStateOf(TimerStore.read(context))}
    var remaining by remember{mutableStateOf(0L)};var replacement by remember{mutableStateOf<Task?>(null)}
    var deleteTarget by remember{mutableStateOf<Task?>(null)}
    var initialTime by remember{mutableStateOf<String?>(null)}
    val currentTasks=day?.tasks.orEmpty()
    val today=LocalDate.now(runCatching{ZoneId.of(day?.timezone?:"Asia/Kolkata")}.getOrDefault(ZoneId.of("Asia/Kolkata")))
    suspend fun refresh(){
        if(!repo.config.configured){settings=true;return}
        loading=true;error=null
        day=repo.cached(selected)
        try{day=repo.day(selected);if(selected==today)Reminders.schedule(context,day!!)}catch(e:Exception){error=e.message?:"Unable to connect. Showing saved day."}finally{loading=false}
    }
    fun operation(block:suspend()->Unit){if(busy)return;busy=true;scope.launch{try{block();refresh()}catch(e:Exception){snackbar.showSnackbar(e.message?:"Could not save changes.")}finally{busy=false}}}
    fun startTimer(task:Task){
        if(timer!=null&&timer?.taskId!=task.id){replacement=task;return}
        requestNotification();TimerStore.start(context,task)
        if(!Settings.canDrawOverlays(context))scope.launch{snackbar.showSnackbar("Timer started. Enable floating timer in Settings to see it across apps.")}
    }
    LaunchedEffect(selected){refresh()}
    LaunchedEffect(Unit){while(true){timer=TimerStore.read(context);remaining=timer?.let{TimerStore.remaining(context,it)}?:0;delay(500)}}
    val tasks=if(inbox)currentTasks.filter{it.time==null}else currentTasks.filter{it.time!=null}.sortedBy{it.clockMinutes}
    Scaffold(containerColor=Paper,snackbarHost={SnackbarHost(snackbar)},bottomBar={
        Column{
            timer?.let{s->Surface(color=Color(0xFFF3EEFF),shadowElevation=3.dp){Row(Modifier.fillMaxWidth().padding(horizontal=18.dp,vertical=12.dp),verticalAlignment=Alignment.CenterVertically){
                Icon(Icons.Rounded.HourglassBottom,null,tint=Coral);Spacer(Modifier.width(12.dp));Column(Modifier.weight(1f)){Text(s.title,color=Ink,maxLines=1,overflow=TextOverflow.Ellipsis,fontWeight=FontWeight.SemiBold);Text("${timerText(remaining)} · ${if(s.running) "Focus" else "Paused"}",color=Color(0xFF79718B),fontSize=13.sp)}
                IconButton(onClick={TimerStore.action(context,"TOGGLE")}){Icon(if(s.running)Icons.Rounded.Pause else Icons.Rounded.PlayArrow,"Pause or resume",tint=Coral)}
                IconButton(onClick={(context as? MainActivity)?.startActivity(Intent(context,MainActivity::class.java).putExtra("finish_timer",s.taskId).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP))}){Icon(Icons.Rounded.Check,"Finish timer",tint=Coral)}
            }}}
            Surface(color=Paper){Row(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal=24.dp,vertical=10.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween){
                TextButton(onClick={inbox=false}){Icon(Icons.Rounded.ViewDay,null);Spacer(Modifier.width(8.dp));Text("Timeline",color=if(!inbox)Coral else Muted)}
                FilledIconButton(onClick={initialTime=null;adding=true},modifier=Modifier.size(54.dp),shape=CircleShape){Icon(Icons.Rounded.Add,"Add a task",Modifier.size(28.dp))}
                TextButton(onClick={inbox=true}){Icon(Icons.Rounded.Inbox,null);Spacer(Modifier.width(8.dp));Text("Inbox ${currentTasks.count{it.time==null}}",color=if(inbox)Coral else Muted)}
            }}
        }
    }){padding->
        Column(Modifier.fillMaxSize().padding(padding)){
            Row(Modifier.fillMaxWidth().padding(start=24.dp,end=12.dp,top=12.dp),verticalAlignment=Alignment.CenterVertically){Column(Modifier.weight(1f)){
                Text(if(selected==today)"TODAY" else selected.dayOfWeek.name,color=Muted,fontSize=11.sp,letterSpacing=2.sp,fontWeight=FontWeight.Bold)
                Text(selected.format(DateTimeFormatter.ofPattern("MMMM d")),fontSize=32.sp,fontWeight=FontWeight.Bold,letterSpacing=(-1).sp)
            };IconButton(onClick={scope.launch{refresh()}}){Icon(Icons.Rounded.Refresh,"Refresh day",tint=Muted)};IconButton(onClick={settings=true}){Icon(Icons.Rounded.Tune,"Settings",tint=Muted)}}
            Row(Modifier.fillMaxWidth().padding(horizontal=12.dp,vertical=12.dp),horizontalArrangement=Arrangement.SpaceEvenly){
                val weekStart=selected.minusDays((selected.dayOfWeek.value-1).toLong())
                for(n in 0..6){val d=weekStart.plusDays(n.toLong());Column(Modifier.width(44.dp).clipShape(RoundedCornerShape(18.dp)).background(if(d==selected)Coral else Color.Transparent).clickable{selected=d}.padding(vertical=10.dp),horizontalAlignment=Alignment.CenterHorizontally){
                    Text(d.format(DateTimeFormatter.ofPattern("EEEEE")),color=if(d==selected)Color.White else Muted,fontSize=11.sp)
                    Spacer(Modifier.height(4.dp));Text(d.dayOfMonth.toString(),color=if(d==selected)Color.White else Ink,fontSize=17.sp,fontWeight=FontWeight.Bold)
                    Spacer(Modifier.height(4.dp));Box(Modifier.size(4.dp).background(if(d==today)if(d==selected)Color.White else Coral else Color.Transparent,CircleShape))
                }}
            }
            Row(Modifier.fillMaxWidth().padding(horizontal=24.dp,vertical=2.dp),verticalAlignment=Alignment.CenterVertically){
                val done=currentTasks.count{it.done};val stars=currentTasks.filter{it.starred}
                Text(if(inbox) "Make room for what matters" else "$done of ${currentTasks.size} complete",fontSize=13.sp,color=Muted,modifier=Modifier.weight(1f))
                if(stars.isNotEmpty()){Icon(Icons.Rounded.Star,null,tint=Coral,modifier=Modifier.size(15.dp));Text(" ${stars.count{it.done}}/${stars.size}",fontSize=13.sp,color=Muted)}
                if(selected!=today)TextButton(onClick={selected=today}){Text("Today")}
            }
            if(loading)LinearProgressIndicator(Modifier.fillMaxWidth().height(2.dp))
            error?.let{Surface(color=Color(0xFFFFEDE3),modifier=Modifier.fillMaxWidth().padding(horizontal=18.dp,vertical=8.dp),shape=RoundedCornerShape(12.dp)){Text((if(day?.cached==true)"Offline · " else "")+it,Modifier.padding(12.dp),fontSize=12.sp,color=Ink)}}
            if(tasks.isEmpty()&&!loading){Column(Modifier.fillMaxWidth().weight(1f),horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.Center){
                Icon(if(inbox)Icons.Rounded.Inbox else Icons.Rounded.WbSunny,null,tint=Coral,modifier=Modifier.size(48.dp));Spacer(Modifier.height(16.dp));Text(if(inbox)"Your inbox is clear" else "A little space to breathe",fontSize=21.sp,fontWeight=FontWeight.SemiBold);Text(if(inbox)"Add an idea. Schedule it when you're ready." else "Add your first block for this day.",color=Muted,fontSize=13.sp,modifier=Modifier.padding(12.dp))
            }}else{
                var drag=0f
                LazyColumn(Modifier.weight(1f).fillMaxWidth().pointerInput(selected){detectHorizontalDragGestures(onDragStart={drag=0f},onHorizontalDrag={_,amount->drag+=amount},onDragEnd={if(kotlin.math.abs(drag)>100)selected=selected.plusDays(if(drag<0)1 else -1)})},contentPadding=PaddingValues(top=16.dp,bottom=28.dp)){
                    items(tasks,key={it.id}){task->
                        val index=tasks.indexOf(task)
                        if(!inbox){val end=tasks.take(index).maxOfOrNull{it.clockMinutes+it.minutes}?:task.clockMinutes
                            if(task.clockMinutes>end){GapRow(task.clockMinutes-end){initialTime=clockText(end);adding=true}}}
                        TaskRow(task,inbox,timer?.taskId==task.id,{editor=task},{operation{repo.patch(task,JSONObject().put("done",!task.done))}},{startTimer(task)})
                    }
                    if(!inbox)item{Row(Modifier.padding(start=31.dp,top=14.dp)){Box(Modifier.size(8.dp).background(Coral,CircleShape));Text("   A day, thoughtfully planned",fontSize=12.sp,color=Muted)}}
                }
            }
        }
    }
    if(settings)SettingsDialog(repo,{settings=false},{requestNotification()},{scope.launch{day=null;refresh()}})
    if(adding||editor!=null)TaskEditor(editor,selected,initialTime,busy,{adding=false;editor=null;initialTime=null},{title,date,time,minutes,notes->
        val edit=editor
        operation{if(edit==null)repo.create(title,date,time,minutes,notes)else repo.patch(edit,JSONObject().put("title",title).put("scheduled_date",date.toString()).put("start_time",time?:JSONObject.NULL).put("estimated_minutes",minutes));adding=false;editor=null}
    },{t->operation{repo.patch(t,JSONObject().put("starred",!t.starred));editor=null}}, {t->operation{repo.split(t,selected);editor=null}}, {t->deleteTarget=t}, {t->startTimer(t);editor=null})
    replacement?.let{task->AlertDialog(onDismissRequest={replacement=null},title={Text("Switch focus?")},text={Text("This ends the timer for ${timer?.title}. Its task stays as it is.")},confirmButton={TextButton(onClick={TimerStore.start(context,task);replacement=null;requestNotification()}){Text("Start ${task.title.take(20)}")}},dismissButton={TextButton(onClick={replacement=null}){Text("Keep current")}})}
    deleteTarget?.let{task->AlertDialog(onDismissRequest={deleteTarget=null},title={Text(if(task.habit)"Skip this occurrence?" else "Delete this task?")},text={Text(task.title)},confirmButton={TextButton(onClick={operation{repo.delete(task);editor=null;deleteTarget=null}}){Text("Delete",color=Coral)}},dismissButton={TextButton(onClick={deleteTarget=null}){Text("Cancel")}})}
    if(finishId!=null){val s=TimerStore.read(context)
        if(s==null||s.taskId!=finishId)LaunchedEffect(finishId){finishHandled()}
        else AlertDialog(onDismissRequest=finishHandled,title={Text("Finish ${s.title}?")},text={Text("${timerText(TimerStore.remaining(context,s))} remaining. Mark the task complete, or just end this timer.")},confirmButton={TextButton(enabled=!busy,onClick={operation{repo.request("PATCH","/v2/day/tasks/${java.net.URLEncoder.encode(s.taskId,"UTF-8")}",JSONObject().put("done",true));TimerStore.action(context,"STOP");finishHandled()}}){Text("Mark done")}},dismissButton={Row{TextButton(onClick={TimerStore.action(context,"STOP");finishHandled()}){Text("End timer")};TextButton(onClick=finishHandled){Text("Continue")}}})
    }
}

private fun Modifier.clipShape(shape:androidx.compose.ui.graphics.Shape)=this.then(Modifier.background(Color.Transparent,shape)).then(Modifier.border(0.dp,Color.Transparent,shape)).then(Modifier.clip(shape))
private fun clockText(minutes:Int)="%02d:%02d".format(minutes/60,minutes%60)
@Composable private fun GapRow(minutes:Int,add:()->Unit){Row(Modifier.fillMaxWidth().padding(start=26.dp,end=24.dp,top=4.dp,bottom=12.dp).clickable(onClick=add),verticalAlignment=Alignment.CenterVertically){Box(Modifier.width(2.dp).height(32.dp).background(Color(0xFFE7DEDF)));Spacer(Modifier.width(62.dp));Icon(Icons.Rounded.Add,null,tint=Muted,modifier=Modifier.size(15.dp));Text("  $minutes min of breathing room",color=Muted,fontSize=12.sp)}}
@Composable private fun TaskRow(task:Task,inbox:Boolean,active:Boolean,edit:()->Unit,toggle:()->Unit,start:()->Unit){
    val color=hues[Math.floorMod((task.projectId?:task.parent?:task.title).hashCode(),hues.size)]
    Row(Modifier.fillMaxWidth().padding(start=20.dp,end=20.dp,bottom=12.dp),verticalAlignment=Alignment.Top){
        Column(Modifier.width(if(inbox)16.dp else 68.dp),horizontalAlignment=Alignment.CenterHorizontally){
            if(!inbox){Text(task.time?.take(5).orEmpty().let{if(task.clockMinutes>=1440)clockText(task.clockMinutes%1440)+" +1" else it},color=Muted,fontSize=12.sp,fontWeight=FontWeight.Medium,modifier=Modifier.padding(top=15.dp));Spacer(Modifier.height(10.dp));Box(Modifier.width(2.dp).height((task.minutes.coerceIn(10,90)/2).dp).background(Color(0xFFE7DEDF)))}
        }
        Surface(onClick=edit,color=color,shape=RoundedCornerShape(20.dp),modifier=Modifier.weight(1f).alpha(if(task.done)0.60f else 1f),border=if(active)BorderStroke(2.dp,Coral)else null){Column(Modifier.padding(14.dp)){
            Row(verticalAlignment=Alignment.CenterVertically){IconButton(onClick=toggle,modifier=Modifier.size(28.dp)){Icon(if(task.done)Icons.Rounded.CheckCircle else Icons.Rounded.RadioButtonUnchecked,if(task.done)"Reopen task" else "Complete task",tint=if(task.done)Coral else Color(0xFF8C7E9F),modifier=Modifier.size(22.dp))};Spacer(Modifier.width(8.dp));Text(task.title,modifier=Modifier.weight(1f),fontSize=17.sp,fontWeight=FontWeight.SemiBold,maxLines=3);if(task.starred)Icon(Icons.Rounded.Star,"Starred task",tint=Coral,modifier=Modifier.size(17.dp))}
            Row(Modifier.padding(start=36.dp,top=5.dp),verticalAlignment=Alignment.CenterVertically){Text("${task.minutes} min"+(if(task.habit)" · Habit" else if(task.parent!=null)" · Session" else ""),fontSize=12.sp,color=Color(0xFF726884),modifier=Modifier.weight(1f));if(!inbox)TextButton(onClick=start,contentPadding=PaddingValues(horizontal=4.dp,vertical=0.dp),modifier=Modifier.height(30.dp)){Icon(if(active)Icons.Rounded.HourglassBottom else Icons.Rounded.PlayArrow,null,modifier=Modifier.size(17.dp));Text(if(active)"Focusing" else "Focus",fontSize=12.sp)}}
        }}
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun TaskEditor(task:Task?,selected:LocalDate,initialTime:String?,busy:Boolean,dismiss:()->Unit,save:(String,LocalDate,String?,Int,String?)->Unit,star:(Task)->Unit,split:(Task)->Unit,delete:(Task)->Unit,start:(Task)->Unit){
    var title by remember(task){mutableStateOf(task?.title.orEmpty())};var date by remember(task){mutableStateOf(task?.date?:selected.toString())}
    var time by remember(task){mutableStateOf(task?.time?.take(5)?:initialTime.orEmpty())};var minutes by remember(task){mutableStateOf((task?.minutes?:30).toString())}
    var notes by remember(task){mutableStateOf(task?.notes.orEmpty())};var validation by remember{mutableStateOf<String?>(null)}
    ModalBottomSheet(onDismissRequest=dismiss,containerColor=Paper){Column(Modifier.fillMaxWidth().imePadding().verticalScroll(rememberScrollState()).padding(horizontal=24.dp).padding(bottom=24.dp)){
        Text(if(task==null)"Make a little plan" else "Your time block",fontSize=25.sp,fontWeight=FontWeight.Bold)
        Spacer(Modifier.height(16.dp));OutlinedTextField(title,{title=it},label={Text("Task name")},readOnly=task?.habit==true,modifier=Modifier.fillMaxWidth(),shape=RoundedCornerShape(14.dp),maxLines=3)
        Spacer(Modifier.height(12.dp));OutlinedTextField(date,{date=it},label={Text("Date · YYYY-MM-DD")},modifier=Modifier.fillMaxWidth(),singleLine=true,shape=RoundedCornerShape(14.dp))
        Row(Modifier.padding(top=12.dp),horizontalArrangement=Arrangement.spacedBy(12.dp)){OutlinedTextField(time,{time=it},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Ascii),label={Text("Start · HH:mm")},supportingText={Text("Leave blank for inbox")},modifier=Modifier.weight(1f),singleLine=true,shape=RoundedCornerShape(14.dp));OutlinedTextField(minutes,{minutes=it.filter{ch->ch.isDigit()}},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number),label={Text("Minutes")},modifier=Modifier.weight(1f),singleLine=true,shape=RoundedCornerShape(14.dp))}
        if(task==null){OutlinedTextField(notes,{notes=it},label={Text("Notes (optional)")},modifier=Modifier.fillMaxWidth(),shape=RoundedCornerShape(14.dp))}
        validation?.let{Text(it,color=MaterialTheme.colorScheme.error,modifier=Modifier.padding(vertical=8.dp),fontSize=12.sp)}
        Button(enabled=!busy,onClick={
            val parsed=runCatching{LocalDate.parse(date)}.getOrNull();val duration=minutes.toIntOrNull();val validTime=time.isBlank()||Regex("([01][0-9]|2[0-9]):[0-5][0-9]").matches(time)
            if(title.isBlank()||title.length>300||parsed==null||duration==null||duration !in 1..1440||!validTime)validation="Enter a task name, valid date, 1–1440 minutes and time such as 09:30 (up to29:59 for after midnight)." else save(title.trim(),parsed,time.takeIf{it.isNotBlank()},duration,notes.takeIf{it.isNotBlank()})
        },modifier=Modifier.fillMaxWidth().padding(top=16.dp).height(50.dp),shape=RoundedCornerShape(16.dp)){Text(if(busy)"Saving…" else "Save block")}
        task?.let{t->Row(Modifier.fillMaxWidth().padding(top=10.dp),horizontalArrangement=Arrangement.SpaceEvenly){TextButton(enabled=!busy,onClick={star(t)}){Icon(if(t.starred)Icons.Rounded.Star else Icons.Rounded.StarBorder,null);Text("Star")};if(!t.habit)TextButton(enabled=!busy&&t.minutes>=2,onClick={split(t)}){Icon(Icons.Rounded.CallSplit,null);Text("Split")};TextButton(enabled=!busy,onClick={delete(t)}){Icon(Icons.Rounded.DeleteOutline,null);Text("Delete")}}
            if(t.time!=null)OutlinedButton(onClick={start(t)},modifier=Modifier.fillMaxWidth()){Icon(Icons.Rounded.PlayArrow,null);Text("Start focus timer")}
        }
    }}
}

@Composable private fun SettingsDialog(repo:PlannerRepository,dismiss:()->Unit,notification:()->Unit,saved:()->Unit){
    val c=androidx.compose.ui.platform.LocalContext.current
    var url by remember{mutableStateOf(repo.config.baseUrl)};var key by remember{mutableStateOf("")};var reminders by remember{mutableStateOf(repo.config.reminders)}
    var error by remember{mutableStateOf<String?>(null)}
    AlertDialog(onDismissRequest=dismiss,title={Text("Your Planner OS")},text={Column(Modifier.verticalScroll(rememberScrollState())){
        Text("Connect to the same server as your PWA.",fontSize=13.sp,color=Muted)
        OutlinedTextField(url,{url=it},label={Text("HTTPS server URL")},placeholder={Text("https://your-planner-server")},singleLine=true,modifier=Modifier.padding(top=12.dp))
        OutlinedTextField(key,{key=it},label={Text(if(repo.config.configured)"Access key (blank keeps current)" else "App access key")},singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Password),visualTransformation=PasswordVisualTransformation(),modifier=Modifier.padding(top=12.dp))
        Text("Your key is encrypted using Android Keystore.",fontSize=11.sp,color=Muted,modifier=Modifier.padding(top=6.dp))
        TextButton(onClick={c.startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,Uri.parse("package:${c.packageName}")))}){Icon(Icons.Rounded.PictureInPicture,null);Text("Allow floating timer")}
        if(Build.VERSION.SDK_INT>=31)TextButton(onClick={c.startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,Uri.parse("package:${c.packageName}")))}){Icon(Icons.Rounded.NotificationsActive,null);Text("Allow precise reminders")}
        Row(verticalAlignment=Alignment.CenterVertically){Text("Native reminders",modifier=Modifier.weight(1f));Switch(reminders,{reminders=it;if(it)notification()})}
        Text("Same 30/5-minute task reminders and daily briefs. Disable browser notifications on this phone to avoid receiving both. On Samsung, allow background battery usage for dependable delivery.",fontSize=12.sp,color=Muted)
        Text("Offline: saved days remain readable. Connect to save edits. Focus timers continue without network access.",fontSize=12.sp,color=Muted,modifier=Modifier.padding(top=12.dp))
        error?.let{Text(it,color=MaterialTheme.colorScheme.error,fontSize=12.sp)}
    }},confirmButton={TextButton(onClick={try{val finalKey=key.ifBlank{repo.config.key()};val changed=url.trim().trimEnd('/')!=repo.config.baseUrl||finalKey!=repo.config.key();repo.config.save(url,finalKey);if(changed)c.getSharedPreferences("day-cache",android.content.Context.MODE_PRIVATE).edit().clear().commit();repo.config.reminders=reminders;Reminders.setup(c);saved();dismiss()}catch(e:Exception){error=e.message}}){Text("Save")}},dismissButton={TextButton(onClick=dismiss){Text("Close")}})
}
