package dev.planneros.android

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.view.ContextThemeWrapper
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.CallSplit
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.LocalDate

internal data class EditorValues(val title:String,val date:LocalDate,val time:String?,val minutes:Int,val notes:String?)
internal fun pickerContext(context:Context,dark:Boolean):Context = ContextThemeWrapper(context,if(dark)android.R.style.Theme_Material_Dialog_Alert else android.R.style.Theme_Material_Light_Dialog_Alert)

@OptIn(ExperimentalMaterial3Api::class)
@Composable internal fun PlannerEditor(task:Task?,selected:LocalDate,suggestedDate:String?,suggestedTime:String?,busy:Boolean,draft:EditorValues?,dismiss:()->Unit,
    save:(String,LocalDate,String?,Int,String?)->Unit,star:(Task)->Unit,split:(Task)->Unit,delete:(Task)->Unit,focus:(Task)->Unit){
    val c=LocalContext.current;val dark=MaterialTheme.colorScheme.surface.luminance()<.5f
    val existing=task?.time?.let{normalizeSlot(if(task.clockMinutes<1440)task.date?.let(LocalDate::parse)?:selected else selected,task.clockMinutes)}
    var title by rememberSaveable(task?.id){mutableStateOf(draft?.title?:task?.title.orEmpty())}
    var date by rememberSaveable(task?.id){mutableStateOf(draft?.date?.toString()?:suggestedDate?:existing?.date?.toString()?:task?.date?:selected.toString())}
    var time by rememberSaveable(task?.id){mutableStateOf(if(draft!=null)draft.time.orEmpty() else suggestedTime?:existing?.clock.orEmpty())}
    var minutes by rememberSaveable(task?.id){mutableStateOf((draft?.minutes?:task?.minutes?:30).toString())}
    var notes by rememberSaveable(task?.id){mutableStateOf(draft?.notes?:task?.notes.orEmpty())}
    var validation by remember{mutableStateOf<String?>(null)}
    ModalBottomSheet(onDismissRequest=dismiss,containerColor=MaterialTheme.colorScheme.surface){
        Column(Modifier.fillMaxWidth().imePadding().verticalScroll(rememberScrollState()).padding(horizontal=22.dp).padding(bottom=24.dp)){
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Text(if(task==null)"New task" else "Edit task",fontSize=24.sp,fontWeight=FontWeight.Bold);IconButton(onClick=dismiss){Icon(Icons.Rounded.Close,"Close task editor")}}
            task?.parent?.let{Text("${task.parentTitle.orEmpty()} · Part ${task.partIndex?:"?"} of ${task.partCount?:"?"}",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)}
            OutlinedTextField(title,{title=it},label={Text("Task name")},readOnly=task?.habit==true,modifier=Modifier.fillMaxWidth(),shape=RoundedCornerShape(14.dp),maxLines=4)
            Spacer(Modifier.height(10.dp))
            OutlinedTextField(date,{date=it},label={Text("Date · YYYY-MM-DD")},singleLine=true,modifier=Modifier.fillMaxWidth(),shape=RoundedCornerShape(14.dp),trailingIcon={IconButton(onClick={val d=runCatching{LocalDate.parse(date)}.getOrDefault(selected);DatePickerDialog(pickerContext(c,dark),{_,y,m,day->date=LocalDate.of(y,m+1,day).toString()},d.year,d.monthValue-1,d.dayOfMonth).show()}){Icon(Icons.Rounded.CalendarMonth,"Choose task date")}})
            OutlinedTextField(time,{time=it},label={Text("Start time · HH:mm")},supportingText={Text("Leave blank for Inbox")},singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Ascii),modifier=Modifier.fillMaxWidth().padding(top=10.dp),shape=RoundedCornerShape(14.dp),trailingIcon={Row{
                if(time.isNotEmpty())IconButton(onClick={time=""}){Icon(Icons.Rounded.Close,"Move task to Inbox")}
                IconButton(onClick={val parts=time.split(":");TimePickerDialog(pickerContext(c,dark),{_,h,m->time="%02d:%02d".format(h,m)},parts.firstOrNull()?.toIntOrNull()?.coerceIn(0,23)?:9,parts.getOrNull(1)?.toIntOrNull()?.coerceIn(0,59)?:0,android.text.format.DateFormat.is24HourFormat(c)).show()}){Icon(Icons.Rounded.Schedule,"Choose task time")}
            }})
            Text("Duration",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=4.dp))
            Row(Modifier.horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(7.dp)){
                listOf(15,30,45,60,90,120).forEach{value->FilterChip(selected=minutes.toIntOrNull()==value,onClick={minutes=value.toString()},label={Text(durationLabel(value))})}
            }
            OutlinedTextField(minutes,{minutes=it.filter(Char::isDigit)},label={Text("Custom minutes")},singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number),modifier=Modifier.fillMaxWidth(),shape=RoundedCornerShape(14.dp))
            if(task==null)OutlinedTextField(notes,{notes=it},label={Text("Notes (optional)")},modifier=Modifier.fillMaxWidth().padding(top=10.dp),shape=RoundedCornerShape(14.dp))
            validation?.let{Text(it,color=MaterialTheme.colorScheme.error,fontSize=12.sp,modifier=Modifier.padding(top=7.dp))}
            Button(enabled=!busy,onClick={
                val parsed=runCatching{LocalDate.parse(date)}.getOrNull();val duration=minutes.toIntOrNull()
                if(title.isBlank()||title.length>300||parsed==null||duration==null||duration !in 1..1440||!(time.isBlank()||Regex("([01][0-9]|2[0-3]):[0-5][0-9]").matches(time)))validation="Enter a task name, valid date, 1–1440 minutes and a time such as 09:30."
                else save(title.trim(),parsed,time.takeIf{it.isNotBlank()},duration,notes.takeIf{it.isNotBlank()})
            },modifier=Modifier.fillMaxWidth().padding(top=14.dp).height(48.dp),shape=RoundedCornerShape(14.dp)){Text(if(busy)"Saving…" else if(task==null)"Add to day" else "Save")}
            task?.let{t->
                TextButton(enabled=!busy,onClick={star(t)},modifier=Modifier.fillMaxWidth()){Icon(if(t.starred)Icons.Rounded.Star else Icons.Rounded.StarBorder,null);Text(if(t.starred)" One of today's wins" else " Mark as one of today's wins")}
                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceEvenly){
                    if(!t.habit)TextButton(enabled=!busy&&t.minutes>=2,onClick={split(t)}){Icon(Icons.AutoMirrored.Rounded.CallSplit,null);Text(" Split")}
                    TextButton(enabled=!busy,onClick={delete(t)}){Icon(Icons.Rounded.DeleteOutline,null);Text(if(t.habit)" Skip occurrence" else " Delete")}
                }
                if(t.time!=null)OutlinedButton(onClick={focus(t)},modifier=Modifier.fillMaxWidth()){Icon(Icons.Rounded.PlayArrow,null);Text(" Start focus timer")}
            }
        }
    }
}

