package dev.planneros.android

import android.text.format.DateFormat
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.snap
import androidx.compose.animation.core.spring
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.DirectionsBike
import androidx.compose.material.icons.automirrored.rounded.DirectionsRun
import androidx.compose.material.icons.automirrored.rounded.DirectionsWalk
import androidx.compose.material.icons.automirrored.rounded.MenuBook
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onPlaced
import androidx.compose.ui.layout.positionInParent
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.platform.ViewConfiguration
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import kotlin.math.abs

// The day laid out like Structured: a spine of coloured capsules sized by
// duration, free time between them, untimed tasks as round chips on top. The
// same rules as the Apple app's TimelinePolicy.swift.

internal sealed interface DayEntry { val key:String }
internal data class TaskEntry(val task:Task,val showsStart:Boolean):DayEntry { override val key get()=task.id }
/** Free time between tasks, and the task that follows it. */
internal data class GapEntry(val start:Int,val minutes:Int,val next:String):DayEntry { override val key get()="gap-$start" }

/** Timed tasks in order, with free time of five minutes or more between them.
 *  A start time shows only where it is not the previous task's end. */
internal fun dayEntries(tasks:List<Task>):List<DayEntry> {
    val entries=mutableListOf<DayEntry>();var lastEnd:Int?=null
    for(task in tasks.filter{it.time!=null}.sortedWith(compareBy<Task>{it.clockMinutes}.thenBy{it.title})){
        val start=task.clockMinutes
        lastEnd?.let{end->if(start-end>=5)entries+=GapEntry(end,start-end,task.title)}
        entries+=TaskEntry(task,lastEnd!=start)
        lastEnd=maxOf(lastEnd?:0,start+task.minutes)
    }
    return entries
}

internal const val ROW_PADDING_DP=5f
/** A 15-minute task is a circle; longer ones stretch, up to a limit. */
internal fun pillHeightDp(minutes:Int)=(minutes*2.4f).coerceIn(52f,216f)
/** Free time takes less room than work does. */
internal fun gapHeightDp(minutes:Int)=(minutes*0.6f).coerceIn(34f,96f)
internal fun entryHeightDp(entry:DayEntry)=when(entry){is TaskEntry->pillHeightDp(entry.task.minutes)+2*ROW_PADDING_DP;is GapEntry->gapHeightDp(entry.minutes)}
/** How far down the list a task sits, for scrolling to it. */
internal fun entryOffsetDp(entries:List<DayEntry>,key:String):Float? {
    var y=0f
    for(entry in entries){if(entry.key==key)return y;y+=entryHeightDp(entry)}
    return null
}
/** "15m", "1h", "1h 30m" */
internal fun shortDuration(minutes:Int)=when{minutes<60->"${minutes}m";minutes%60==0->"${minutes/60}h";else->"${minutes/60}h ${minutes%60}m"}

/** A colour slot that stays the same for a title on every device (the Apple app uses the same hash). */
internal fun paletteIndex(title:String,count:Int):Int {
    var hash=5381UL
    title.codePoints().forEach{hash=hash*33UL+it.toULong()}
    return (hash%count.coerceAtLeast(1).toULong()).toInt()
}

/** Coral, slate, navy, sage, wine, amber, teal, lavender. */
private val blockColors=listOf(Color(0xFFF2948F),Color(0xFF6685B0),Color(0xFF2B4A6E),Color(0xFF8CC266),
    Color(0xFF8F3D57),Color(0xFFF0AD4D),Color(0xFF3D999E),Color(0xFF9480CC))
internal fun blockColor(task:Task)=blockColors[paletteIndex(task.title,blockColors.size)]

