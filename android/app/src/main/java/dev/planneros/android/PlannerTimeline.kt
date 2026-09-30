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

internal val Wine = Color(0xFFA32C53)
private val pastelLight = listOf(Color(0xFFFBD9D4),Color(0xFFFBE9C9),Color(0xFFDCECC8),Color(0xFFCBE8EC),Color(0xFFDFE4FB),Color(0xFFEFD6EC),Color(0xFFD3ECDF),Color(0xFFF8DDC0),Color(0xFFE0D9F7),Color(0xFFCFE8FA))
private val pastelDark = listOf(Color(0xFF4B2F2D),Color(0xFF4B3E26),Color(0xFF33452C),Color(0xFF2B4348),Color(0xFF2F3555),Color(0xFF472F47),Color(0xFF2C4639),Color(0xFF4A3A27),Color(0xFF383152),Color(0xFF28404F))
internal fun taskTint(task:Task,dark:Boolean):Color = (if(dark)pastelDark else pastelLight)[Math.floorMod(task.title.hashCode(),pastelLight.size)]
internal fun taskBlocks(tasks:List<Task>) = tasks.filter { it.time != null }.map { TimeBlock(it.id,it.clockMinutes,it.minutes) }
internal data class DragPreview(val taskId:String,val deltaDp:Float,val dayShift:Int,val target:ScheduleSlot)
internal data class DragState(val task:Task,val originDate:LocalDate,val originScroll:Int,val deltaX:Float=0f,val deltaY:Float=0f,val pointerY:Float=0f)

@Composable internal fun WinsPanel(tasks:List<Task>,limit:Int,onJump:(Task)->Unit){
    if(tasks.isEmpty())return
    val wins=tasks.filter{it.starred};val hit=wins.count{it.done}
    Surface(color=MaterialTheme.colorScheme.primary.copy(alpha=.055f),shape=RoundedCornerShape(16.dp),modifier=Modifier.fillMaxWidth().padding(horizontal=18.dp,vertical=7.dp)){
        Column(Modifier.padding(horizontal=12.dp,vertical=9.dp)){
            Row(verticalAlignment=Alignment.CenterVertically){Icon(Icons.Rounded.Star,null,tint=MaterialTheme.colorScheme.primary,modifier=Modifier.size(17.dp));Spacer(Modifier.width(7.dp));Text(if(wins.isNotEmpty()&&hit==wins.size)"Day won" else "Top Wins"+(if(wins.isNotEmpty())" · $hit of ${wins.size}" else ""),fontWeight=FontWeight.SemiBold,fontSize=13.sp)}
            if(wins.isEmpty())Text("Pick today's wins — tap ☆ on up to $limit tasks",color=MaterialTheme.colorScheme.onSurfaceVariant,fontSize=12.sp,modifier=Modifier.padding(top=4.dp))
            else Row(Modifier.horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(7.dp)){
                wins.forEach{task->AssistChip(onClick={onJump(task)},label={Text(task.title,maxLines=1,overflow=TextOverflow.Ellipsis,modifier=Modifier.widthIn(max=195.dp),textDecoration=if(task.done)TextDecoration.LineThrough else null)},leadingIcon={Icon(if(task.done)Icons.Rounded.CheckCircle else Icons.Rounded.RadioButtonUnchecked,null,modifier=Modifier.size(15.dp))},modifier=Modifier.semantics{contentDescription="Top Win ${task.title}, ${if(task.done)"complete" else "incomplete"}. Reveal task"})}
            }
        }
    }
}

