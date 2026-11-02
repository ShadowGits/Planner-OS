package dev.planneros.android

import android.text.format.DateFormat
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.luminance
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
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import kotlin.math.abs
import kotlin.math.roundToInt

// The day laid out as Structured lays it out (docs/structured-ux.md): time runs
// down the page at 1.6 dp a minute, each task a capsule on a spine, free time
// between them, untimed tasks as round chips on top. The Apple app follows the
// same rules in TimelinePolicy.swift.

internal sealed interface DayEntry { val key:String }
internal data class TaskEntry(val task:Task,val showsStart:Boolean):DayEntry { override val key get()=task.id }
/** Free time between tasks, and the task that follows it. */
internal data class GapEntry(val start:Int,val minutes:Int,val next:String):DayEntry { override val key get()="gap-$start" }
/** Tasks that run at the same time, side by side in their own columns, each
 *  placed by its own clock rather than stacked as though they were a queue.
 *  Two things at once is a decision, not a mistake, so nothing is hidden and
 *  nothing is moved. */
internal data class OverlapEntry(val placed:List<Placed>,val start:Int,val end:Int,val columns:Int,val showsStart:Boolean=true):DayEntry {
    override val key get()="overlap-$start-${placed.size}"
    /** Where one task sits inside the group: which column, and how far down. */
    data class Placed(val task:Task,val column:Int,val topDp:Float,val heightDp:Float)
}

/** Which column each task takes, so that tasks running at the same time never
 *  share one. The first free column is reused, as a calendar does, so two
 *  tasks that merely touch end-to-end stay in the same column. */
private fun columnsFor(group:List<Task>):Map<String,Int> {
    val ends=mutableListOf<Int>();val out=mutableMapOf<String,Int>()
    for(task in group){
        val start=task.clockMinutes
        val free=ends.indexOfFirst{it<=start}
        val column=if(free>=0)free else ends.size.also{ends.add(0)}
        ends[column]=start+task.minutes.coerceAtLeast(1)
        out[task.id]=column
    }
    return out
}

/** Timed tasks in order, with free time of five minutes or more between them.
 *  A start time shows only where it is not the previous task's end. Tasks that
 *  run over each other become one side-by-side group. */
internal fun dayEntries(tasks:List<Task>):List<DayEntry> {
    val timed=tasks.filter{it.time!=null}.sortedWith(compareBy<Task>{it.clockMinutes}.thenBy{it.title})
    // Everything that overlaps, directly or through a third task, belongs together.
    val groups=mutableListOf<MutableList<Task>>();var groupEnd=Int.MIN_VALUE
    for(task in timed){
        if(groups.isEmpty()||task.clockMinutes>=groupEnd){groups+=mutableListOf(task);groupEnd=task.clockMinutes+task.minutes.coerceAtLeast(1)}
        else{groups.last()+=task;groupEnd=maxOf(groupEnd,task.clockMinutes+task.minutes.coerceAtLeast(1))}
    }

    val entries=mutableListOf<DayEntry>();var lastEnd:Int?=null
    for(group in groups){
        val start=group.first().clockMinutes
        val end=group.maxOf{it.clockMinutes+it.minutes.coerceAtLeast(1)}
        lastEnd?.let{previous->if(start-previous>=5)entries+=GapEntry(previous,start-previous,group.first().title)}
        if(group.size==1)entries+=TaskEntry(group.first(),lastEnd!=start)
        else{
            val columns=columnsFor(group)
            val width=(columns.values.maxOrNull()?:0)+1
            // Each task sits where its own start time falls, except where that
            // would let two in the same column touch: a 5-minute task is drawn
            // 48 dp tall, which is taller than its five minutes.
            val bottoms=MutableList(width){0f}
            val placed=group.map{task->
                val column=columns.getValue(task.id)
                val height=pillHeightDp(task.minutes)
                val top=maxOf((task.clockMinutes-start)*MINUTE_DP,bottoms[column])
                bottoms[column]=top+height+2f
                OverlapEntry.Placed(task,column,top,height)
            }
            entries+=OverlapEntry(placed,start,end,width,showsStart=lastEnd!=start)
        }
        lastEnd=maxOf(lastEnd?:0,end)
    }
    return entries
}

/** Structured's scale: two hours is about 190 dp. */
internal const val MINUTE_DP=1.6f
/** Capsule width, and the height of the shortest task (a circle). */
internal const val PILL_DP=48f
internal const val ROW_PADDING_DP=4f
internal const val TIME_COLUMN_DP=44f
/** The latest start a drag can reach: 27:55, five to four the next morning. The planner's day
 *  runs to 04:00 (LOGICAL_DAY_CUTOFF), and the old timeline let a task go that far without
 *  leaving the day; the server lists such a task on this day as 25:30 and so on. */
internal const val LAST_START=27*60+55

internal fun pillHeightDp(minutes:Int)=(minutes*MINUTE_DP).coerceIn(PILL_DP,640f)
/** A few minutes is a short piece of spine; free time keeps the scale; a long window is capped. */
internal fun gapHeightDp(minutes:Int)=when{minutes<30->16f;minutes<180->maxOf(minutes*MINUTE_DP,64f);else->104f}
internal fun entryHeightDp(entry:DayEntry)=when(entry){
    is TaskEntry->pillHeightDp(entry.task.minutes)+2*ROW_PADDING_DP
    is GapEntry->gapHeightDp(entry.minutes)
    is OverlapEntry->entry.placed.maxOf{it.topDp+it.heightDp}+2*ROW_PADDING_DP
}
/** How far down the list an item starts, for scrolling to it and for drags. */
internal fun entryOffsetDp(entries:List<DayEntry>,key:String):Float? {
    var y=0f
    for(entry in entries){if(entry.key==key)return y;y+=entryHeightDp(entry)}
    return null
}

private fun snapFive(minute:Float)=((minute/5f).roundToInt()*5).coerceIn(0,LAST_START)
private fun firstStart(entries:List<DayEntry>)=entries.firstNotNullOfOrNull{
    when(it){is TaskEntry->it.task.clockMinutes;is OverlapEntry->it.start;else->null}
}