/** Words in a title that pick its icon, first match wins; the Apple app uses the same list. */
private val iconRules:List<Pair<List<String>,ImageVector>> = listOf(
    listOf("wake","alarm") to Icons.Rounded.Alarm,
    listOf("sleep","bed","nap") to Icons.Rounded.Bedtime,
    listOf("yoga","meditat","stretch","breath") to Icons.Rounded.SelfImprovement,
    listOf("gym","workout","lift","strength") to Icons.Rounded.FitnessCenter,
    listOf("run","jog") to Icons.AutoMirrored.Rounded.DirectionsRun,
    listOf("walk") to Icons.AutoMirrored.Rounded.DirectionsWalk,
    listOf("bike","cycl") to Icons.AutoMirrored.Rounded.DirectionsBike,
    listOf("shower","get ready","bath") to Icons.Rounded.Shower,
    listOf("coffee","tea") to Icons.Rounded.LocalCafe,
    listOf("breakfast","lunch","dinner","meal","eat","cook") to Icons.Rounded.Restaurant,
    listOf("water","hydrat") to Icons.Rounded.WaterDrop,
    listOf("german","language","duolingo","vocab") to Icons.Rounded.Translate,
    listOf("study","learn","course","lecture","class","calculus","math","revise","exam") to Icons.AutoMirrored.Rounded.MenuBook,
    listOf("read","book") to Icons.Rounded.AutoStories,
    listOf("apply","application","university","uni ","admission","aps") to Icons.Rounded.School,
    listOf("cv","resume","write","essay","sop","letter","draft") to Icons.Rounded.Edit,
    listOf("call","phone") to Icons.Rounded.Call,
    listOf("meet","interview","sync","standup") to Icons.Rounded.Groups,
    listOf("mail","email","inbox") to Icons.Rounded.Email,
    listOf("code","dev","build","deploy","bug","app","planner") to Icons.Rounded.Laptop,
    listOf("pay","bank","budget","tax","finance","money","rent","invoice") to Icons.Rounded.CreditCard,
    listOf("shop","grocer","buy") to Icons.Rounded.ShoppingCart,
    listOf("clean","laundry","tidy") to Icons.Rounded.CleaningServices,
    listOf("flight","travel","visa","trip","airport") to Icons.Rounded.Flight,
    listOf("drive","car ") to Icons.Rounded.DirectionsCar,
    listOf("doctor","health","medic","dentist") to Icons.Rounded.MedicalServices,
    listOf("birthday","anniversary","gift") to Icons.Rounded.Cake,
    listOf("music","guitar","piano") to Icons.Rounded.MusicNote,
    listOf("plan","review","journal") to Icons.Rounded.EditCalendar,
    listOf("work","office","job","intern") to Icons.Rounded.Work,
)
internal fun taskIcon(task:Task):ImageVector {
    val title=" ${task.title.lowercase()} "
    return iconRules.firstOrNull{(words,_)->words.any{title.contains(it)}}?.second?:if(task.habit)Icons.Rounded.Repeat else Icons.Rounded.TaskAlt
}

/** "May 2026", the year in the accent colour. */
@Composable internal fun MonthTitle(date:LocalDate){
    Row(verticalAlignment=Alignment.Bottom){
        Text(date.format(DateTimeFormatter.ofPattern("MMMM")),fontSize=26.sp,fontWeight=FontWeight.Bold,maxLines=1)
        Text(" ${date.year}",fontSize=26.sp,fontWeight=FontWeight.Bold,color=MaterialTheme.colorScheme.primary,maxLines=1)
    }
}

/** Mon to Sun with the selected day in a filled circle. Swipe for other weeks. */
@Composable internal fun StructuredWeekStrip(selected:LocalDate,today:LocalDate,hasTasks:(LocalDate)->Boolean,onSelect:(LocalDate)->Unit){
    val density=LocalDensity.current.density
    val start=selected.minusDays((selected.dayOfWeek.value-1).toLong())
    var dragX by remember{mutableFloatStateOf(0f)}
    val latestSelect by rememberUpdatedState(onSelect)
    Row(Modifier.fillMaxWidth().padding(horizontal=8.dp).padding(bottom=10.dp).pointerInput(selected){
        detectHorizontalDragGestures(onDragStart={dragX=0f},onDragEnd={
            if(abs(dragX)>60*density)latestSelect(selected.plusDays(if(dragX<0)7 else -7))
            dragX=0f
        }){change,amount->change.consume();dragX+=amount}
    }){
        for(index in 0..6){
            val day=start.plusDays(index.toLong());val isSelected=day==selected
            Column(Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).clickable{onSelect(day)}.padding(vertical=4.dp)
                .semantics{contentDescription=day.format(DateTimeFormatter.ofPattern("EEEE, MMMM d"))+if(isSelected)", selected" else ""},
                horizontalAlignment=Alignment.CenterHorizontally){
                Text(day.format(DateTimeFormatter.ofPattern("EEE")),fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(4.dp))
                Box(Modifier.size(34.dp).background(if(isSelected)MaterialTheme.colorScheme.primary else Color.Transparent,CircleShape),contentAlignment=Alignment.Center){
                    Text(day.dayOfMonth.toString(),fontSize=16.sp,fontWeight=FontWeight.SemiBold,
                        color=if(isSelected)MaterialTheme.colorScheme.onPrimary else if(day==today)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                }
                Box(Modifier.padding(top=3.dp).size(4.dp).background(if(!isSelected&&hasTasks(day))MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha=.6f) else Color.Transparent,CircleShape))
            }
        }
    }
}

