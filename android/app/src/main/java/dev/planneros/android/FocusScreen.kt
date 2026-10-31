package dev.planneros.android

import android.app.DatePickerDialog
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowForward
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

// Enough to see what is most pressing without the whole backlog at once.
private const val OVERDUE_PREVIEW=9

private val GROUPS=listOf(
    FocusReason.DEADLINE to ("Past deadline" to "The due date has gone."),
    FocusReason.MISSED_SLOT to ("Missed slot" to "It was planned for a time that has passed."),
    FocusReason.NEVER_SCHEDULED to ("Never scheduled" to "No date at all."),
)

private fun hours(minutes:Int)=if(minutes<60)"${minutes}m" else (minutes/60.0).let{if(it%1.0==0.0)"${it.toInt()}h" else "%.1fh".format(Locale.ENGLISH,it)}

/** Badge colours for how a task is late, readable in both themes. */
@Composable private fun reasonColors(reason:FocusReason?,dark:Boolean):Pair<Color,Color> = when(reason){
    FocusReason.DEADLINE->if(dark)Color(0x33EF4444) to Color(0xFFFCA5A5) else Color(0xFFFEE2E2) to Color(0xFFB91C1C)
    FocusReason.MISSED_SLOT->if(dark)Color(0x33F59E0B) to Color(0xFFFCD34D) else Color(0xFFFEF3C7) to Color(0xFF92400E)
    FocusReason.NEVER_SCHEDULED->if(dark)Color(0x339CA3AF) to Color(0xFFD1D5DB) else Color(0xFFF3F4F6) to Color(0xFF4B5563)
    null->MaterialTheme.colorScheme.primary.copy(alpha=.10f) to MaterialTheme.colorScheme.primary
}