/** The time at a point of the list, y in dp from its top, snapped to five minutes. Inside a
 *  capsule time runs over its duration, inside free time over the gap, beyond the ends at scale. */
internal fun minuteAtDp(y:Float,entries:List<DayEntry>):Int {
    if(y<0f)return snapFive((firstStart(entries)?:9*60)+y/MINUTE_DP)
    var top=0f;var end:Int?=null
    for(entry in entries){
        val height=entryHeightDp(entry)
        when(entry){
            is TaskEntry->{
                val task=entry.task
                if(y<top+height){
                    val inside=((y-top-ROW_PADDING_DP)/pillHeightDp(task.minutes)).coerceIn(0f,1f)
                    return snapFive(task.clockMinutes+inside*task.minutes)
                }
                end=maxOf(end?:0,task.clockMinutes+task.minutes)
            }
            is GapEntry->{
                if(y<top+height)return snapFive(entry.start+(y-top)/height*entry.minutes)
                end=entry.start+entry.minutes
            }
            is OverlapEntry->{
                // Time runs evenly over a group: the columns inside it are a
                // way of drawing the same stretch of clock, not more of it.
                if(y<top+height)return snapFive(entry.start+(y-top)/height*(entry.end-entry.start))
                end=maxOf(end?:0,entry.end)
            }
        }
        top+=height
    }
    return snapFive((end?:9*60)+(y-top)/MINUTE_DP)
}

/** Where a time sits in the list: the inverse of minuteAtDp. */
internal fun offsetForDp(minute:Int,entries:List<DayEntry>):Float {
    val first=firstStart(entries)
    if(first!=null&&minute<first)return (minute-first)*MINUTE_DP
    var top=0f;var end:Int?=null
    for(entry in entries){
        val height=entryHeightDp(entry)
        when(entry){
            is TaskEntry->{
                val task=entry.task
                if(minute<task.clockMinutes)return top
                if(minute<task.clockMinutes+task.minutes)
                    return top+ROW_PADDING_DP+(minute-task.clockMinutes).toFloat()/task.minutes.coerceAtLeast(1)*pillHeightDp(task.minutes)
                end=maxOf(end?:0,task.clockMinutes+task.minutes)
            }
            is GapEntry->{
                if(minute<entry.start+entry.minutes)return top+(minute-entry.start).toFloat()/entry.minutes.coerceAtLeast(1)*height
                end=entry.start+entry.minutes
            }
            is OverlapEntry->{
                if(minute<entry.start)return top
                if(minute<entry.end)return top+(minute-entry.start).toFloat()/(entry.end-entry.start).coerceAtLeast(1)*height
                end=maxOf(end?:0,entry.end)
            }
        }
        top+=height
    }
    return top+(minute-(end?:9*60))*MINUTE_DP
}

/** The now bar's height in the list: at the current time's place in the layout, and when now
 *  is before the first task or after the last, just above or below them. Null on other days. */
/** Where the day's tasks finish, for the room below them. */
internal fun lastEnd(entries:List<DayEntry>):Int? = entries.mapNotNull{
    when(it){is TaskEntry->it.task.clockMinutes+it.task.minutes;is OverlapEntry->it.end;else->null}
}.maxOrNull()

/** While a task is held, the timeline carries on below the last task at scale to the end of the
 *  day at 04:00, with room for the held task's capsule, so it can be dropped anywhere until then. */
internal fun nightRoomDp(entries:List<DayEntry>,heldMinutes:Int):Float {
    val end=lastEnd(entries)?:return 0f
    return (LAST_START-end).coerceAtLeast(0)*MINUTE_DP+pillHeightDp(heldMinutes)
}

/** The whole hours shown in that room, after the last task up to 04:00, where the day ends. */
internal fun nightHours(entries:List<DayEntry>):List<Int> {
    val end=lastEnd(entries)?:return emptyList()
    val first=(end+59)/60*60
    return (first..LOGICAL_DAY_CUTOFF+1440 step 60).filter{it-end>=15}
}

internal fun nowBarDp(now:Int,entries:List<DayEntry>):Float? {
    if(entries.isEmpty()||now<0||now>LAST_START+120)return null
    val bottom=entries.sumOf{entryHeightDp(it).toDouble()}.toFloat()
    return offsetForDp(now,entries).coerceIn(-12f,bottom+20f)
}

/** Where a task stands against the clock, which decides how its capsule is filled. */
internal enum class Phase{UPCOMING,UNDERWAY,PAST,DONE}
/** `now` is minutes into the day shown: Int.MAX_VALUE on an earlier day, -1 on a later one. */
internal fun phaseOf(task:Task,now:Int)=when{
    task.done->Phase.DONE
    now>=task.clockMinutes+task.minutes->Phase.PAST
    now>=task.clockMinutes->Phase.UNDERWAY
    else->Phase.UPCOMING
}
internal fun progressOf(task:Task,now:Int)=((now-task.clockMinutes).toFloat()/task.minutes.coerceAtLeast(1)).coerceIn(0f,1f)
internal fun nowOnDay(day:LocalDate,today:LocalDate,nowMinute:Int)=when{day<today->Int.MAX_VALUE;day>today-> -1;else->nowMinute}

/** "15m", "1h", "1h 30m" */
internal fun shortDuration(minutes:Int)=when{minutes<60->"${minutes}m";minutes%60==0->"${minutes/60}h";else->"${minutes/60}h ${minutes%60}m"}
/** "15 min", "1 hr", "1 hr, 30 min", as in the subtitle. */
internal fun durationWords(minutes:Int)=when{minutes<60->"$minutes min";minutes%60==0->"${minutes/60} hr";else->"${minutes/60} hr, ${minutes%60} min"}
internal fun remainingText(task:Task,now:Int)="${shortDuration((task.clockMinutes+task.minutes-now).coerceAtLeast(1))} remaining"
/** "7:00" on a 12-hour phone, "07:00" on a 24-hour one, as in the left column. */
/** "Part 2/3" for a piece of a split task. */
internal fun partText(task:Task):String? = if(task.parent==null)null else "Part ${task.partIndex?:"?"}/${task.partCount?:"?"}"