/** Tasks with no time, as round chips like all-day events. Hold one to tick it off. */
@OptIn(ExperimentalFoundationApi::class)
@Composable private fun AllDayChips(tasks:List<Task>,enabled:(Task)->Boolean,open:(Task)->Unit,done:(Task)->Unit){
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal=4.dp,vertical=6.dp),horizontalArrangement=Arrangement.spacedBy(14.dp)){
        tasks.forEach{task->
            val color=blockColor(task);val interactive=enabled(task)
            Column(Modifier.width(76.dp).alpha(if(interactive)1f else .5f).clip(RoundedCornerShape(12.dp))
                .combinedClickable(enabled=interactive,onClick={open(task)},onLongClick={done(task)})
                .semantics{contentDescription="${task.title}, any time${if(task.done)", done" else ""}. Hold to ${if(task.done)"reopen" else "complete"}"},
                horizontalAlignment=Alignment.CenterHorizontally){
                Box(Modifier.size(58.dp).background(MaterialTheme.colorScheme.onSurface.copy(alpha=.07f),CircleShape),contentAlignment=Alignment.Center){
                    Icon(taskIcon(task),null,tint=color,modifier=Modifier.size(26.dp))
                    if(task.done)Icon(Icons.Rounded.CheckCircle,null,tint=color,modifier=Modifier.align(Alignment.BottomEnd).size(18.dp).background(MaterialTheme.colorScheme.background,CircleShape))
                }
                Spacer(Modifier.height(6.dp))
                Text(task.title,fontSize=12.sp,fontWeight=FontWeight.SemiBold,textAlign=TextAlign.Center,maxLines=2,overflow=TextOverflow.Ellipsis,lineHeight=15.sp,
                    textDecoration=if(task.done)TextDecoration.LineThrough else null,
                    color=if(task.done)MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface)
            }
        }
    }
}

/**
 * The day's timeline. Dragging is driven by MainActivity (DragState and
 * DragPreview, with edge auto-scroll); this draws it: the held task tracks the
 * finger exactly, ticks at each five-minute step, and on release it, and any
 * task it displaced, glide into their new places.
 */
@Composable internal fun StructuredTimeline(tasks:List<Task>,allDay:List<Task>,date:LocalDate,isToday:Boolean,nowMinute:Int,timerId:String?,
    enabled:Boolean,scroll:ScrollState,preview:DragPreview?,modifier:Modifier=Modifier,
    edit:(Task)->Unit,done:(Task)->Unit,focus:(Task)->Unit,gap:(Int)->Unit,
    dragStart:(Task)->Unit,dragMove:(Task,Offset,Float)->Unit,dragEnd:(Task)->Unit,dragCancel:()->Unit,
    viewport:(Float,Float)->Unit){
    val entries=remember(tasks){dayEntries(tasks)}
    val config=LocalViewConfiguration.current
    val holdConfig=remember(config){object:ViewConfiguration by config{override val longPressTimeoutMillis=230L}}
    val twelve=!DateFormat.is24HourFormat(LocalContext.current)
    val now=if(isToday)nowMinute else null
    CompositionLocalProvider(LocalViewConfiguration provides holdConfig){
        Column(modifier.onGloballyPositioned{val y=it.positionInWindow().y;viewport(y,y+it.size.height)}
            .verticalScroll(scroll).padding(start=12.dp,end=8.dp,top=6.dp,bottom=96.dp)){
            if(allDay.isNotEmpty()){
                AllDayChips(allDay,{enabled&&!it.id.startsWith("pending:")},edit,done)
                Spacer(Modifier.height(10.dp))
            }
            if(entries.isEmpty())Text(if(allDay.isEmpty())"Nothing planned. Tap + to add a task." else "Nothing at a set time. Tap + to add one.",
                color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.fillMaxWidth().padding(top=48.dp),textAlign=TextAlign.Center)
            entries.forEach{entry->
                key(entry.key){
                    when(entry){
                        is TaskEntry->{
                            val dragging=preview?.taskId==entry.task.id
                            TimelineTaskRow(entry.task,entry.showsStart,entry.key==entries.first().key,entry.key==entries.last().key,
                                now,twelve,enabled&&!entry.task.id.startsWith("pending:"),timerId==entry.task.id,
                                lifted=dragging,liftDp=if(dragging)preview!!.deltaDp else 0f,
                                target=if(dragging)preview!!.target else null,viewDate=date,
                                edit={edit(entry.task)},done={done(entry.task)},focus={focus(entry.task)},
                                dragStart={dragStart(entry.task)},dragMove={delta,y->dragMove(entry.task,delta,y)},
                                dragEnd={dragEnd(entry.task)},dragCancel=dragCancel)
                        }
                        is GapEntry->GapRow(entry,now,{gap(((entry.start+4)/5)*5)})
                    }
                }
            }
        }
    }
}

