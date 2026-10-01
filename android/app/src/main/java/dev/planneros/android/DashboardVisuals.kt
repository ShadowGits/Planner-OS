package dev.planneros.android

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

internal fun dashboardIcon(label:String):ImageVector=when(label.lowercase()){
    "overview","home"->Icons.Rounded.SpaceDashboard
    "week"->Icons.Rounded.CalendarMonth
    "projects","internship and project"->Icons.Rounded.WorkOutline
    "study","topics","subjects","study_logs"->Icons.Rounded.School
    "books","reading","papers"->Icons.Rounded.MenuBook
    "habits","fitness"->Icons.Rounded.FitnessCenter
    "money","finance","finance_summary","finance_transactions"->Icons.Rounded.AccountBalanceWallet
    "finance_plan","finance_goals","goals","weekly_goals"->Icons.Rounded.Savings
    "germany","colleges"->Icons.Rounded.Public
    "documents","files"->Icons.Rounded.FolderOpen
    "tests","problems"->Icons.Rounded.Quiz
    "applications"->Icons.Rounded.Send
    "professors"->Icons.Rounded.PersonOutline
    "milestones"->Icons.Rounded.Flag
    "tasks"->Icons.Rounded.Checklist
    "qna"->Icons.Rounded.QuestionAnswer
    "widgets","browse"->Icons.Rounded.Widgets
    "revisions"->Icons.Rounded.History
    "language"->Icons.Rounded.Translate
    "piano"->Icons.Rounded.Piano
    else->Icons.Rounded.FolderOpen
}
internal fun JSONObject.dashboardObjects(key:String):List<JSONObject>{val array=optJSONArray(key)?:return emptyList();return (0 until array.length()).mapNotNull{array.optJSONObject(it)}}
internal fun friendlyDate(value:String?):String=value?.let{runCatching{val date=LocalDate.parse(it);date.format(DateTimeFormatter.ofPattern(if(date.year==LocalDate.now().year)"d MMM" else "d MMM yyyy",Locale.getDefault()))}.getOrDefault(it)}.orEmpty()
internal fun humanStatus(value:String)=when(value.lowercase()){
    "red"->"At risk";"amber"->"Behind";"green"->"On track";"no_date"->"No schedule";"todo","not_started","not started"->"To do"
    "in_progress","in progress"->"In progress";"done","complete","completed"->"Done";else->value.replace('_',' ').replaceFirstChar{it.uppercase()}
}
internal fun recordDone(row:JSONObject)=row.optBoolean("done")||row.optBoolean("completed")||row.optString("status").lowercase() in listOf("done","complete","completed")