/** "25m worked · 35m left", or just "1h worked" once it is done. */
internal fun workedText(task:Task):String = "${workDuration(task.workedSeconds)} worked"+if(task.done)"" else " · ${workDuration(task.remainingSeconds)} left"

internal fun columnClock(minute:Int,twelve:Boolean):String {
    val m=Math.floorMod(minute,1440);val hour=m/60
    return if(twelve)"${if(hour%12==0)12 else hour%12}:%02d".format(m%60) else "%02d:%02d".format(hour,m%60)
}
private fun half(minute:Int)=if(Math.floorMod(minute,1440)<720)"AM" else "PM"
/** "7:00 PM", used while dragging. */
internal fun fullClock(minute:Int,twelve:Boolean)=if(twelve)"${columnClock(minute,true)} ${half(minute)}" else columnClock(minute,false)
/** "7:00–7:15 AM", or "11:30 AM–12:15 PM" across noon, or "07:00–07:15". */
internal fun rangeText(start:Int,end:Int,twelve:Boolean)=when{
    !twelve->"${columnClock(start,false)}–${columnClock(end,false)}"
    half(start)==half(end)->"${columnClock(start,true)}–${columnClock(end,true)} ${half(end)}"
    else->"${fullClock(start,true)}–${fullClock(end,true)}"
}
/** Whole hours inside a long task, for the left column. */
internal fun hourMarks(task:Task)=((task.clockMinutes/60+1)..((task.clockMinutes+task.minutes-1)/60)).map{it*60}
    .filter{it-task.clockMinutes>=25&&task.clockMinutes+task.minutes-it>=25}

/** A colour slot that stays the same for a title on every device (the Apple app uses the same hash). */
internal fun paletteIndex(title:String,count:Int):Int {
    var hash=5381UL
    title.codePoints().forEach{hash=hash*33UL+it.toULong()}
    return (hash%count.coerceAtLeast(1).toULong()).toInt()
}

/** Structured's accent. */
internal val Accent=Color(0xFFF19E98)
/** Structured's preset task colours: coral, orange, amber, green, blue, dark green, wine, navy. */
private val blockColors=listOf(Color(0xFFF19E98),Color(0xFFF19C74),Color(0xFFEAA93B),Color(0xFF91BE6C),
    Color(0xFF6085A8),Color(0xFF3A8564),Color(0xFF974667),Color(0xFF2B5073))
internal fun blockColor(task:Task)=blockColors[paletteIndex(task.title,blockColors.size)]
/** The capsule and spine colour of anything still ahead of now. */
@Composable private fun pale()=if(MaterialTheme.colorScheme.background.luminance()<.5f)Color(0xFF2C2C2E) else Color(0xFFEBEBEB)

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

/** "16. October 2025 ›", the year and chevron in the accent colour. */
@Composable internal fun MonthTitle(date:LocalDate){
    Row(verticalAlignment=Alignment.Bottom){
        Text("${date.dayOfMonth}. ${date.format(DateTimeFormatter.ofPattern("MMMM"))}",fontSize=26.sp,fontWeight=FontWeight.Bold,maxLines=1)
        Text(" ${date.year} ›",fontSize=26.sp,fontWeight=FontWeight.Bold,color=Accent,maxLines=1)
    }
}

/** Mon to Sun. The selected day sits in a filled circle (accent when it is today), today
 *  otherwise in accent; under each day, small circles in the colours of its tasks. Swipe for weeks. */
@Composable internal fun StructuredWeekStrip(selected:LocalDate,today:LocalDate,dayColors:(LocalDate)->List<Color>,onSelect:(LocalDate)->Unit){
    val density=LocalDensity.current.density
    val start=selected.minusDays((selected.dayOfWeek.value-1).toLong())
    var dragX by remember{mutableFloatStateOf(0f)}
    val latestSelect by rememberUpdatedState(onSelect)
    val background=MaterialTheme.colorScheme.background
    Row(Modifier.fillMaxWidth().padding(horizontal=8.dp).padding(bottom=10.dp).pointerInput(selected){
        detectHorizontalDragGestures(onDragStart={dragX=0f},onDragEnd={
            if(abs(dragX)>60*density)latestSelect(selected.plusDays(if(dragX<0)7 else -7))
            dragX=0f
        }){change,amount->change.consume();dragX+=amount}
    }){
        for(index in 0..6){
            val day=start.plusDays(index.toLong());val isSelected=day==selected;val isToday=day==today
            Column(Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).clickable{onSelect(day)}.padding(vertical=4.dp)
                .semantics{contentDescription=day.format(DateTimeFormatter.ofPattern("EEEE, MMMM d"))+if(isSelected)", selected" else ""},
                horizontalAlignment=Alignment.CenterHorizontally){
                Text(day.format(DateTimeFormatter.ofPattern("EEE")),fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(4.dp))
                val fill=when{isSelected&&isToday->Accent;isSelected->MaterialTheme.colorScheme.onSurface;else->Color.Transparent}
                Box(Modifier.size(32.dp).background(fill,CircleShape),contentAlignment=Alignment.Center){
                    Text(day.dayOfMonth.toString(),fontSize=16.sp,fontWeight=FontWeight.SemiBold,
                        color=when{isSelected->MaterialTheme.colorScheme.surface;isToday->Accent;else->MaterialTheme.colorScheme.onSurface})
                }
                Spacer(Modifier.height(5.dp))
                val colors=dayColors(day).take(4)
                Row(Modifier.height(11.dp),horizontalArrangement=Arrangement.spacedBy((-4).dp)){
                    colors.forEach{Box(Modifier.size(11.dp).background(background,CircleShape).padding(1.dp).background(it,CircleShape))}
                }
            }
        }
    }
}