/**
 * The Focus screen: what is overdue, ranked; what is left today; and the week
 * laid out by milestone. Every change goes back to the caller, which saves it
 * through the same optimistic path as the timeline, so caches, alarms and
 * timers stay in step however a task was moved.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable internal fun FocusScreen(
    overdue:List<Pair<Task,FocusReason>>,
    todayTasks:List<Task>,
    week:Day?,
    milestones:Map<String,FocusMilestone>,
    projectNames:Map<String,String>,
    now:ZonedDateTime,
    today:LocalDate,
    dark:Boolean,
    backlogLoaded:Boolean,
    busy:(Task)->Boolean,
    onOpen:(Task)->Unit,
    onDone:(Task)->Unit,
    onMove:(List<Task>,LocalDate)->Unit,
    onDrop:(List<Task>)->Unit,
    onWeek:(LocalDate)->Unit,
    onOpenDay:(LocalDate)->Unit,
    modifier:Modifier=Modifier,
){
    val context=LocalContext.current
    var showAll by rememberSaveable{mutableStateOf(false)}
    var selected by rememberSaveable{mutableStateOf(setOf<String>())}
    var confirmDrop by remember{mutableStateOf(false)}
    val overdueById=overdue.associateBy{it.first.id}
    // A task that has left the list (moved, done, dropped) cannot stay selected.
    val chosen=overdue.filter{it.first.id in selected}.map{it.first}
    val selecting=chosen.isNotEmpty()

    fun pickDate(onPicked:(LocalDate)->Unit){
        DatePickerDialog(pickerContext(context,dark),{_,y,m,d->LocalDate.of(y,m+1,d).let{if(!it.isBefore(today))onPicked(it)}},
            today.year,today.monthValue-1,today.dayOfMonth).apply{
            datePicker.minDate=today.atStartOfDay(ZoneId.systemDefault()).toInstant().toEpochMilli()
        }.show()
    }
    fun toggle(task:Task){selected=if(task.id in selected)selected-task.id else selected+task.id}

    @Composable fun card(task:Task,reason:FocusReason?,selectable:Boolean){
        val isBusy=busy(task)||task.id.startsWith("pending:")
        val (badgeBg,badgeText)=reasonColors(reason,dark)
        val milestone=task.milestoneId?.let{milestones[it]}
        val where=milestone?.name?:task.projectId?.let{projectNames[it]}
        val isSelected=task.id in selected
        Surface(
            shape=RoundedCornerShape(14.dp),
            color=if(isSelected)MaterialTheme.colorScheme.primary.copy(alpha=.08f)else MaterialTheme.colorScheme.surface,
            border=androidx.compose.foundation.BorderStroke(if(isSelected)1.5.dp else 1.dp,
                if(isSelected)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant.copy(alpha=.6f)),
            modifier=Modifier.fillMaxWidth().padding(horizontal=14.dp,vertical=4.dp)
                .combinedClickable(enabled=!isBusy,
                    onClick={if(selecting&&selectable)toggle(task) else onOpen(task)},
                    onLongClick={if(selectable)toggle(task)},
                    onLongClickLabel="Select for moving or dropping"),
        ){Column(Modifier.padding(start=12.dp,end=6.dp,top=10.dp,bottom=4.dp)){
            Row(verticalAlignment=Alignment.Top){
                if(selecting&&selectable)Checkbox(checked=isSelected,onCheckedChange={toggle(task)},enabled=!isBusy,modifier=Modifier.size(24.dp).padding(end=8.dp))
                if(isPinned(task))Icon(if(task.starred)Icons.Rounded.Star else Icons.Rounded.PriorityHigh,if(task.starred)"Starred" else "High priority",
                    tint=MaterialTheme.colorScheme.primary,modifier=Modifier.padding(top=2.dp,end=4.dp).size(15.dp))
                Text(task.title,fontSize=15.sp,fontWeight=FontWeight.SemiBold,maxLines=2,overflow=TextOverflow.Ellipsis,modifier=Modifier.weight(1f))
            }
            Row(Modifier.padding(top=6.dp).horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(6.dp),verticalAlignment=Alignment.CenterVertically){
                val label=if(reason!=null)lateness(task,reason,now) else task.time?.take(5)?:"Any time today"
                Text(label,fontSize=11.sp,fontWeight=FontWeight.SemiBold,color=badgeText,
                    modifier=Modifier.background(badgeBg,RoundedCornerShape(50)).padding(horizontal=8.dp,vertical=2.dp))
                Text(hours(task.minutes),fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                where?.let{Text(it,fontSize=11.sp,maxLines=1,overflow=TextOverflow.Ellipsis,color=MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier=Modifier.widthIn(max=170.dp).background(MaterialTheme.colorScheme.onSurface.copy(alpha=.06f),RoundedCornerShape(6.dp)).padding(horizontal=6.dp,vertical=1.dp))}
                milestoneSoon(task,milestones,now)?.let{Text(it,fontSize=11.sp,fontWeight=FontWeight.SemiBold,color=Color(0xFF6D28D9),
                    modifier=Modifier.background(Color(0xFFEDE9FE),RoundedCornerShape(6.dp)).padding(horizontal=6.dp,vertical=1.dp))}
            }
            if(!selecting)Row(verticalAlignment=Alignment.CenterVertically){
                TextButton(onClick={onDone(task)},enabled=!isBusy,contentPadding=PaddingValues(horizontal=8.dp)){
                    Icon(Icons.Rounded.Check,null,Modifier.size(16.dp));Spacer(Modifier.width(4.dp));Text("Done",fontSize=13.sp)}
                TextButton(onClick={onMove(listOf(task),today.plusDays(1))},enabled=!isBusy,contentPadding=PaddingValues(horizontal=8.dp)){
                    Icon(Icons.AutoMirrored.Rounded.ArrowForward,null,Modifier.size(16.dp));Spacer(Modifier.width(4.dp));Text("Tomorrow",fontSize=13.sp)}
                TextButton(onClick={pickDate{onMove(listOf(task),it)}},enabled=!isBusy,contentPadding=PaddingValues(horizontal=8.dp)){
                    Icon(Icons.Rounded.CalendarMonth,null,Modifier.size(16.dp));Spacer(Modifier.width(4.dp));Text("Date",fontSize=13.sp)}
                Spacer(Modifier.weight(1f))
                TextButton(onClick={onDrop(listOf(task))},enabled=!isBusy,contentPadding=PaddingValues(horizontal=8.dp),
                    colors=ButtonDefaults.textButtonColors(contentColor=MaterialTheme.colorScheme.onSurfaceVariant)){Text("Drop",fontSize=13.sp)}
            }else Spacer(Modifier.height(8.dp))
        }}
    }

    @Composable fun header(title:String,detail:String?,icon:androidx.compose.ui.graphics.vector.ImageVector,tint:Color,trailing:@Composable ()->Unit={}){
        Row(Modifier.fillMaxWidth().padding(start=18.dp,end=8.dp,top=18.dp,bottom=4.dp),verticalAlignment=Alignment.CenterVertically){
            Icon(icon,null,tint=tint,modifier=Modifier.size(20.dp));Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)){
                Text(title,fontSize=17.sp,fontWeight=FontWeight.SemiBold)
                detail?.let{Text(it,fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)}
            }
            trailing()
        }
    }

    Box(modifier){
        LazyColumn(Modifier.fillMaxSize(),contentPadding=PaddingValues(bottom=if(selecting)150.dp else 24.dp)){
            // Overdue
            item(key="h:overdue"){
                header("Overdue · ${overdue.size}",
                    if(overdue.isEmpty())null else "≈ ${hours(overdue.sumOf{it.first.minutes})} of work · hold a card to move several",
                    Icons.Rounded.WarningAmber,Color(0xFFDC2626)){
                    if(overdue.size>OVERDUE_PREVIEW)TextButton(onClick={showAll=!showAll}){Text(if(showAll)"Top $OVERDUE_PREVIEW" else "All ${overdue.size}",fontSize=13.sp)}
                }
            }
            if(overdue.isEmpty())item(key="overdue:empty"){
                Text(if(backlogLoaded)"Nothing overdue." else "Loading what's overdue…",fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(horizontal=20.dp,vertical=8.dp))
            }else if(!showAll){
                items(overdue.take(OVERDUE_PREVIEW),key={"o:${it.first.id}"}){(task,reason)->card(task,reason,true)}
            }else GROUPS.forEach{(reason,labels)->
                val rows=overdue.filter{it.second==reason}
                if(rows.isNotEmpty()){
                    item(key="g:$reason"){
                        val ids=rows.map{it.first.id}.toSet()
                        Row(Modifier.fillMaxWidth().padding(start=20.dp,end=8.dp,top=12.dp),verticalAlignment=Alignment.CenterVertically){
                            Column(Modifier.weight(1f)){
                                Text("${labels.first} · ${rows.size}",fontSize=13.sp,fontWeight=FontWeight.SemiBold)
                                Text(labels.second,fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            TextButton(onClick={selected=if(selected.containsAll(ids))selected-ids else selected+ids}){
                                Text(if(selected.containsAll(ids))"Unselect" else "Select all",fontSize=12.sp)}
                        }
                    }
                    items(rows,key={"o:${it.first.id}"}){(task,r)->card(task,r,true)}
                }
            }

            // Today
            item(key="h:today"){
                header("Today · ${todayTasks.size} left",
                    "${today.format(DateTimeFormatter.ofPattern("EEE d MMM",Locale.ENGLISH))}${if(todayTasks.isEmpty())"" else " · ≈ ${hours(todayTasks.sumOf{it.minutes})}"}",
                    Icons.Rounded.WbSunny,Color(0xFFF59E0B))
            }
            if(todayTasks.isEmpty())item(key="today:empty"){
                Text("Nothing left planned for today.",fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(horizontal=20.dp,vertical=8.dp))
            }
            items(todayTasks,key={"t:${it.id}"}){task->card(task,null,false)}

            // This week
            item(key="h:week"){
                val start=week?.date?.let(LocalDate::parse)?:today.minusDays((today.dayOfWeek.value-1).toLong())
                header("This week","One row per milestone, soonest first. Tap a day to open it.",Icons.Rounded.ViewWeek,MaterialTheme.colorScheme.primary){
                    IconButton(onClick={onWeek(start.minusDays(7))}){Icon(Icons.Rounded.ChevronLeft,"Previous week")}
                    IconButton(onClick={onWeek(start.plusDays(7))}){Icon(Icons.Rounded.ChevronRight,"Next week")}
                }
            }
            item(key="week"){WeekMatrix(week,milestones,projectNames,today,onOpenDay)}
        }

        // Bulk move / drop
        if(selecting)Surface(tonalElevation=6.dp,shadowElevation=12.dp,shape=RoundedCornerShape(topStart=18.dp,topEnd=18.dp),
            modifier=Modifier.align(Alignment.BottomCenter).fillMaxWidth()){
            Column(Modifier.padding(start=16.dp,end=8.dp,top=10.dp,bottom=8.dp)){
                Row(verticalAlignment=Alignment.CenterVertically){
                    Text("${chosen.size} selected · ≈ ${hours(chosen.sumOf{it.minutes})}",fontWeight=FontWeight.SemiBold,modifier=Modifier.weight(1f))
                    TextButton(onClick={confirmDrop=true}){Text("Drop")}
                    IconButton(onClick={selected=emptySet()}){Icon(Icons.Rounded.Close,"Clear selection")}
                }
                Row(Modifier.horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(6.dp)){
                    quickMoveDates(today).forEach{(day,label)->
                        FilledTonalButton(onClick={onMove(chosen,day);selected=emptySet()},contentPadding=PaddingValues(horizontal=12.dp)){Text(label,fontSize=13.sp)}
                    }
                    OutlinedButton(onClick={pickDate{day->onMove(chosen,day);selected=emptySet()}},contentPadding=PaddingValues(horizontal=12.dp)){
                        Icon(Icons.Rounded.CalendarMonth,null,Modifier.size(16.dp));Spacer(Modifier.width(4.dp));Text("Date",fontSize=13.sp)}
                }
                Text("Moved tasks land untimed on that day. A deadline that has already passed moves with them.",
                    fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=4.dp,end=8.dp))
            }
        }
    }

    if(confirmDrop)AlertDialog(onDismissRequest={confirmDrop=false},
        title={Text("Drop ${chosen.size} task${if(chosen.size==1)"" else "s"}?")},
        text={Text("They're closed as skipped, not deleted, so their history stays.")},
        confirmButton={TextButton(onClick={confirmDrop=false;onDrop(chosen);selected=emptySet()}){Text("Drop")}},
        dismissButton={TextButton(onClick={confirmDrop=false}){Text("Cancel")}})
}

/** The week as a matrix: one row per milestone, seven day cells holding a count. */
@Composable private fun WeekMatrix(week:Day?,milestones:Map<String,FocusMilestone>,projectNames:Map<String,String>,today:LocalDate,onOpenDay:(LocalDate)->Unit){
    if(week==null){
        Text("The week needs a connection the first time.",fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(horizontal=20.dp,vertical=8.dp));return
    }
    val start=LocalDate.parse(week.date)
    val rows=focusWeekRows(week.tasks,start,milestones,projectNames)
    val days=(0..6).map{start.plusDays(it.toLong())}
    Column(Modifier.fillMaxWidth().padding(horizontal=12.dp)){
        Row(Modifier.fillMaxWidth().padding(bottom=4.dp)){
            Spacer(Modifier.weight(2.4f))
            days.forEach{d->
                Column(Modifier.weight(1f),horizontalAlignment=Alignment.CenterHorizontally){
                    Text(d.format(DateTimeFormatter.ofPattern("EEEEE",Locale.ENGLISH)),fontSize=10.sp,color=if(d==today)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(d.dayOfMonth.toString(),fontSize=12.sp,fontWeight=FontWeight.Bold,color=if(d==today)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                }
            }
        }
        if(rows.isEmpty())Text("Nothing planned this week.",fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(8.dp))
        rows.forEach{row->
            HorizontalDivider(color=MaterialTheme.colorScheme.outlineVariant.copy(alpha=.4f))
            Row(Modifier.fillMaxWidth().heightIn(min=42.dp),verticalAlignment=Alignment.CenterVertically){
                Column(Modifier.weight(2.4f).padding(end=6.dp)){
                    Text(row.label,fontSize=12.sp,fontWeight=FontWeight.SemiBold,maxLines=1,overflow=TextOverflow.Ellipsis)
                    (row.milestone?.targetDate?.let{"due "+LocalDate.parse(it).format(DateTimeFormatter.ofPattern("d MMM",Locale.ENGLISH))}?:row.sublabel)?.let{
                        Text(it,fontSize=10.sp,maxLines=1,overflow=TextOverflow.Ellipsis,color=MaterialTheme.colorScheme.onSurfaceVariant)}
                }
                row.cells.forEachIndexed{i,cell->
                    val open=cell.count{!it.done}
                    Box(Modifier.weight(1f).height(34.dp).padding(2.dp)
                        .background(if(days[i]==today)MaterialTheme.colorScheme.primary.copy(alpha=.07f)else Color.Transparent,RoundedCornerShape(8.dp))
                        .clickable(enabled=cell.isNotEmpty(),onClickLabel="Open ${days[i]}"){onOpenDay(days[i])},
                        contentAlignment=Alignment.Center){
                        if(cell.isNotEmpty())Box(Modifier.size(22.dp).background(
                            if(open==0)MaterialTheme.colorScheme.onSurface.copy(alpha=.12f)else MaterialTheme.colorScheme.primary.copy(alpha=.85f),CircleShape),
                            contentAlignment=Alignment.Center){
                            Text(if(open==0)"✓" else open.toString(),fontSize=11.sp,fontWeight=FontWeight.Bold,
                                color=if(open==0)MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onPrimary)
                        }
                    }
                }
            }
        }
    }
}