@Composable internal fun DashboardBadge(label:String,attention:Boolean=false){
    val scheme=MaterialTheme.colorScheme
    Surface(color=if(attention)scheme.errorContainer else scheme.secondaryContainer,shape=RoundedCornerShape(8.dp)){
        Text(label,fontSize=12.sp,fontWeight=FontWeight.Medium,color=if(attention)scheme.onErrorContainer else scheme.onSecondaryContainer,modifier=Modifier.padding(horizontal=9.dp,vertical=5.dp))
    }
}
@Composable internal fun DashboardIconMark(icon:ImageVector,modifier:Modifier=Modifier){
    Surface(color=MaterialTheme.colorScheme.secondaryContainer,shape=RoundedCornerShape(14.dp),modifier=modifier.size(44.dp)){
        Box(contentAlignment=Alignment.Center){Icon(icon,null,tint=MaterialTheme.colorScheme.onSecondaryContainer,modifier=Modifier.size(24.dp))}
    }
}
@Composable internal fun DashboardRing(percent:Float,modifier:Modifier=Modifier){
    val value=percent.coerceIn(0f,100f);val scheme=MaterialTheme.colorScheme
    Box(modifier.size(64.dp).semantics{contentDescription=value.toInt().toString()+" percent complete"},contentAlignment=Alignment.Center){
        Canvas(Modifier.fillMaxSize().padding(4.dp)){
            val stroke=Stroke(5.dp.toPx(),cap=StrokeCap.Round)
            drawArc(scheme.outlineVariant,-90f,360f,false,style=stroke)
            if(value>0)drawArc(scheme.secondary,-90f,360f*value/100f,false,style=stroke)
        }
        Text(value.toInt().toString()+"%",fontSize=16.sp,fontWeight=FontWeight.Bold,color=scheme.onSurface)
    }
}
@Composable internal fun DashboardHeading(title:String,subtitle:String?=null){
    Column(Modifier.fillMaxWidth().padding(top=8.dp,bottom=4.dp)){
        Text(title,fontSize=21.sp,fontWeight=FontWeight.SemiBold)
        if(!subtitle.isNullOrBlank())Text(subtitle,fontSize=14.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=4.dp))
    }
}
@Composable internal fun DashboardNotice(message:String){
    Surface(color=MaterialTheme.colorScheme.secondaryContainer,shape=RoundedCornerShape(12.dp),modifier=Modifier.fillMaxWidth().padding(horizontal=16.dp,vertical=6.dp)){
        Row(Modifier.padding(12.dp),horizontalArrangement=Arrangement.spacedBy(10.dp)){
            Icon(Icons.Rounded.Info,null,tint=MaterialTheme.colorScheme.onSecondaryContainer,modifier=Modifier.size(20.dp))
            Text(message,fontSize=13.sp,color=MaterialTheme.colorScheme.onSecondaryContainer,modifier=Modifier.weight(1f))
        }
    }
}
@Composable internal fun DashboardMessage(icon:ImageVector,title:String,message:String,loading:Boolean=false,onRetry:(()->Unit)?=null){
    Column(Modifier.fillMaxWidth().padding(horizontal=24.dp,vertical=36.dp),horizontalAlignment=Alignment.CenterHorizontally){
        DashboardIconMark(icon);Text(title,fontSize=23.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.padding(top=20.dp))
        Text(message,fontSize=15.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=10.dp))
        if(loading)CircularProgressIndicator(Modifier.padding(top=24.dp).size(28.dp),strokeWidth=3.dp)
        if(onRetry!=null)Button(onClick=onRetry,modifier=Modifier.padding(top=20.dp)){Text("Try again")}
    }
}
@Composable internal fun DashboardProject(row:JSONObject,onClick:()->Unit){
    val total=row.optInt("total_tasks");val open=row.optInt("open_tasks",total-row.optInt("done_tasks"))
    Surface(onClick=onClick,shape=RoundedCornerShape(20.dp),color=MaterialTheme.colorScheme.surface,modifier=Modifier.fillMaxWidth()){
        Column(Modifier.padding(16.dp)){
            Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(12.dp)){
                DashboardIconMark(dashboardIcon(row.optString("name")))
                Column(Modifier.weight(1f)){
                    Text(row.optString("name","Project"),fontSize=18.sp,fontWeight=FontWeight.SemiBold)
                    Text(if(total>0)open.toString()+if(open==1)" task left" else " tasks left" else "No tasks yet",fontSize=14.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=4.dp))
                }
                if(total>0)DashboardRing(row.optDouble("completion_pct").toFloat())else Icon(Icons.Rounded.ChevronRight,null,tint=MaterialTheme.colorScheme.onSurfaceVariant)
            }
            val next=row.optJSONObject("next_milestone")
            val due=next?.nullString("target_date")?:row.nullString("target_date")
            val text=next?.nullString("name")
            if(text!=null||due!=null){HorizontalDivider(Modifier.padding(vertical=12.dp),color=MaterialTheme.colorScheme.outlineVariant.copy(alpha=.5f))
                Row(horizontalArrangement=Arrangement.spacedBy(8.dp),verticalAlignment=Alignment.Top){Icon(Icons.Rounded.Flag,null,modifier=Modifier.size(18.dp),tint=MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(listOfNotNull(text,due?.let{friendlyDate(it)}).joinToString(" · "),fontSize=14.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.weight(1f))}
            }
        }
    }
}
@Composable internal fun DashboardOverview(snapshot:JSONObject,onProject:(JSONObject)->Unit,onRecord:(JSONObject)->Unit,onProjects:()->Unit,onWeek:()->Unit){
    val totals=snapshot.optJSONObject("totals")?:JSONObject();val projects=snapshot.dashboardObjects("projects")
    val risks=snapshot.dashboardObjects("milestone_health").filter{it.optString("status") in listOf("red","amber","overdue")}.take(3)
    val deadlines=snapshot.dashboardObjects("upcoming_deadlines").take(4)
    LazyColumn(Modifier.fillMaxSize(),contentPadding=PaddingValues(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)){
        item{
            Surface(color=PlannerPalette.Navy,shape=RoundedCornerShape(24.dp),modifier=Modifier.fillMaxWidth()){
                Column(Modifier.padding(22.dp)){
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically){
                        Text("TODAY",fontSize=13.sp,fontWeight=FontWeight.SemiBold,color=PlannerPalette.Ice)
                        Icon(Icons.Rounded.TaskAlt,null,tint=PlannerPalette.IceBlue,modifier=Modifier.size(28.dp))
                    }
                    Row(verticalAlignment=Alignment.Bottom,horizontalArrangement=Arrangement.spacedBy(12.dp),modifier=Modifier.padding(top=12.dp)){
                        Text(totals.optInt("completed_today").toString(),fontSize=46.sp,fontWeight=FontWeight.Bold,color=Color.White)
                        Text("finished\ntoday",fontSize=20.sp,color=Color.White,modifier=Modifier.padding(bottom=7.dp))
                    }
                    HorizontalDivider(Modifier.padding(vertical=16.dp),color=PlannerPalette.Ice.copy(alpha=.18f))
                    Text(totals.optInt("completions_last_7_days").toString()+" completed in the last 7 days",fontSize=16.sp,color=PlannerPalette.Ice)
                }
            }
        }
        item{Row(horizontalArrangement=Arrangement.spacedBy(12.dp),modifier=Modifier.fillMaxWidth()){
            Surface(onClick=onProjects,color=MaterialTheme.colorScheme.secondaryContainer,shape=RoundedCornerShape(18.dp),modifier=Modifier.weight(1f)){
                Column(Modifier.padding(16.dp)){Icon(Icons.Rounded.PendingActions,null,tint=MaterialTheme.colorScheme.onSecondaryContainer);Text(totals.optInt("open_tasks").toString(),fontSize=30.sp,fontWeight=FontWeight.Bold,color=MaterialTheme.colorScheme.onSecondaryContainer,modifier=Modifier.padding(top=8.dp));Text("Open tasks",fontSize=14.sp,color=MaterialTheme.colorScheme.onSecondaryContainer)}
            }
            Surface(color=PlannerPalette.Wine,shape=RoundedCornerShape(18.dp),modifier=Modifier.weight(1f)){
                Column(Modifier.padding(16.dp)){Icon(Icons.Rounded.PriorityHigh,null,tint=Color.White);Text(totals.optInt("overdue_tasks").toString(),fontSize=30.sp,fontWeight=FontWeight.Bold,color=Color.White,modifier=Modifier.padding(top=8.dp));Text("Needs attention",fontSize=14.sp,color=Color.White)}
            }
        }}
        if(risks.isNotEmpty()){item{DashboardHeading("Needs attention","Milestones that need a decision")}
            items(risks){row->Surface(onClick={projects.firstOrNull{it.optString("id")==row.optString("project_id")}?.let(onProject)},color=MaterialTheme.colorScheme.surface,shape=RoundedCornerShape(18.dp)){
                Column(Modifier.padding(16.dp)){Row(horizontalArrangement=Arrangement.spacedBy(10.dp),verticalAlignment=Alignment.Top){Icon(Icons.Rounded.Flag,null,tint=MaterialTheme.colorScheme.error,modifier=Modifier.size(24.dp));Text(row.optString("name"),fontSize=17.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.weight(1f))}
                    Text(row.optString("project_name"),fontSize=14.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=6.dp,bottom=10.dp))
                    DashboardBadge(humanStatus(row.optString("status"))+" · "+row.optInt("done")+" of "+row.optInt("total")+" done",attention=true)
                }
            }}
        }
        item{Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically){Text("Projects",fontSize=21.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.weight(1f));TextButton(onClick=onWeek){Icon(Icons.Rounded.CalendarMonth,null,modifier=Modifier.size(18.dp));Spacer(Modifier.width(6.dp));Text("Week view",fontSize=14.sp)}}}
        items(projects){row->DashboardProject(row){onProject(row)}}
        if(deadlines.isNotEmpty()){item{DashboardHeading("Coming up","Dates to keep in sight")};items(deadlines){row->
            Surface(onClick={onRecord(row)},color=MaterialTheme.colorScheme.surface,shape=RoundedCornerShape(18.dp)){
                Row(Modifier.fillMaxWidth().padding(16.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(14.dp)){
                    DeadlineStamp(row.optString("date"))
                    Column(Modifier.weight(1f)){Text(row.optString("name"),fontSize=17.sp,fontWeight=FontWeight.Medium);Text(if(row.optBoolean("overdue"))"Deadline passed" else row.optInt("days_left").toString()+" days left",fontSize=14.sp,color=if(row.optBoolean("overdue"))MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=5.dp))}
                }
            }
        }}
        val streaks=snapshot.optJSONObject("streaks")?:JSONObject()
        if(streaks.length()>0){item{DashboardHeading("Keep the streak")};streaks.keys().forEach{key->item{
            Row(Modifier.fillMaxWidth().padding(vertical=8.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(12.dp)){
                Icon(Icons.Rounded.LocalFireDepartment,null,tint=MaterialTheme.colorScheme.tertiary,modifier=Modifier.size(30.dp));Text(key,fontSize=17.sp,modifier=Modifier.weight(1f));Text(streaks.optInt(key).toString()+" days",fontSize=20.sp,fontWeight=FontWeight.SemiBold)
            }
        }}}
    }
}
@Composable internal fun DeadlineStamp(value:String){
    val date=runCatching{LocalDate.parse(value)}.getOrNull()
    Surface(color=MaterialTheme.colorScheme.secondaryContainer,shape=RoundedCornerShape(12.dp),modifier=Modifier.width(54.dp)){
        Column(Modifier.padding(vertical=10.dp,horizontal=4.dp),horizontalAlignment=Alignment.CenterHorizontally){
            if(date!=null){Text(date.dayOfMonth.toString(),fontSize=24.sp,fontWeight=FontWeight.Bold,color=MaterialTheme.colorScheme.onSecondaryContainer);Text(date.format(DateTimeFormatter.ofPattern("MMM")),fontSize=12.sp,color=MaterialTheme.colorScheme.onSecondaryContainer)}
            else Icon(Icons.Rounded.Event,null,tint=MaterialTheme.colorScheme.onSecondaryContainer)
        }
    }
}
@Composable internal fun DashboardWeek(data:JSONObject,onRecord:(JSONObject)->Unit){
    val rows=data.dashboardObjects("items");val start=runCatching{LocalDate.parse(data.optString("week_start"))}.getOrDefault(LocalDate.now())
    var selected by rememberSaveable(data.optString("week_start")){mutableStateOf(if(LocalDate.now() in start..start.plusDays(6))LocalDate.now().toString()else start.toString())}
    val dayRows=rows.filter{(it.nullString("scheduled_date")?:it.nullString("due_date"))==selected}.sortedBy{it.nullString("start_time")?:"99:99"}
    Column(Modifier.fillMaxSize()){
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal=16.dp,vertical=10.dp),horizontalArrangement=Arrangement.spacedBy(8.dp)){
            for(i in 0..6){val day=start.plusDays(i.toLong());val key=day.toString();val count=rows.count{(it.nullString("scheduled_date")?:it.nullString("due_date"))==key};val active=key==selected
                Surface(onClick={selected=key},shape=RoundedCornerShape(16.dp),color=if(active)PlannerPalette.Wine else MaterialTheme.colorScheme.surface,modifier=Modifier.width(56.dp)){
                    Column(Modifier.padding(vertical=12.dp,horizontal=3.dp),horizontalAlignment=Alignment.CenterHorizontally){
                        val ink=if(active)Color.White else MaterialTheme.colorScheme.onSurface
                        Text(day.format(DateTimeFormatter.ofPattern("EEE")),fontSize=12.sp,color=ink);Text(day.dayOfMonth.toString(),fontSize=22.sp,fontWeight=FontWeight.Bold,color=ink)
                        Text(if(count>0)count.toString()+" tasks" else "—",fontSize=12.sp,color=ink)
                    }
                }
            }
        }
        LazyColumn(Modifier.fillMaxSize(),contentPadding=PaddingValues(horizontal=16.dp,vertical=10.dp),verticalArrangement=Arrangement.spacedBy(12.dp)){
            item{DashboardHeading(LocalDate.parse(selected).format(DateTimeFormatter.ofPattern("EEEE, d MMM")),dayRows.count{recordDone(it)}.toString()+" of "+dayRows.size+" done · "+durationLabel(dayRows.sumOf{it.optInt("estimated_minutes")}))}
            if(dayRows.isEmpty())item{DashboardMessage(Icons.Rounded.WbSunny,"Room to breathe","No work scheduled for this day.")}
            items(dayRows){row->Surface(onClick={onRecord(row)},color=MaterialTheme.colorScheme.surface,shape=RoundedCornerShape(18.dp)){
                Row(Modifier.fillMaxWidth().padding(16.dp),horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.Top){
                    Column(Modifier.width(58.dp)){Text(row.nullString("start_time")?.take(5)?:"Anytime",fontSize=14.sp,fontWeight=FontWeight.SemiBold);Text(durationLabel(row.optInt("estimated_minutes")),fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=6.dp))}
                    Column(Modifier.weight(1f)){Text(rowTitle(row),fontSize=17.sp,fontWeight=FontWeight.Medium);Text(if(recordDone(row))"Done" else if(row.optBoolean("is_habit"))"Habit" else "Planned",fontSize=14.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=7.dp))}
                    Icon(if(recordDone(row))Icons.Rounded.CheckCircle else Icons.Rounded.Schedule,null,tint=if(recordDone(row))MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.size(22.dp))
                }
            }}
        }
    }
}