/** Tasks with no time, as round chips. Open: pale circle, icon in the task colour. Done: solid
 *  colour, white icon, label struck through. Hold one to tick it off. */
@OptIn(ExperimentalFoundationApi::class)
@Composable private fun AllDayChips(tasks:List<Task>,enabled:(Task)->Boolean,open:(Task)->Unit,done:(Task)->Unit){
    val pale=pale()
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal=4.dp,vertical=6.dp),horizontalArrangement=Arrangement.spacedBy(14.dp)){
        tasks.forEach{task->
            val color=blockColor(task);val interactive=enabled(task)
            Column(Modifier.width(72.dp).clip(RoundedCornerShape(12.dp))
                .combinedClickable(enabled=interactive,onClick={open(task)},onLongClick={done(task)})
                .semantics{contentDescription="${task.title}, any time${if(task.done)", done" else ""}. Hold to ${if(task.done)"reopen" else "complete"}"},
                horizontalAlignment=Alignment.CenterHorizontally){
                Box(Modifier.size(46.dp).background(if(task.done)color else pale,CircleShape),contentAlignment=Alignment.Center){
                    Icon(taskIcon(task),null,tint=if(task.done)Color.White else color,modifier=Modifier.size(22.dp))
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
 * The day's timeline. MainActivity drives a drag (DragState and DragPreview, with
 * edge auto-scroll); this draws it as Structured does: the held task leaves an
 * empty place, a compact chip follows the finger, and an outlined capsule shows
 * where it will land, with the new start and end in bold on the left. Nothing
 * else moves until it is dropped.
 */
@Composable internal fun StructuredTimeline(tasks:List<Task>,allDay:List<Task>,date:LocalDate,now:Int,timerId:String?,
    enabled:Boolean,scroll:ScrollState,preview:DragPreview?,modifier:Modifier=Modifier,
    edit:(Task)->Unit,done:(Task)->Unit,star:(Task)->Unit,focus:(Task)->Unit,gap:(Int)->Unit,
    dragStart:(Task)->Unit,dragMove:(Task,Offset,Offset)->Unit,dragEnd:(Task)->Unit,dragCancel:()->Unit,
    viewport:(Float,Float)->Unit){
    val entries=remember(tasks){dayEntries(tasks)}
    val config=LocalViewConfiguration.current
    val holdConfig=remember(config){object:ViewConfiguration by config{override val longPressTimeoutMillis=300L}}
    val twelve=!DateFormat.is24HourFormat(LocalContext.current)
    val tasksById=entries.flatMap{entry->
        when(entry){is TaskEntry->listOf(entry.task);is OverlapEntry->entry.placed.map{it.task};else->emptyList()}
    }.associateBy{it.id}
    CompositionLocalProvider(LocalViewConfiguration provides holdConfig){
        Column(modifier.onGloballyPositioned{val y=it.positionInWindow().y;viewport(y,y+it.size.height)}
            .verticalScroll(scroll).padding(start=12.dp,end=8.dp,top=6.dp,bottom=110.dp)){
            if(allDay.isNotEmpty()){
                AllDayChips(allDay,{enabled&&!it.id.startsWith("pending:")},edit,done)
                Spacer(Modifier.height(10.dp))
            }
            if(entries.isEmpty())Text(if(allDay.isEmpty())"Nothing planned. Tap + to add a task." else "Nothing at a set time. Tap + to add one.",
                color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.fillMaxWidth().padding(top=48.dp),textAlign=TextAlign.Center)
            Box{
                Column{
                    entries.forEachIndexed{index,entry->
                        key(entry.key){
                            when(entry){
                                is TaskEntry->TaskRow(entry.task,entry.showsStart,index==0,index==entries.lastIndex,now,twelve,
                                    enabled&&!entry.task.id.startsWith("pending:"),timerId==entry.task.id,hidden=preview?.taskId==entry.task.id,
                                    edit={edit(entry.task)},done={done(entry.task)},star={star(entry.task)},focus={focus(entry.task)},
                                    dragStart={dragStart(entry.task)},dragMove={delta,pointer->dragMove(entry.task,delta,pointer)},
                                    dragEnd={dragEnd(entry.task)},dragCancel=dragCancel)
                                is OverlapEntry->OverlapRow(entry,now,twelve,enabled,timerId,
                                    hiddenId=preview?.taskId,edit=edit,done=done,
                                    dragStart=dragStart,dragMove=dragMove,dragEnd=dragEnd,dragCancel=dragCancel)
                                is GapEntry->GapRow(entry,
                                    (entries.getOrNull(index-1) as? TaskEntry)?.task?.let(::blockColor),
                                    (entries.getOrNull(index+1) as? TaskEntry)?.task?.let(::blockColor),now,twelve){gap(((entry.start+4)/5)*5)}
                            }
                        }
                    }
                    // While a task is held: the night, down to 04:00 the next morning.
                    preview?.let{drag->tasksById[drag.taskId]?.let{held->
                        val landing=visibleMinute(date,drag.target)
                        NightRoom(entries,held.minutes,date,twelve,listOfNotNull(landing,landing?.plus(held.minutes)))
                    }}
                }
                nowBarDp(now,entries)?.let{NowBar(it,columnClock(now,twelve))}
                preview?.let{drag->tasksById[drag.taskId]?.let{task->DragOverlay(task,drag,entries,date,twelve)}}
            }
        }
    }
}

/** Below the last task while one is held: time carries on at scale to 04:00 the next morning,
 *  with faint hours and the next day named at midnight, so a task can be dropped there. */
@Composable private fun NightRoom(entries:List<DayEntry>,heldMinutes:Int,date:LocalDate,twelve:Boolean,bold:List<Int>){
    val end=lastEnd(entries)?:return
    val faint=MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha=.6f)
    val spine=pale()
    Box(Modifier.fillMaxWidth().height(nightRoomDp(entries,heldMinutes).dp).clearAndSetSemantics{}){
        Canvas(Modifier.fillMaxSize()){
            val x=(TIME_COLUMN_DP+4+PILL_DP/2).dp.toPx()
            drawLine(spine,Offset(x,0f),Offset(x,((LAST_START-end).coerceAtLeast(0)*MINUTE_DP).dp.toPx()),strokeWidth=3.dp.toPx(),
                pathEffect=PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(),6.dp.toPx())))
        }
        // An hour next to the landing's bold times gives way to them.
        nightHours(entries).filter{hour->bold.none{abs(it-hour)*MINUTE_DP<14f}}.forEach{hour->
            Row(Modifier.offset(y=((hour-end)*MINUTE_DP-7f).dp),verticalAlignment=Alignment.CenterVertically){
                Text(columnClock(hour,twelve),fontSize=11.sp,color=faint,maxLines=1,modifier=Modifier.width(TIME_COLUMN_DP.dp))
                if(hour==1440)Text(date.plusDays(1).format(DateTimeFormatter.ofPattern("EEE d MMM")),fontSize=11.sp,fontWeight=FontWeight.SemiBold,
                    color=faint,maxLines=1,modifier=Modifier.padding(start=(4+PILL_DP+12).dp))
            }
        }
    }
}