@Composable internal fun ProportionalTimeline(tasks:List<Task>,date:LocalDate,isToday:Boolean,nowMinute:Int,timerId:String?,dark:Boolean,
    enabled:Boolean,scroll:ScrollState,preview:DragPreview?,modifier:Modifier=Modifier,
    edit:(Task)->Unit,done:(Task)->Unit,star:(Task)->Unit,focus:(Task)->Unit,gap:(Int)->Unit,
    dragStart:(Task)->Unit,dragMove:(Task,Offset,Float)->Unit,dragEnd:(Task)->Unit,dragCancel:()->Unit,
    viewport:(Float,Float)->Unit){
    val blocks=remember(tasks){taskBlocks(tasks)}
    val bounds=remember(blocks){timelineBounds(blocks)}
    val lanes=remember(blocks){overlapLanes(blocks)}
    val density=LocalDensity.current;val config=LocalViewConfiguration.current
    val holdConfig=remember(config){object:ViewConfiguration by config{override val longPressTimeoutMillis=230L}}
    val context=LocalContext.current;val twelve=!DateFormat.is24HourFormat(context)
    CompositionLocalProvider(LocalViewConfiguration provides holdConfig){
        Box(modifier.onGloballyPositioned{val y=it.positionInWindow().y;viewport(y,y+it.size.height)}.verticalScroll(scroll)){
            BoxWithConstraints(Modifier.fillMaxWidth().height(((bounds.end-bounds.start)*TIMELINE_DP_PER_MINUTE+84).dp)){
                val gutter=58.dp;val right=12.dp
                val usable=maxWidth-gutter-right
                for(minute in bounds.start..bounds.end step 60){
                    Row(Modifier.offset(y=((minute-bounds.start)*TIMELINE_DP_PER_MINUTE).dp).fillMaxWidth(),verticalAlignment=Alignment.CenterVertically){
                        Text(displayClock(minute,twelve),fontSize=10.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.width(gutter).padding(start=7.dp))
                        HorizontalDivider(color=MaterialTheme.colorScheme.outlineVariant.copy(alpha=.45f),modifier=Modifier.weight(1f))
                    }
                }
                val spine=MaterialTheme.colorScheme.outlineVariant.copy(alpha=.5f)
                Canvas(Modifier.offset(x=51.dp).width(1.dp).fillMaxHeight()){drawLine(spine,Offset.Zero,Offset(0f,size.height),strokeWidth=1.dp.toPx(),pathEffect=PathEffect.dashPathEffect(floatArrayOf(2.dp.toPx(),5.dp.toPx())))}
                var occupiedEnd=Int.MIN_VALUE
                tasks.sortedBy{it.clockMinutes}.forEachIndexed{index,task->
                    occupiedEnd=maxOf(occupiedEnd,task.clockMinutes+task.minutes)
                    val next=tasks.sortedBy{it.clockMinutes}.getOrNull(index+1)?.clockMinutes
                    if(next!=null&&next-occupiedEnd>=30){
                        val start=occupiedEnd
                        TextButton(onClick={gap(((start+4)/5)*5)},modifier=Modifier.offset(x=gutter,y=((start-bounds.start)*TIMELINE_DP_PER_MINUTE+8).dp).heightIn(min=36.dp)){
                            Icon(Icons.Rounded.Add,null,modifier=Modifier.size(15.dp));Text(" ${durationLabel(next-start)} free · Add",fontSize=12.sp)
                        }
                    }
                }
                tasks.forEach{task->
                    val lane=lanes[task.id]?:Lane(0,1);val width=usable/lane.columns
                    val dragging=preview?.taskId==task.id
                    val extraY=if(dragging)preview!!.deltaDp else 0f
                    val active=isToday&&!task.done&&nowMinute>=task.clockMinutes&&nowMinute<task.clockMinutes+task.minutes
                    TimelineCard(task,dark,lane.columns,active,timerId==task.id,enabled,dragging,
                        Modifier.offset(x=gutter+width*lane.column+3.dp,y=((task.clockMinutes-bounds.start)*TIMELINE_DP_PER_MINUTE+extraY).dp)
                            .width(width-6.dp).height(maxOf(52f,task.minutes*TIMELINE_DP_PER_MINUTE).dp).zIndex(if(dragging)100f else lane.column.toFloat()),
                        {edit(task)},{done(task)},{star(task)},{focus(task)},
                        {dragStart(task)},{delta,y->dragMove(task,delta,y)},{dragEnd(task)},dragCancel)
                }
                if(isToday&&nowMinute in bounds.start..bounds.end){
                    Row(Modifier.offset(y=((nowMinute-bounds.start)*TIMELINE_DP_PER_MINUTE).dp).fillMaxWidth().zIndex(150f),verticalAlignment=Alignment.CenterVertically){
                        Text("NOW",color=MaterialTheme.colorScheme.primary,fontSize=9.sp,fontWeight=FontWeight.Bold,modifier=Modifier.width(gutter).padding(start=9.dp))
                        Box(Modifier.size(6.dp).background(MaterialTheme.colorScheme.primary,CircleShape));HorizontalDivider(color=MaterialTheme.colorScheme.primary,modifier=Modifier.weight(1f))
                    }
                }
                if(preview!=null){
                    Surface(color=MaterialTheme.colorScheme.primary,shape=RoundedCornerShape(12.dp),shadowElevation=6.dp,modifier=Modifier.offset(x=gutter,y=((preview.target.date.toEpochDay()-date.toEpochDay())*1440+preview.target.clockMinute-bounds.start).coerceIn(0,(bounds.end-bounds.start).toLong()).toFloat().times(TIMELINE_DP_PER_MINUTE).dp).zIndex(200f)){
                        Text("${preview.target.date.format(DateTimeFormatter.ofPattern("EEE, MMM d"))} · ${displayClock(preview.target.clockMinute,twelve)}",color=MaterialTheme.colorScheme.onPrimary,fontSize=12.sp,fontWeight=FontWeight.Bold,modifier=Modifier.padding(8.dp))
                    }
                }
            }
        }
    }
}

