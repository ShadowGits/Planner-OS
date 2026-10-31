package dev.planneros.android

import android.text.format.DateFormat
import androidx.compose.foundation.*
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.*
import androidx.compose.ui.semantics.*
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.*
import androidx.compose.ui.zIndex
import java.time.LocalDate
import java.time.format.DateTimeFormatter

internal val Wine = PlannerPalette.Wine
internal fun taskBlocks(tasks:List<Task>) = tasks.filter { it.time != null }.map { TimeBlock(it.id,it.clockMinutes,it.minutes) }
internal data class DragPreview(val taskId:String,val deltaDp:Float,val dayShift:Int,val target:ScheduleSlot)
internal data class DragState(val task:Task,val originDate:LocalDate,val originScroll:Int,val deltaX:Float=0f,val deltaY:Float=0f,val pointerY:Float=0f,val pointerX:Float=0f)
/**
 * Where a held task would land. Its capsule's top has travelled with the finger
 * (plus any auto-scroll since it was lifted), and the time is read off the
 * layout at that point, as Structured does: the outline lands exactly where the
 * capsule will appear, and moving across the screen moves hours, not minutes.
 * Sideways past 100 dp shifts a day, keeping the time.
 */
internal fun dragPreviewOf(drag:DragState?,scrollValue:Int,density:Float,entries:List<DayEntry>):DragPreview? = drag?.let{d->
    val deltaDp=d.deltaY/density+(scrollValue-d.originScroll)/density
    val shift=if(d.deltaX>100*density)1 else if(d.deltaX< -100*density)-1 else 0
    val top=(entryOffsetDp(entries,d.task.id)?:0f)+ROW_PADDING_DP
    val minute=if(shift==0)minuteAtDp(top+deltaDp,entries) else d.task.clockMinutes
    DragPreview(d.task.id,deltaDp,shift,normalizeSlot(d.originDate.plusDays(shift.toLong()),minute.coerceIn(0,1675)))
}

@Composable internal fun InboxCard(task:Task,dark:Boolean,enabled:Boolean,edit:()->Unit,done:()->Unit,star:()->Unit,schedule:()->Unit,overdue:Boolean=false){
    val interactive=enabled&&!task.id.startsWith("pending:")
    Column(Modifier.fillMaxWidth().padding(horizontal=12.dp).alpha(if(task.done).6f else 1f)){
        Row(Modifier.fillMaxWidth().heightIn(min=64.dp),verticalAlignment=Alignment.CenterVertically){
            IconButton(onClick=done,enabled=interactive,modifier=Modifier.size(44.dp)){
                Icon(if(task.done)Icons.Rounded.CheckCircle else Icons.Rounded.RadioButtonUnchecked,"${if(task.done)"Reopen" else "Complete"} ${task.title}",tint=if(task.done)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Column(Modifier.weight(1f).clickable(enabled=interactive,onClick=edit).padding(vertical=9.dp,horizontal=4.dp)){
                Text(task.title,fontSize=15.sp,fontWeight=FontWeight.Medium,maxLines=3,overflow=TextOverflow.Ellipsis,textDecoration=if(task.done)TextDecoration.LineThrough else null)
                val dated=task.dueDate?:task.date
                val stamp=dated?.let{runCatching{LocalDate.parse(it).format(DateTimeFormatter.ofPattern("MMM d"))}.getOrDefault(it)}
                Text(listOfNotNull(if(overdue&&dated!=null)"Overdue" else if(task.done)"Done" else if(task.time==null)"Unscheduled" else null,stamp,task.time?.take(5),durationLabel(task.minutes),if(task.parent!=null)"Part ${task.partIndex?:"?"}/${task.partCount?:"?"}" else if(task.habit)"Habit" else null).joinToString(" · "),
                    fontSize=11.sp,color=if(overdue&&dated!=null)MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,maxLines=2,overflow=TextOverflow.Ellipsis)
                if(TimerPreferences.enabled(LocalContext.current)&&task.workedSeconds>0)Text("${workDuration(task.workedSeconds)} worked${if(task.done)""else " · ${workDuration(task.remainingSeconds)} left"}",fontSize=13.sp,fontWeight=FontWeight.Medium,color=MaterialTheme.colorScheme.primary,modifier=Modifier.padding(top=3.dp))
            }
            if(!task.done)IconButton(onClick=schedule,enabled=interactive,modifier=Modifier.size(44.dp)){Icon(Icons.Rounded.Schedule,"Schedule ${task.title}",modifier=Modifier.size(20.dp))}
        }
        HorizontalDivider(color=MaterialTheme.colorScheme.outlineVariant.copy(alpha=.45f),modifier=Modifier.padding(start=48.dp,end=8.dp))
    }
}