/** The now bar: the current time in bold, a small dot on the spine and a very subtle line across. */
@Composable private fun NowBar(y:Float,label:String){
    Box(Modifier.offset(y=(y-8f).dp).fillMaxWidth().height(16.dp).zIndex(4f)
        .semantics{contentDescription="Now, $label"}){
        Text(label,fontSize=11.sp,fontWeight=FontWeight.Bold,color=MaterialTheme.colorScheme.onSurface,maxLines=1,
            modifier=Modifier.align(Alignment.CenterStart))
        Canvas(Modifier.fillMaxSize()){
            val x=(TIME_COLUMN_DP+4+PILL_DP/2).dp.toPx();val mid=size.height/2
            // Very subtle: a hairline, faint, with a small dot on the spine.
            drawLine(Accent.copy(alpha=.35f),Offset(x,mid),Offset(size.width,mid),strokeWidth=1.dp.toPx())
            drawCircle(Accent,radius=3.dp.toPx(),center=Offset(x,mid))
        }
    }
}

/** The landing outline with its bold times, and the chip that follows the finger. */
@Composable private fun DragOverlay(task:Task,drag:DragPreview,entries:List<DayEntry>,date:LocalDate,twelve:Boolean){
    // After midnight up to 04:00 still lands in this day's view, as minutes past 24:00.
    val onDay=visibleMinute(date,drag.target)
    val sameDay=drag.target.date==date
    val start=onDay?:drag.target.clockMinute
    val pill=pillHeightDp(task.minutes)
    val white=if(MaterialTheme.colorScheme.background.luminance()<.5f)Color(0xFF2C2C2E) else Color.White
    if(onDay!=null){
        val top=offsetForDp(start,entries)
        Box(Modifier.offset(y=top.dp).fillMaxWidth().height(pill.dp).zIndex(5f).clearAndSetSemantics{}){
            Text(fullClock(start,twelve),fontSize=10.sp,fontWeight=FontWeight.Bold,maxLines=1,modifier=Modifier.offset(y=(-6).dp))
            Text(fullClock(start+task.minutes,twelve),fontSize=10.sp,fontWeight=FontWeight.Bold,maxLines=1,modifier=Modifier.align(Alignment.BottomStart).offset(y=6.dp))
            Box(Modifier.padding(start=(TIME_COLUMN_DP+4).dp).size(PILL_DP.dp,pill.dp).background(white,RoundedCornerShape(50))
                .border(1.5.dp,Color(0xFFB8B8BD),RoundedCornerShape(50)))
        }
    }
    val rowTop=(entryOffsetDp(entries,task.id)?:0f)+ROW_PADDING_DP
    val color=blockColor(task)
    // White, and beside the outline rather than over it, as in Structured.
    Surface(shape=RoundedCornerShape(28.dp),shadowElevation=10.dp,color=white,
        // Drawn only: the row itself already tells a screen reader about the task.
        modifier=Modifier.offset(x=(TIME_COLUMN_DP+4+PILL_DP+16).dp,y=(rowTop+drag.deltaDp).dp).zIndex(10f).clearAndSetSemantics{}){
        Row(Modifier.padding(start=6.dp,end=14.dp,top=6.dp,bottom=6.dp),verticalAlignment=Alignment.CenterVertically){
            Box(Modifier.size(36.dp).background(color,CircleShape),contentAlignment=Alignment.Center){Icon(taskIcon(task),null,tint=Color.White,modifier=Modifier.size(18.dp))}
            Spacer(Modifier.width(8.dp))
            Column{
                val day=if(sameDay)"" else drag.target.date.format(DateTimeFormatter.ofPattern("EEE d MMM"))+" · "
                Text(day+rangeText(start,start+task.minutes,twelve)+" (${durationWords(task.minutes)})",fontSize=10.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,maxLines=1)
                Text(task.title,fontSize=13.sp,fontWeight=FontWeight.SemiBold,maxLines=1,overflow=TextOverflow.Ellipsis,modifier=Modifier.widthIn(max=180.dp))
            }
        }
    }
}

/** The left column: start and end, and whole hours inside long tasks. Labels next to the now
 *  bar give way to its bold time. */
@Composable private fun TimeColumn(height:Float,labels:List<Pair<Float,String>>,nowLabel:Pair<Float,String>?){
    Box(Modifier.width(TIME_COLUMN_DP.dp).height(height.dp)){
        labels.filter{label->nowLabel==null||abs(label.first-nowLabel.first)>14f}.forEach{(y,text)->
            Text(text,fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,maxLines=1,modifier=Modifier.offset(y=(y-7f).dp))
        }
    }
}