@Composable private fun TimelineCard(task:Task,dark:Boolean,columns:Int,ongoing:Boolean,focusing:Boolean,enabled:Boolean,lifted:Boolean,
    modifier:Modifier,edit:()->Unit,done:()->Unit,star:()->Unit,focus:()->Unit,
    dragStart:()->Unit,dragMove:(Offset,Float)->Unit,dragEnd:()->Unit,dragCancel:()->Unit){
    val haptic=LocalHapticFeedback.current;var windowY by remember{mutableFloatStateOf(0f)}
    val twelve=!DateFormat.is24HourFormat(LocalContext.current)
    val interactive=enabled&&!task.id.startsWith("pending:")
    val compact=task.minutes<45
    val showMetadata=!compact||(maxOf(52f,task.minutes*TIMELINE_DP_PER_MINUTE)-24f>=27f*LocalDensity.current.fontScale)
    val latestStart by rememberUpdatedState(dragStart);val latestMove by rememberUpdatedState(dragMove)
    val latestEnd by rememberUpdatedState(dragEnd);val latestCancel by rememberUpdatedState(dragCancel)
    Surface(onClick=edit,enabled=interactive,color=taskTint(task,dark),shape=RoundedCornerShape(12.dp),shadowElevation=if(lifted)10.dp else 0.dp,
        border=if(ongoing||focusing||lifted)BorderStroke(2.dp,MaterialTheme.colorScheme.primary)else null,
        modifier=modifier.alpha(if(task.done).58f else 1f).semantics{contentDescription="${task.title}, ${displayClock(task.clockMinutes,twelve)} to ${displayClock(task.clockMinutes+task.minutes,twelve)}, ${durationLabel(task.minutes)}${if(task.starred)", Top Win" else ""}. Hold and drag to reschedule"}){
        Column(Modifier.padding(horizontal=if(columns>2)3.dp else 7.dp,vertical=if(compact)2.dp else 5.dp)){
            Column(Modifier.weight(1f).fillMaxWidth().onGloballyPositioned{windowY=it.positionInWindow().y}
                .pointerInput(task.id,interactive){if(interactive)detectDragGesturesAfterLongPress(
                    onDragStart={haptic.performHapticFeedback(HapticFeedbackType.LongPress);latestStart()},
                    onDrag={change,amount->change.consume();latestMove(amount,windowY+change.position.y)},onDragEnd={latestEnd()},onDragCancel={latestCancel()})}){
                Text("${taskEmoji(task.title)} ${task.title}",fontSize=if(compact||columns>1)13.sp else 17.sp,lineHeight=if(compact)16.sp else 20.sp,fontWeight=FontWeight.SemiBold,maxLines=if(compact)1 else if(columns>1)3 else 4,overflow=TextOverflow.Ellipsis,textDecoration=if(task.done)TextDecoration.LineThrough else null)
                if(showMetadata)Text("${displayClock(task.clockMinutes,twelve)}${if(columns<3)" – ${displayClock(task.clockMinutes+task.minutes,twelve)}" else ""} · ${durationLabel(task.minutes)}${if(task.recurrenceKey!=null||task.habit)" ↻" else ""}",fontSize=if(compact||columns>1)9.sp else 11.sp,lineHeight=if(compact)11.sp else 14.sp,maxLines=1,overflow=TextOverflow.Ellipsis,color=MaterialTheme.colorScheme.onSurfaceVariant)
                if(task.parent!=null&&!compact)Text("${task.parentTitle?.let{"$it · "}.orEmpty()}Part ${task.partIndex?:"?"}/${task.partCount?:"?"}",fontSize=10.sp,maxLines=2,overflow=TextOverflow.Ellipsis,color=MaterialTheme.colorScheme.onSurfaceVariant)
                if(ongoing&&!compact)Text("ONGOING",fontSize=9.sp,fontWeight=FontWeight.Bold,color=MaterialTheme.colorScheme.primary)
            }
            CompositionLocalProvider(LocalMinimumInteractiveComponentSize provides Dp.Unspecified){
                Row(Modifier.fillMaxWidth().height(if(compact)20.dp else 28.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween){
                    IconButton(onClick=done,enabled=interactive,modifier=Modifier.weight(1f).fillMaxHeight()){Icon(if(task.done)Icons.Rounded.CheckCircle else Icons.Rounded.RadioButtonUnchecked,"${if(task.done)"Reopen" else "Complete"} ${task.title}",modifier=Modifier.size(if(columns>2)15.dp else 18.dp))}
                    IconButton(onClick=star,enabled=interactive,modifier=Modifier.weight(1f).fillMaxHeight()){Icon(if(task.starred)Icons.Rounded.Star else Icons.Rounded.StarBorder,"${if(task.starred)"Remove" else "Choose"} ${task.title} as Top Win",tint=MaterialTheme.colorScheme.primary,modifier=Modifier.size(if(columns>2)15.dp else 18.dp))}
                    IconButton(onClick=focus,enabled=interactive,modifier=Modifier.weight(1f).fillMaxHeight()){Icon(if(focusing)Icons.Rounded.HourglassBottom else Icons.Rounded.PlayArrow,"Start focus timer for ${task.title}",tint=MaterialTheme.colorScheme.primary,modifier=Modifier.size(if(columns>2)15.dp else 18.dp))}
                }
            }
        }
    }
}

@Composable internal fun InboxCard(task:Task,dark:Boolean,enabled:Boolean,edit:()->Unit,done:()->Unit,star:()->Unit,schedule:()->Unit){
    Surface(onClick=edit,enabled=enabled&&!task.id.startsWith("pending:"),color=taskTint(task,dark),shape=RoundedCornerShape(18.dp),modifier=Modifier.fillMaxWidth().padding(horizontal=18.dp,vertical=6.dp).alpha(if(task.done).6f else 1f)){
        Column(Modifier.padding(12.dp)){
            Row(verticalAlignment=Alignment.CenterVertically){IconButton(onClick=done,enabled=enabled,modifier=Modifier.size(32.dp)){Icon(if(task.done)Icons.Rounded.CheckCircle else Icons.Rounded.RadioButtonUnchecked,"${if(task.done)"Reopen" else "Complete"} ${task.title}")};Text("${taskEmoji(task.title)} ${task.title}",modifier=Modifier.weight(1f),fontWeight=FontWeight.SemiBold,maxLines=4,textDecoration=if(task.done)TextDecoration.LineThrough else null);IconButton(onClick=star,enabled=enabled,modifier=Modifier.size(32.dp)){Icon(if(task.starred)Icons.Rounded.Star else Icons.Rounded.StarBorder,"Choose ${task.title} as Top Win",tint=MaterialTheme.colorScheme.primary)}}
            Row(verticalAlignment=Alignment.CenterVertically){Text(durationLabel(task.minutes)+(if(task.parent!=null)" · Part ${task.partIndex?:"?"}/${task.partCount?:"?"}" else if(task.habit)" · Habit" else ""),fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.weight(1f).padding(start=34.dp));TextButton(onClick=schedule,enabled=enabled){Icon(Icons.Rounded.Schedule,null,modifier=Modifier.size(17.dp));Text(" Schedule")}}
        }
    }
}