@Composable private fun TimelineTaskRow(task:Task,showsStart:Boolean,first:Boolean,last:Boolean,now:Int?,twelve:Boolean,
    interactive:Boolean,timing:Boolean,lifted:Boolean,liftDp:Float,target:ScheduleSlot?,viewDate:LocalDate,
    edit:()->Unit,done:()->Unit,focus:()->Unit,dragStart:()->Unit,dragMove:(Offset,Float)->Unit,dragEnd:()->Unit,dragCancel:()->Unit){
    val density=LocalDensity.current.density
    val haptic=LocalHapticFeedback.current
    val scope=rememberCoroutineScope()
    var windowY by remember{mutableFloatStateOf(0f)}
    val latestStart by rememberUpdatedState(dragStart);val latestMove by rememberUpdatedState(dragMove)
    val latestEnd by rememberUpdatedState(dragEnd);val latestCancel by rememberUpdatedState(dragCancel)
    val pill=pillHeightDp(task.minutes)
    val color=blockColor(task)
    val start=target?.clockMinute?:task.clockMinutes
    val progress=now?.takeIf{!task.done&&it>=task.clockMinutes&&it<task.clockMinutes+task.minutes}?.let{(it-task.clockMinutes).toFloat()/task.minutes.coerceAtLeast(1)}
    // While held the task follows the finger with no lag; on release it springs home.
    val follow by animateFloatAsState(liftDp*density,if(lifted)snap() else spring(dampingRatio=.82f,stiffness=Spring.StiffnessMediumLow),label="follow")
    val lift by animateFloatAsState(if(lifted)1f else 0f,spring(dampingRatio=.75f,stiffness=Spring.StiffnessMedium),label="lift")
    // When the list reorders (this task dropped elsewhere, or another one moved
    // past it) the row starts from where it was drawn and slides to its slot.
    val settle=remember{Animatable(0f)}
    var placedTop by remember{mutableStateOf<Float?>(null)}
    LaunchedEffect(target?.clockMinute,lifted){if(lifted&&target!=null)haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)}
    val timeColor=if(lifted)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
    Row(Modifier.fillMaxWidth().height((pill+2*ROW_PADDING_DP).dp).zIndex(if(lifted||lift>0f)10f else 0f)
        .onPlaced{coords->
            val top=coords.positionInParent().y;val previous=placedTop;placedTop=top
            if(previous!=null&&previous!=top)scope.launch{settle.snapTo(settle.value+previous-top);settle.animateTo(0f,spring(dampingRatio=.85f,stiffness=Spring.StiffnessMediumLow))}
        }
        .graphicsLayer{
            translationY=follow+settle.value
            val scale=1f+.03f*lift;scaleX=scale;scaleY=scale
            shadowElevation=14.dp.toPx()*lift;shape=RoundedCornerShape(18.dp);clip=false
        }
        .onGloballyPositioned{windowY=it.positionInWindow().y}
        .pointerInput(task.id,interactive){if(interactive)detectDragGesturesAfterLongPress(
            onDragStart={haptic.performHapticFeedback(HapticFeedbackType.LongPress);latestStart()},
            onDrag={change,amount->change.consume();latestMove(amount,windowY+change.position.y)},
            onDragEnd={latestEnd()},onDragCancel={latestCancel()})}
        .clickable(enabled=interactive,onClick=edit)
        .semantics{contentDescription="${task.title}, ${displayClock(task.clockMinutes,twelve)} to ${displayClock(task.clockMinutes+task.minutes,twelve)}, ${durationLabel(task.minutes)}${if(task.done)", done" else ""}. Hold and drag to reschedule"},
        verticalAlignment=Alignment.CenterVertically){
        Column(Modifier.width(62.dp).fillMaxHeight().padding(vertical=ROW_PADDING_DP.dp),horizontalAlignment=Alignment.End,verticalArrangement=Arrangement.SpaceBetween){
            Text(if(showsStart||lifted)displayClock(start,twelve) else "",fontSize=11.sp,color=timeColor,maxLines=1)
            Text(displayClock(start+task.minutes,twelve),fontSize=11.sp,color=timeColor,maxLines=1)
        }
        Spacer(Modifier.width(12.dp))
        val spine=MaterialTheme.colorScheme.outlineVariant
        Box(Modifier.width(52.dp).fillMaxHeight(),contentAlignment=Alignment.Center){
            Canvas(Modifier.fillMaxSize()){
                val x=size.width/2;val top=if(first)size.height/2 else 0f;val bottom=if(last)size.height/2 else size.height
                if(!lifted&&bottom>top)drawLine(spine,Offset(x,top),Offset(x,bottom),strokeWidth=2.dp.toPx())
            }
            Box(Modifier.width(52.dp).height(pill.dp).clip(RoundedCornerShape(26.dp))
                .background(color.copy(alpha=if(task.done).4f else if(progress!=null).38f else 1f))){
                progress?.let{Box(Modifier.fillMaxWidth().fillMaxHeight(it).background(color))}
                Icon(taskIcon(task),null,tint=Color.White,modifier=Modifier.align(Alignment.Center).size(22.dp))
            }
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)){
            val moving=target?.takeIf{it.date!=viewDate}?.date?.format(DateTimeFormatter.ofPattern("EEE d MMM"))?.let{"$it · "}.orEmpty()
            Text("$moving${displayClock(start,twelve)} – ${displayClock(start+task.minutes,twelve)} (${shortDuration(task.minutes)})",fontSize=12.sp,color=timeColor,maxLines=1,overflow=TextOverflow.Ellipsis)
            Row(verticalAlignment=Alignment.CenterVertically){
                Text(task.title,fontSize=17.sp,fontWeight=FontWeight.SemiBold,maxLines=if(pill>64)2 else 1,overflow=TextOverflow.Ellipsis,lineHeight=21.sp,
                    textDecoration=if(task.done)TextDecoration.LineThrough else null,modifier=Modifier.weight(1f,fill=false),
                    color=if(task.done)MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface)
                if(task.starred)Icon(Icons.Rounded.Star,"Top Win",tint=MaterialTheme.colorScheme.primary,modifier=Modifier.padding(start=4.dp).size(14.dp))
            }
        }
        if(TimerPreferences.enabled(LocalContext.current)&&!task.done)IconButton(onClick=focus,enabled=interactive,modifier=Modifier.size(36.dp)){
            Icon(if(timing)Icons.Rounded.HourglassBottom else Icons.Rounded.PlayArrow,"Start focus timer for ${task.title}",tint=color,modifier=Modifier.size(20.dp))
        }
        IconButton(onClick=done,enabled=interactive,modifier=Modifier.size(44.dp)){
            Icon(if(task.done)Icons.Rounded.CheckCircle else Icons.Rounded.RadioButtonUnchecked,"${if(task.done)"Reopen" else "Complete"} ${task.title}",tint=color,modifier=Modifier.size(28.dp))
        }
    }
}

/** Free time: a dotted spine and how long it lasts, or how long until the next task. Tap to add a task there. */
@Composable private fun GapRow(entry:GapEntry,now:Int?,add:()->Unit){
    val isNow=now!=null&&now>=entry.start&&now<entry.start+entry.minutes
    val spine=MaterialTheme.colorScheme.outlineVariant
    Row(Modifier.fillMaxWidth().height(gapHeightDp(entry.minutes).dp).clickable(onClick=add),verticalAlignment=Alignment.CenterVertically){
        Spacer(Modifier.width(74.dp))
        Canvas(Modifier.width(52.dp).fillMaxHeight()){
            val x=size.width/2
            drawLine(spine,Offset(x,0f),Offset(x,size.height),strokeWidth=2.dp.toPx(),cap=StrokeCap.Round,
                pathEffect=PathEffect.dashPathEffect(floatArrayOf(1.dp.toPx(),6.dp.toPx())))
        }
        Spacer(Modifier.width(12.dp))
        Text(if(isNow)"Now · ${shortDuration(entry.start+entry.minutes-now!!)} until ${entry.next}" else "${shortDuration(entry.minutes)} free",
            fontSize=12.sp,maxLines=1,overflow=TextOverflow.Ellipsis,
            color=if(isNow)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