@Composable private fun TaskRow(task:Task,showsStart:Boolean,first:Boolean,last:Boolean,now:Int,twelve:Boolean,
    interactive:Boolean,timing:Boolean,hidden:Boolean,
    edit:()->Unit,done:()->Unit,star:()->Unit,focus:()->Unit,dragStart:()->Unit,dragMove:(Offset,Offset)->Unit,dragEnd:()->Unit,dragCancel:()->Unit){
    val haptic=LocalHapticFeedback.current
    val scope=rememberCoroutineScope()
    var windowPosition by remember{mutableStateOf(Offset.Zero)}
    val latestStart by rememberUpdatedState(dragStart);val latestMove by rememberUpdatedState(dragMove)
    val latestEnd by rememberUpdatedState(dragEnd);val latestCancel by rememberUpdatedState(dragCancel)
    val pill=pillHeightDp(task.minutes);val rowHeight=pill+2*ROW_PADDING_DP
    val color=blockColor(task);val pale=pale()
    val phase=phaseOf(task,now);val progress=progressOf(task,now)
    val start=task.clockMinutes;val end=start+task.minutes
    val solid=phase==Phase.PAST||phase==Phase.DONE
    // When the list reorders the row starts from where it was drawn and slides to its place.
    val settle=remember{Animatable(0f)}
    var placedTop by remember{mutableStateOf<Float?>(null)}
    val labels=buildList{
        if(showsStart)add(ROW_PADDING_DP+6f to columnClock(start,twelve))
        hourMarks(task).forEach{add(ROW_PADDING_DP+(it-start).toFloat()/task.minutes*pill to columnClock(it,twelve))}
        add(ROW_PADDING_DP+pill-6f to columnClock(end,twelve))
    }
    val nowLabel=if(phase==Phase.UNDERWAY||(phase==Phase.DONE&&now in start until end))(ROW_PADDING_DP+progress*pill) to columnClock(now,twelve) else null
    Row(Modifier.fillMaxWidth().height(rowHeight.dp)
        .onPlaced{coords->
            val top=coords.positionInParent().y;val previous=placedTop;placedTop=top
            if(previous!=null&&previous!=top)scope.launch{settle.snapTo(settle.value+previous-top);settle.animateTo(0f,spring(dampingRatio=.85f,stiffness=Spring.StiffnessMediumLow))}
        }
        // The drag is read on the row's fixed place, before the layer that moves it.
        .onGloballyPositioned{windowPosition=it.positionInWindow()}
        .pointerInput(task.id,interactive){if(interactive)detectDragGesturesAfterLongPress(
            onDragStart={haptic.performHapticFeedback(HapticFeedbackType.LongPress);latestStart()},
            onDrag={change,amount->change.consume();latestMove(amount,windowPosition+change.position)},
            onDragEnd={latestEnd()},onDragCancel={latestCancel()})}
        .graphicsLayer{translationY=settle.value}
        .clickable(enabled=interactive,onClick=edit)
        .semantics{contentDescription="${task.title}, ${fullClock(start,twelve)} to ${fullClock(end,twelve)}, ${durationWords(task.minutes)}${if(task.starred)", Top Win" else ""}${if(task.done)", done" else ""}. Hold and drag to reschedule"},
        verticalAlignment=Alignment.CenterVertically){
        TimeColumn(rowHeight,if(hidden)emptyList() else labels,if(hidden)null else nowLabel)
        Spacer(Modifier.width(4.dp))
        Box(Modifier.width(PILL_DP.dp).fillMaxHeight(),contentAlignment=Alignment.Center){
            Canvas(Modifier.fillMaxSize()){
                val x=size.width/2;val stroke=3.dp.toPx()
                val top=if(first)size.height/2 else 0f;val bottom=if(last)size.height/2 else size.height
                if(bottom>top){
                    drawLine(pale,Offset(x,top),Offset(x,bottom),strokeWidth=stroke)
                    val reached=when{now>=end->bottom;now<=start->top;else->(ROW_PADDING_DP+progress*pill).dp.toPx().coerceIn(top,bottom)}
                    if(reached>top)drawLine(color,Offset(x,top),Offset(x,reached),strokeWidth=stroke)
                }
            }
            Box(Modifier.alpha(if(hidden)0f else 1f).size(PILL_DP.dp,pill.dp).clip(RoundedCornerShape(50)).background(if(solid)color else pale)){
                if(phase==Phase.UNDERWAY)Box(Modifier.fillMaxWidth().fillMaxHeight(progress.coerceAtLeast(.02f))
                    .background(Brush.verticalGradient(0f to color,.8f to color,1f to color.copy(alpha=.4f))))
                Icon(taskIcon(task),null,tint=if(solid||(phase==Phase.UNDERWAY&&progress>.5f))Color.White else color,
                    modifier=Modifier.align(Alignment.Center).size(22.dp))
            }
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f).alpha(if(hidden)0f else 1f)){
            Row(verticalAlignment=Alignment.CenterVertically){
                Text(if(phase==Phase.UNDERWAY)remainingText(task,now) else "${rangeText(start,end,twelve)} (${durationWords(task.minutes)})",
                    fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,maxLines=1,overflow=TextOverflow.Ellipsis,modifier=Modifier.weight(1f,fill=false))
                if(task.recurrenceKey!=null||task.habit)Icon(Icons.Rounded.Repeat,"Repeats",tint=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(start=3.dp).size(12.dp))
                partText(task)?.let{Text(" · $it",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,maxLines=1)}
            }
            Text(task.title,fontSize=17.sp,fontWeight=FontWeight.SemiBold,maxLines=if(pill>60)2 else 1,overflow=TextOverflow.Ellipsis,lineHeight=21.sp,
                textDecoration=if(task.done)TextDecoration.LineThrough else null,
                color=if(task.done)MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface)
            if(TimerPreferences.enabled(LocalContext.current)&&task.workedSeconds>0)
                Text(workedText(task),fontSize=11.sp,fontWeight=FontWeight.Medium,color=color,maxLines=1,overflow=TextOverflow.Ellipsis)
        }
        // Next to the tick, the star keeps the same place on every row.
        if(TimerPreferences.enabled(LocalContext.current)&&!task.done&&!hidden)IconButton(onClick=focus,enabled=interactive,modifier=Modifier.size(36.dp)){
            Icon(if(timing)Icons.Rounded.HourglassBottom else Icons.Rounded.PlayArrow,"Start focus timer for ${task.title}",tint=color,modifier=Modifier.size(20.dp))
        }
        // Top Win: tap the star, as on the old timeline.
        IconButton(onClick=star,enabled=interactive,modifier=Modifier.size(32.dp).alpha(if(hidden)0f else 1f)){
            Icon(if(task.starred)Icons.Rounded.Star else Icons.Rounded.StarBorder,"${if(task.starred)"Remove" else "Choose"} ${task.title} as Top Win",
                tint=if(task.starred)Accent else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha=.55f),modifier=Modifier.size(18.dp))
        }
        IconButton(onClick=done,enabled=interactive,modifier=Modifier.size(44.dp).alpha(if(hidden)0f else 1f)
            .semantics{contentDescription="${if(task.done)"Reopen" else "Complete"} ${task.title}"}){
            Box(Modifier.size(24.dp).then(if(task.done)Modifier.background(color,CircleShape) else Modifier.border(2.dp,color,CircleShape)),contentAlignment=Alignment.Center){
                if(task.done)Icon(Icons.Rounded.Check,null,tint=Color.White,modifier=Modifier.size(16.dp))
            }
        }
    }
}