@Composable internal fun ConnectionSettings(repo:PlannerRepository,appearance:String,onAppearance:(String)->Unit,dismiss:()->Unit,notification:()->Unit,saved:()->Unit){
    val c=LocalContext.current
    var testResult by remember{mutableStateOf<String?>(null)}
    val notificationManager=c.getSystemService(android.app.NotificationManager::class.java)
    val enabled=notificationManager.areNotificationsEnabled()&&(Build.VERSION.SDK_INT<33||androidx.core.content.ContextCompat.checkSelfPermission(c,android.Manifest.permission.POST_NOTIFICATIONS)==android.content.pm.PackageManager.PERMISSION_GRANTED)
    var url by remember{mutableStateOf(repo.config.baseUrl)};var key by remember{mutableStateOf("")};var reminders by remember{mutableStateOf(repo.config.reminders)};var error by remember{mutableStateOf<String?>(null)}
    var automatic by remember{mutableStateOf(AutoFocusScheduler.enabled(c))}
    AlertDialog(onDismissRequest=dismiss,title={Text("Your Planner OS")},text={Column(Modifier.verticalScroll(rememberScrollState())){
        Text("Connect to the same server as your PWA.",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedTextField(url,{url=it},label={Text("HTTPS server URL")},singleLine=true,modifier=Modifier.padding(top=10.dp))
        OutlinedTextField(key,{key=it},label={Text(if(repo.config.configured)"Access key (blank keeps current)" else "App access key")},singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Password),visualTransformation=PasswordVisualTransformation(),modifier=Modifier.padding(top=10.dp))
        Text("Your key is encrypted using Android Keystore.",fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=5.dp))
        Text("Appearance",fontWeight=FontWeight.SemiBold,modifier=Modifier.padding(top=10.dp))
        Row(horizontalArrangement=Arrangement.spacedBy(6.dp)){listOf("system","light","dark").forEach{mode->FilterChip(selected=appearance==mode,onClick={onAppearance(mode)},label={Text(mode.replaceFirstChar(Char::titlecase))})}}
        if(TimerStore.read(c)!=null)TextButton(onClick={TimerStore.action(c,"SHOW")}){Icon(Icons.Rounded.PictureInPictureAlt,null);Text(" Show floating timer")}
        TextButton(onClick={c.startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,Uri.parse("package:${c.packageName}")))}){Icon(Icons.Rounded.PictureInPicture,null);Text(" Allow floating timer")}
        Row(verticalAlignment=androidx.compose.ui.Alignment.CenterVertically){Text("Start focus with scheduled blocks",modifier=Modifier.weight(1f));Switch(automatic,{automatic=it})}
        Text(if(AutoFocusScheduler.backgroundAvailable(c))"Automatic timers can start in the background. Pausing or canceling a block keeps that occurrence stopped." else "Automatic timers start while Planner OS is open. Allow precise alarms to start them in the background. Pausing or canceling keeps that occurrence stopped.",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
        if(Build.VERSION.SDK_INT>=31)TextButton(onClick={c.startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,Uri.parse("package:${c.packageName}")))}){Icon(Icons.Rounded.NotificationsActive,null);Text(" Allow precise alarms")}
        Row(verticalAlignment=androidx.compose.ui.Alignment.CenterVertically){Text("Native reminders",modifier=Modifier.weight(1f));Switch(reminders,{reminders=it;if(it)notification()})}
        Text(if(enabled)"System notifications enabled" else "System notifications blocked",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
        TextButton(onClick={if(!enabled)notification();testResult=if(Reminders.test(c))"Test sent — check your notification shade." else "Notifications are blocked. Allow notifications and the Planner reminders channel in Android Settings, then test again."}){Icon(Icons.Rounded.NotificationsNone,null);Text(" Test notification")}
        testResult?.let{Text(it,fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)}
        Text("Lock-screen timer: allow lock-screen notifications and Show content for Planner OS in Samsung Settings. Tap the timer card to open the wooden dial while locked; Android decides whether Live Updates appear in the Now Bar.",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
        TextButton(onClick={c.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE,c.packageName))}){Text(" Android notification settings")}
        Text("Same 30/5-minute task reminders and daily briefs. Disable browser notifications on this phone to avoid receiving both. On Samsung, allow background battery usage for dependable delivery.",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
        Text("Offline: saved days remain readable. Reconnect to save edits. Focus timers run without network access.",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=10.dp))
        error?.let{Text(it,color=MaterialTheme.colorScheme.error,fontSize=12.sp)}
    }},confirmButton={TextButton(onClick={try{repo.config.save(url,key.ifBlank{repo.config.key()});repo.config.reminders=reminders;AutoFocusScheduler.setEnabled(c,automatic);Reminders.setup(c);saved();dismiss()}catch(e:Exception){error=e.message}}){Text("Save")}},dismissButton={TextButton(onClick=dismiss){Text("Close")}})
}
