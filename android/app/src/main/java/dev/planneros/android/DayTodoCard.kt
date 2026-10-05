package dev.planneros.android

import android.text.format.DateFormat
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Same selected-day data and mutation callbacks as the timeline; no fetch on toggle. */
@Composable internal fun DayTodoCard(task:Task,dark:Boolean,enabled:Boolean,focusing:Boolean,
    edit:()->Unit,done:()->Unit,star:()->Unit,focus:()->Unit){
    val interactive=enabled&&!task.id.startsWith("pending:")
    val twelve=!DateFormat.is24HourFormat(LocalContext.current)
    Surface(onClick=edit,enabled=interactive,color=taskTint(task,dark),shape=RoundedCornerShape(8.dp),
        border=if(focusing)BorderStroke(2.dp,MaterialTheme.colorScheme.primary)else null,
        modifier=Modifier.fillMaxWidth().alpha(if(task.done).65f else 1f)){
        Row(Modifier.padding(start=0.dp,end=0.dp,top=3.dp,bottom=3.dp),verticalAlignment=Alignment.CenterVertically){
            Checkbox(checked=task.done,onCheckedChange={done()},enabled=interactive,
                modifier=Modifier.sizeIn(minWidth=48.dp,minHeight=48.dp))
            Column(Modifier.weight(1f).padding(vertical=2.dp)){
                Text("${taskEmoji(task.title)} ${task.title}",fontSize=15.sp,lineHeight=20.sp,fontWeight=FontWeight.SemiBold,
                    maxLines=2,overflow=TextOverflow.Ellipsis,textDecoration=if(task.done)TextDecoration.LineThrough else null)
                Text("${if(task.time==null)"Unscheduled" else displayClock(task.clockMinutes,twelve)} · ${durationLabel(task.minutes)}${if(task.habit||task.recurrenceKey!=null)" · Habit" else ""}",
                    fontSize=11.sp,lineHeight=14.sp,maxLines=1,overflow=TextOverflow.Ellipsis,color=MaterialTheme.colorScheme.onSurfaceVariant)
                if(task.parent!=null)Text("${task.parentTitle?.let{"$it · "}.orEmpty()}Part ${task.partIndex?:"?"}/${task.partCount?:"?"}",fontSize=11.sp,lineHeight=14.sp,maxLines=1,overflow=TextOverflow.Ellipsis,color=MaterialTheme.colorScheme.onSurfaceVariant)
                if(task.workedSeconds>0)Text("${workDuration(task.workedSeconds)} worked · ${workDuration(task.remainingSeconds)} left",fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Row{
                IconButton(onClick=star,enabled=interactive,modifier=Modifier.size(48.dp)){
                    Icon(if(task.starred)Icons.Rounded.Star else Icons.Rounded.StarOutline,
                        if(task.starred)"Remove ${task.title} from Top Wins" else "Star ${task.title}",tint=MaterialTheme.colorScheme.primary,modifier=Modifier.size(20.dp))
                }
                IconButton(onClick=focus,enabled=interactive&&!task.done,modifier=Modifier.size(48.dp)){
                    Icon(Icons.Rounded.Timer,"Start timer for ${task.title}",tint=MaterialTheme.colorScheme.primary,modifier=Modifier.size(20.dp))
                }
            }
        }
    }
}