/**
 * Tasks that run at the same time, drawn beside each other.
 *
 * The single-file row cannot say this: stacked, two things at eleven look like
 * one at eleven and one after it. Here each column is its own task, placed by
 * its own clock, so an overlap reads as an overlap. Nothing is moved and
 * nothing is hidden — running two things at once is a choice.
 */
@Composable private fun OverlapRow(entry:OverlapEntry,now:Int,twelve:Boolean,enabled:Boolean,timerId:String?,
    hiddenId:String?,edit:(Task)->Unit,done:(Task)->Unit,
    dragStart:(Task)->Unit,dragMove:(Task,Offset,Offset)->Unit,dragEnd:(Task)->Unit,dragCancel:()->Unit){
    val height=entryHeightDp(entry)
    // The start is already printed as the previous task's end when they meet.
    val labels=buildList{
        if(entry.showsStart)add(ROW_PADDING_DP+6f to columnClock(entry.start,twelve))
        add(height-ROW_PADDING_DP-6f to columnClock(entry.end,twelve))
    }
    Row(Modifier.fillMaxWidth().height(height.dp)){
        TimeColumn(height,labels,null)
        Spacer(Modifier.width(4.dp))
        BoxWithConstraints(Modifier.weight(1f).fillMaxHeight()){
            val columnWidth=maxWidth/entry.columns
            entry.placed.forEach{placed->
                key(placed.task.id){
                    OverlapBlock(placed,entry.columns,columnWidth,now,twelve,
                        interactive=enabled&&!placed.task.id.startsWith("pending:"),
                        timing=timerId==placed.task.id,hidden=hiddenId==placed.task.id,
                        edit={edit(placed.task)},done={done(placed.task)},
                        dragStart={dragStart(placed.task)},dragMove={d,p->dragMove(placed.task,d,p)},
                        dragEnd={dragEnd(placed.task)},dragCancel=dragCancel)
                }
            }
        }
    }
}

