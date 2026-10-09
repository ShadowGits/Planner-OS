package dev.planneros.android

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject
import java.time.LocalDate
import java.util.UUID
import kotlinx.coroutines.launch

class WorkLogActivity:ComponentActivity(){
    override fun onCreate(savedInstanceState:Bundle?){
        super.onCreate(savedInstanceState);if(!TimerPreferences.enabled(this)){finish();return};enableEdgeToEdge();FocusWorkLogs.promptOpen=true
        val task=intent.getStringExtra("task_ref")?:run{finish();return}
        val workId=intent.getStringExtra("work_id")
        val entry=FocusWorkLogs.entries(this).find{it.optString("id")==workId}
        if(workId!=null&&entry==null){finish();return}
        setContent{
            val preference=getSharedPreferences("appearance",MODE_PRIVATE).getString("theme","system")
            val dark=preference=="dark"||preference!="light"&&isSystemInDarkTheme()
            MaterialTheme(colorScheme=plannerColorScheme(dark)){WorkLogScreen(task,entry,dark){finish()}}
        }
    }
    override fun onResume(){super.onResume();if(!TimerPreferences.enabled(this))finish()}
    override fun onDestroy(){FocusWorkLogs.promptOpen=false;super.onDestroy()}
    @OptIn(ExperimentalMaterial3Api::class)
    @Composable private fun WorkLogScreen(initialTask:String,entry:JSONObject?,dark:Boolean,close:()->Unit){
        val scope=rememberCoroutineScope();val repo=remember{PlannerRepository(this)}
        var taskRef by rememberSaveable{mutableStateOf(initialTask)}
        val mandatory=entry?.optBoolean("mandatory")==true
        val id=rememberSaveable{entry?.optString("id")?:UUID.randomUUID().toString()}
        val prepared=entry?.optJSONObject("body")
        var frozen by remember{mutableStateOf(prepared)}
        var info by remember{mutableStateOf<JSONObject?>(null)}
        var error by remember{mutableStateOf<String?>(null)}
        var busy by remember{mutableStateOf(false)}
        var reload by remember{mutableIntStateOf(0)}
        var hours by rememberSaveable{mutableStateOf(((prepared?.optInt("seconds")?:entry?.optInt("seconds")?:0)/3600).toString())}
        var minutes by rememberSaveable{mutableStateOf(((prepared?.optInt("seconds")?:entry?.optInt("seconds")?:0)/60%60).toString())}
        var seconds by rememberSaveable{mutableStateOf(((prepared?.optInt("seconds")?:entry?.optInt("seconds")?:0)%60).toString())}
        var showSeconds by rememberSaveable{mutableStateOf(seconds!="0")}
        var split by rememberSaveable{mutableStateOf(prepared?.optBoolean("split")?:false)}
        var splitInitialized by rememberSaveable{mutableStateOf(prepared!=null)}
        var placing by remember{mutableStateOf(false)}
        var date by rememberSaveable{mutableStateOf(prepared?.nullString("remainder_date")?:LocalDate.now().toString())}
        var clock by rememberSaveable{mutableStateOf(prepared?.nullString("remainder_time").orEmpty())}
        var warning by remember{mutableStateOf<String?>(null)}
        var saved by remember{mutableStateOf<String?>(null)}
        fun dismiss(){if(!mandatory&&saved==null)FocusWorkLogs.ignore(this@WorkLogActivity,id);close()}
        BackHandler(enabled=mandatory&&saved==null){error="Log the actual work for this expired timer to finish."}
        BackHandler(enabled=!mandatory){dismiss()}
        LaunchedEffect(taskRef,reload){
            info=null;error=null
            try{info=repo.request("GET","/v2/day/tasks/${java.net.URLEncoder.encode(taskRef,"UTF-8")}/work").getJSONObject("data")}
            catch(e:Exception){error=e.message}
        }
        val task=info?.optJSONObject("task")
        val planned=info?.optInt("planned_seconds")?:0
        val worked=info?.optInt("worked_seconds")?:0
        val input=WorkLogPolicy.parse(hours,minutes,seconds)
        val rest=WorkLogPolicy.remaining(planned,worked,input?:0)
        val blocks=info?.optJSONArray("blocks")
        val selectBlock=blocks!=null&&blocks.length()>0
        LaunchedEffect(info){
            if(!splitInitialized&&task!=null&&!selectBlock){
                splitInitialized=true
                split=task.nullString("start_time")!=null&&!task.optBoolean("is_habit")&&!task.optBoolean("done")&&rest>0
            }
        }
        LaunchedEffect(split,taskRef){
            if(split&&clock.isBlank()&&frozen==null){
                placing=true
                try{
                    val now=java.time.ZonedDateTime.now(java.time.ZoneId.of(info?.optString("timezone")?:"Asia/Kolkata"))
                    val today=logicalToday(now);val selected=maxOf(LocalDate.parse(date),today)
                    val day=repo.confirmedCached(selected)?:repo.day(selected)
                    val slot=nextFreeSlot(selected,today,logicalNowMinute(now)+1,(rest.coerceAtLeast(1)+59)/60,taskBlocks(day.tasks.filter{!it.done&&it.id!=taskRef}))
                    date=slot.date.toString();clock=slot.clock
                }catch(e:kotlinx.coroutines.CancellationException){throw e}catch(e:Exception){error="Choose a time for the remainder, or use Find next clear slot. ${e.message.orEmpty()}"}
                finally{placing=false}
            }
        }
        LaunchedEffect(split,date,clock,rest,taskRef){
            warning=null
            if(split&&Regex("([01][0-9]|2[0-3]):[0-5][0-9]").matches(clock)){
                try{
                    val selected=LocalDate.parse(date)
                    val day=repo.confirmedCached(selected)?:repo.day(selected)
                    val parts=clock.split(":");val start=parts[0].toInt()*60+parts[1].toInt()
                    val conflicts=day.tasks.filter{it.id!=taskRef&&!it.done&&it.time!=null&&start<it.clockMinutes+it.minutes&&start+(rest+59)/60>it.clockMinutes}
                    if(conflicts.isNotEmpty())warning="Overlaps ${conflicts.joinToString{it.title}}. Choose another time for a clear slot."
                }catch(e:kotlinx.coroutines.CancellationException){throw e}catch(_:Exception){warning="Couldn't check other tasks. Review this time in your day."}
            }
        }
        fun save(){
            if(input==null){error="Enter 0–24 hours, with minutes and seconds between 0 and 59.";return}
            val parsedDate=runCatching{LocalDate.parse(date)}.getOrNull()
            val doSplit=split&&rest>0
            if(doSplit&&(parsedDate==null||!Regex("([01][0-9]|2[0-3]):[0-5][0-9]").matches(clock))){error="Choose a valid date and start time for the remaining work.";return}
            busy=true;error=null
            scope.launch{
                try{
                    val body=frozen?:JSONObject().put("request_id",id).put("seconds",input).put("source",if(entry==null)"manual"else "timer").put("finish",true).put("split",doSplit).apply{if(doSplit){put("remainder_date",date);put("remainder_time",clock)}}
                    FocusWorkLogs.prepare(this@WorkLogActivity,id,taskRef,task?.optString("title")?:entry?.optString("title")?:"Task",body,mandatory)
                    frozen=body
                    val row=FocusWorkLogs.entries(this@WorkLogActivity).first{it.optString("id")==id}
                    val response=FocusWorkLogs.submit(this@WorkLogActivity,row)
                    if(TimerStore.read(this@WorkLogActivity)?.sessionId==id)TimerStore.action(this@WorkLogActivity,"STOP",id)
                    saved=if(body.optBoolean("split"))"${workDuration(body.getInt("seconds"))} logged · ${workDuration(response.optInt("remaining_seconds"))} scheduled for $date at $clock"else if(response.optBoolean("done"))"${workDuration(body.getInt("seconds"))} logged · Task complete"else "${workDuration(body.getInt("seconds"))} logged · ${workDuration(response.optInt("remaining_seconds"))} remaining"
                }catch(e:kotlinx.coroutines.CancellationException){throw e}catch(e:Exception){
                    if(e is PlannerHttpException&&e.statusCode==400){FocusWorkLogs.allowEditing(this@WorkLogActivity,id);frozen=null}
                    error=e.message
                }
                finally{busy=false}
            }
        }
        Scaffold(containerColor=MaterialTheme.colorScheme.background,topBar={TopAppBar(title={Text(if(mandatory)"Timer finished"else "Log time",fontSize=22.sp,fontWeight=FontWeight.SemiBold)},navigationIcon={if(!mandatory||saved!=null)IconButton(enabled=!busy,onClick=::dismiss){Icon(Icons.AutoMirrored.Rounded.ArrowBack,"Back")}},actions={if(!mandatory&&saved==null)TextButton(enabled=!busy,onClick=::dismiss){Text(if(frozen==null)"Ignore"else "Close")}})}){padding->
            Column(Modifier.fillMaxSize().padding(padding).imePadding().verticalScroll(rememberScrollState()).padding(20.dp),verticalArrangement=Arrangement.spacedBy(16.dp)){
                Text(task?.optString("title")?:entry?.optString("title")?:"Loading task…",fontSize=24.sp,fontWeight=FontWeight.SemiBold)
                if(saved!=null){
                    Icon(Icons.Rounded.CheckCircle,null,tint=MaterialTheme.colorScheme.tertiary,modifier=Modifier.size(42.dp))
                    Text(saved!!,fontSize=20.sp)
                    Button(onClick=close,modifier=Modifier.fillMaxWidth()){Text("Back to planner")}
                }else{
                    if(mandatory)Text("The timer ran out. Enter how much you actually worked.",fontSize=17.sp)
                    if(task?.optBoolean("done")==true)Text("This task is already complete. You can still record its actual time.",fontSize=16.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                    if(info==null&&error==null)CircularProgressIndicator()
                    if(selectBlock){
                        Text("Choose the block you worked on",fontSize=18.sp,fontWeight=FontWeight.SemiBold)
                        for(i in 0 until blocks!!.length()){val block=blocks.getJSONObject(i);OutlinedButton(enabled=!busy&&frozen==null,onClick={taskRef=block.getString("id");hours="0";minutes="0";seconds="0";clock="";split=false;splitInitialized=false},modifier=Modifier.fillMaxWidth()){Text("Part ${i+1} · ${block.nullString("scheduled_date").orEmpty()} · ${block.nullString("start_time")?.take(5).orEmpty()} · ${durationLabel(block.optInt("estimated_minutes"))}")}}
                    }else if(info!=null){
                        Surface(color=PlannerPalette.Navy,contentColor=Color.White,shape=MaterialTheme.shapes.large){Column(Modifier.fillMaxWidth().padding(18.dp)){
                            Text("${workDuration(worked)} worked",fontSize=28.sp,fontWeight=FontWeight.Bold)
                            Text("${workDuration(planned)} planned · ${workDuration((planned-worked).coerceAtLeast(0))} remaining",fontSize=16.sp,color=PlannerPalette.Ice)
                        }}
                        Text("Time worked in this session",fontSize=18.sp,fontWeight=FontWeight.SemiBold)
                        Row(horizontalArrangement=Arrangement.spacedBy(12.dp)){
                            OutlinedTextField(hours,{hours=it.filter(Char::isDigit)},label={Text("Hours")},singleLine=true,readOnly=frozen!=null,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number),modifier=Modifier.weight(1f))
                            OutlinedTextField(minutes,{minutes=it.filter(Char::isDigit)},label={Text("Minutes")},singleLine=true,readOnly=frozen!=null,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number),modifier=Modifier.weight(1f))
                        }
                        if(!showSeconds)TextButton(onClick={showSeconds=true}){Text("Add seconds (optional)")}
                        if(showSeconds)OutlinedTextField(seconds,{seconds=it.filter(Char::isDigit)},label={Text("Seconds")},singleLine=true,readOnly=frozen!=null,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number),modifier=Modifier.fillMaxWidth())
                        Text("After logging: ${workDuration(rest)} left",fontSize=20.sp,fontWeight=FontWeight.Medium)
                        if(rest>0||split)Row(verticalAlignment=androidx.compose.ui.Alignment.CenterVertically){Text("Split & schedule remaining work",modifier=Modifier.weight(1f),fontSize=17.sp);Switch(split,{if(frozen==null)split=it},enabled=frozen==null)}
                        if(split){
                            Text(if(task?.optBoolean("is_habit")==true)"Only this habit occurrence moves. Its recurring schedule stays as it is."else "The worked block is completed; the remaining block stays open.",fontSize=15.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                            TextButton(enabled=frozen==null&&!busy,onClick={scope.launch{
                                busy=true;error=null
                                try{
                                    val selected=LocalDate.parse(date);val day=repo.confirmedCached(selected)?:repo.day(selected)
                                    val now=java.time.ZonedDateTime.now(java.time.ZoneId.of(info?.optString("timezone")?:"Asia/Kolkata"))
                                    val slot=nextFreeSlot(selected,now.toLocalDate(),now.hour*60+now.minute+1,(rest+59)/60,taskBlocks(day.tasks.filter{!it.done&&it.id!=taskRef}))
                                    date=slot.date.toString();clock=slot.clock
                                }catch(e:kotlinx.coroutines.CancellationException){throw e}catch(e:Exception){error=e.message}finally{busy=false}
                            }}){Icon(Icons.Rounded.AutoAwesome,null,modifier=Modifier.size(18.dp));Spacer(Modifier.width(8.dp));Text("Find next clear slot")}
                            OutlinedButton(enabled=frozen==null,onClick={val d=runCatching{LocalDate.parse(date)}.getOrDefault(LocalDate.now());DatePickerDialog(pickerContext(this@WorkLogActivity,dark),{_,y,m,day->date=LocalDate.of(y,m+1,day).toString()},d.year,d.monthValue-1,d.dayOfMonth).show()},modifier=Modifier.fillMaxWidth()){Icon(Icons.Rounded.CalendarMonth,null);Text(" $date")}
                            OutlinedButton(enabled=frozen==null,onClick={val parts=clock.split(":");TimePickerDialog(pickerContext(this@WorkLogActivity,dark),{_,h,m->clock="%02d:%02d".format(h,m)},parts.firstOrNull()?.toIntOrNull()?:18,parts.getOrNull(1)?.toIntOrNull()?:0,android.text.format.DateFormat.is24HourFormat(this@WorkLogActivity)).show()},modifier=Modifier.fillMaxWidth()){Icon(Icons.Rounded.Schedule,null);Text(" "+clock.ifBlank{"Choose later time"})}
                            warning?.let{Text(it,fontSize=15.sp,color=MaterialTheme.colorScheme.error)}
                        }
                        if(frozen!=null)Text("This entry is saved on this device. Retry sends the same entry, without logging it twice.",fontSize=15.sp)
                        Button(enabled=!busy&&!placing,onClick=::save,modifier=Modifier.fillMaxWidth().heightIn(min=52.dp)){Text(if(busy)"Saving…"else if(placing)"Finding a slot…"else if(frozen!=null)"Retry saved entry"else if(split&&rest>0)"Log & schedule remainder"else "Save time")}
                        val sessions=info?.optJSONArray("sessions")
                        if(sessions!=null&&sessions.length()>0){Text("Work history",fontSize=19.sp,fontWeight=FontWeight.SemiBold);for(i in sessions.length()-1 downTo 0){val session=sessions.getJSONObject(i);Text("${workDuration(session.optInt("seconds"))} · ${session.optString("source")} · ${runCatching{java.time.OffsetDateTime.parse(session.optString("created_at")).atZoneSameInstant(java.time.ZoneId.of(info?.optString("timezone")?:"Asia/Kolkata")).format(java.time.format.DateTimeFormatter.ofPattern("d MMM · HH:mm"))}.getOrDefault("")}",fontSize=15.sp)}}
                    }
                    error?.let{Text(it,fontSize=16.sp,color=MaterialTheme.colorScheme.error);if(info==null)OutlinedButton(onClick={reload++}){Text("Retry")}}
                }
            }
        }
    }
}