/** One task inside a side-by-side group: its own block, in its own column. */
@Composable private fun OverlapBlock(placed:OverlapEntry.Placed,columns:Int,columnWidth:Dp,now:Int,twelve:Boolean,
    interactive:Boolean,timing:Boolean,hidden:Boolean,edit:()->Unit,done:()->Unit,
    dragStart:()->Unit,dragMove:(Offset,Offset)->Unit,dragEnd:()->Unit,dragCancel:()->Unit){
    val task=placed.task
    val haptic=LocalHapticFeedback.current
    var windowPosition by remember{mutableStateOf(Offset.Zero)}
    val latestStart by rememberUpdatedState(dragStart);val latestMove by rememberUpdatedState(dragMove)
    val latestEnd by rememberUpdatedState(dragEnd);val latestCancel by rememberUpdatedState(dragCancel)
    val color=blockColor(task);val pale=pale()
    val phase=phaseOf(task,now);val progress=progressOf(task,now)
    val solid=phase==Phase.PAST||phase==Phase.DONE
    val start=task.clockMinutes;val end=start+task.minutes
    val narrow=columns>2
    Box(Modifier.offset(x=columnWidth*placed.column,y=(ROW_PADDING_DP+placed.topDp).dp)
        .width(columnWidth-4.dp).height(placed.heightDp.dp)
        .alpha(if(hidden)0f else 1f)
        .onGloballyPositioned{windowPosition=it.positionInWindow()}
        .pointerInput(task.id,interactive){if(interactive)detectDragGesturesAfterLongPress(
            onDragStart={haptic.performHapticFeedback(HapticFeedbackType.LongPress);latestStart()},
            onDrag={change,amount->change.consume();latestMove(amount,windowPosition+change.position)},
            onDragEnd={latestEnd()},onDragCancel={latestCancel()})}
        .clip(RoundedCornerShape(14.dp))
        .background(if(solid)color else pale)
        .clickable(enabled=interactive,onClick=edit)
        .semantics{contentDescription="${task.title}, ${fullClock(start,twelve)} to ${fullClock(end,twelve)}, ${durationWords(task.minutes)}, at the same time as ${columns-1} other${if(columns==2)"" else "s"}. Hold and drag to reschedule"}){
        if(phase==Phase.UNDERWAY)Box(Modifier.fillMaxWidth().fillMaxHeight(progress.coerceAtLeast(.02f))
            .background(Brush.verticalGradient(0f to color,.8f to color,1f to color.copy(alpha=.4f))))
        val ink=if(solid||(phase==Phase.UNDERWAY&&progress>.5f))Color.White else color
        val words=if(solid)Color.White else MaterialTheme.colorScheme.onSurface
        // A 30-minute block is one line tall: its own time and a tick below the
        // title would be drawn straight through it.
        val roomy=placed.heightDp>=78f
        val title=@Composable{ lines:Int->
            Text(task.title,fontSize=if(narrow)11.sp else 13.sp,fontWeight=FontWeight.SemiBold,
                maxLines=lines,overflow=TextOverflow.Ellipsis,lineHeight=15.sp,
                textDecoration=if(task.done)TextDecoration.LineThrough else null,color=words)
        }
        val tick=@Composable{ size:Dp->
            IconButton(onClick=done,enabled=interactive,modifier=Modifier.size(size)
                .semantics{contentDescription="${if(task.done)"Reopen" else "Complete"} ${task.title}"}){
                Box(Modifier.size(18.dp).then(if(task.done)Modifier.background(color,CircleShape) else Modifier.border(2.dp,ink,CircleShape)),
                    contentAlignment=Alignment.Center){
                    if(task.done)Icon(Icons.Rounded.Check,null,tint=Color.White,modifier=Modifier.size(12.dp))
                }
            }
        }
        // The tick floats in the corner rather than taking a row of its own:
        // stacked under the title it pushed the words out of a short block.
        if(roomy){
            Column(Modifier.fillMaxSize().padding(start=7.dp,top=5.dp,end=30.dp,bottom=4.dp)){
                Row(verticalAlignment=Alignment.CenterVertically){
                    Icon(taskIcon(task),null,tint=ink,modifier=Modifier.size(if(narrow)14.dp else 16.dp))
                    Spacer(Modifier.width(4.dp))
                    if(!narrow)Text(columnClock(start,twelve),fontSize=10.sp,maxLines=1,
                        color=if(solid)Color.White.copy(alpha=.85f) else MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Box(Modifier.weight(1f).padding(top=2.dp)){title(if(placed.heightDp>110f)3 else 2)}
            }
            Box(Modifier.align(Alignment.BottomEnd)){tick(30.dp)}
        }
        else Row(Modifier.fillMaxSize().padding(start=7.dp,end=2.dp),verticalAlignment=Alignment.CenterVertically){
            Icon(taskIcon(task),null,tint=ink,modifier=Modifier.size(14.dp))
            Spacer(Modifier.width(5.dp))
            Box(Modifier.weight(1f)){title(1)}
            tick(30.dp)
        }
    }
}

/** Free time: the spine (coloured up to now, blending from one task's colour to the next), the
 *  current time in bold if now falls here, and Structured's wording. Tap to add a task here. */
@Composable private fun GapRow(entry:GapEntry,previous:Color?,next:Color?,now:Int,twelve:Boolean,add:()->Unit){
    val height=gapHeightDp(entry.minutes)
    val end=entry.start+entry.minutes
    val nowY=if(now>=entry.start&&now<end)(now-entry.start).toFloat()/entry.minutes*height else null
    val pale=pale()
    val from=previous?:next?:pale;val to=next?:previous?:pale
    Row(Modifier.fillMaxWidth().height(height.dp).clickable(onClick=add),verticalAlignment=Alignment.CenterVertically){
        TimeColumn(height,emptyList(),nowY?.let{it to columnClock(now,twelve)})
        Spacer(Modifier.width(4.dp))
        Canvas(Modifier.width(PILL_DP.dp).fillMaxHeight()){
            val x=size.width/2;val stroke=3.dp.toPx()
            drawLine(pale,Offset(x,0f),Offset(x,size.height),strokeWidth=stroke)
            val reached=when{now>=end->size.height;nowY!=null->nowY.dp.toPx();else->0f}
            if(reached>0f)drawLine(Brush.verticalGradient(listOf(from,to),0f,size.height),Offset(x,0f),Offset(x,reached),strokeWidth=stroke)
        }
        Spacer(Modifier.width(12.dp))
        val length=shortDuration(entry.minutes)
        when{
            entry.minutes<30->{}
            entry.minutes<180->Row(verticalAlignment=Alignment.CenterVertically){
                Icon(Icons.Rounded.Schedule,null,tint=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.size(14.dp))
                Spacer(Modifier.width(6.dp))
                Text(buildAnnotatedString{append("You'll have ");withStyle(SpanStyle(color=Accent)){append(length)};append(" free. Anything you'd like to fit in?")},
                    fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,maxLines=2)
            }
            else->Column{
                Row(verticalAlignment=Alignment.CenterVertically){
                    Icon(Icons.Rounded.Schedule,null,tint=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.size(14.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(buildAnnotatedString{append("A window: ");withStyle(SpanStyle(color=Accent)){append(length)};append(" of potential.")},
                        fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,maxLines=1)
                }
                Spacer(Modifier.height(6.dp))
                Surface(onClick=add,shape=RoundedCornerShape(14.dp),color=Accent.copy(alpha=.14f)){
                    Row(Modifier.padding(horizontal=10.dp,vertical=4.dp),verticalAlignment=Alignment.CenterVertically){
                        Icon(Icons.Rounded.AddCircle,null,tint=Accent,modifier=Modifier.size(14.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("Add Task",fontSize=12.sp,fontWeight=FontWeight.SemiBold,color=Accent)
                    }
                }
            }
        }
    }
}

/** A place in the floating bottom pill: icon over label, accent when selected. */
@Composable internal fun RowScope.BottomTab(label:String,icon:ImageVector,selected:Boolean,onClick:()->Unit){
    Column(Modifier.weight(1f).fillMaxHeight().clip(RoundedCornerShape(24.dp)).clickable(onClick=onClick)
        .semantics{contentDescription=label+if(selected)", selected" else ""},
        horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.Center){
        Icon(icon,null,tint=if(selected)Accent else MaterialTheme.colorScheme.onSurface,modifier=Modifier.size(22.dp))
        Text(label,fontSize=11.sp,fontWeight=if(selected)FontWeight.SemiBold else FontWeight.Medium,color=if(selected)Accent else MaterialTheme.colorScheme.onSurface,maxLines=1)
    }
}
