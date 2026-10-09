package dev.planneros.android

import android.content.Intent
import android.net.Uri
import android.text.Html
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONArray
import org.json.JSONObject
import java.text.NumberFormat
import java.util.Locale

private val hiddenFields=setOf("id","user_id","workspace_id","project_id","milestone_id","parent_task_id","created_at","updated_at","recurrence_key","config","file_id")
internal fun dashboardFields(row:JSONObject):List<Pair<String,String>> = row.keys().asSequence().filter{it !in hiddenFields&&!it.startsWith('_')&&!row.isNull(it)}.map{key->
    key to when(val value=row.get(key)){
        is JSONObject->value.keys().asSequence().filter{!value.isNull(it)}.joinToString("\n"){it.replace('_',' ')+": "+value.get(it)}
        is JSONArray->(0 until value.length()).joinToString(", "){value.get(it).toString()}
        is Boolean->if(value)"Yes"else "No"
        else->value.toString()
    }
}.filter{it.second.isNotBlank()}.toList()
internal fun rowTitle(row:JSONObject)=listOf("title","name","document","book","question","test","goal","task","subject","topic","university","professor","institute","label","description").firstNotNullOfOrNull{row.nullString(it)}?:"Details"
private fun typedTitle(section:String,row:JSONObject)=when(section){
    "study_logs"->row.nullString("task");"subjects"->row.nullString("subject");"topics","revisions","problems"->row.nullString("topic");"professors"->row.nullString("professor");"applications"->row.nullString("institute");else->null
}?:rowTitle(row)
private fun sectionTitle(section:String)=when(section){
    "projects"->"Your projects";"tasks"->"Work queue";"milestones"->"Milestones";"qna"->"Questions & answers";"widgets"->"Project notes & tables"
    "goals"->"Monthly goals";"weekly_goals"->"Weekly goals";"finance_transactions"->"Transactions";"finance_goals"->"Saving goals";"books"->"Reading shelf"
    "topics"->"Study topics";"subjects"->"Subjects";"revisions"->"Revision tracker";"problems"->"Practice log";"study_logs"->"Study sessions"
    "documents"->"Document checklist";"tests"->"Tests & registrations";"habits"->"Habit routines";"files"->"Project files";else->section.replace('_',' ').replaceFirstChar{it.uppercase()}
}
private fun amount(value:Double,currency:String):String{
    val number=NumberFormat.getNumberInstance(Locale.getDefault()).apply{maximumFractionDigits=if(value%1.0==0.0)0 else 2}.format(value)
    val prefix=when(currency.uppercase()){ "INR"->"₹";"EUR"->"€";"USD"->"$";"GBP"->"£";else->currency+" "};return prefix+number
}
private fun snippet(value:String)=Html.fromHtml(value,Html.FROM_HTML_MODE_COMPACT).toString().trim()

@Composable internal fun DashboardRecords(section:String,rows:List<JSONObject>,project:JSONObject?,onRecord:(JSONObject)->Unit,onProject:(JSONObject)->Unit,more:Boolean,loading:Boolean,onMore:()->Unit){
    var showDone by rememberSaveable(section){mutableStateOf(false)}
    fun open(row:JSONObject){onRecord(JSONObject(row.toString()).put("_section",section))}
    LazyColumn(Modifier.fillMaxSize(),contentPadding=PaddingValues(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)){
        item{DashboardHeading(sectionTitle(section),when(section){"projects"->"Choose a workstream to see its plan";"finance_transactions"->"Income and spending, newest first";"qna"->"Questions, decisions and answers";"books"->"What you’re reading and how far you’ve come";else->null})}
        if(section=="tasks"&&project!=null)item{
            Surface(color=PlannerPalette.Navy,shape=RoundedCornerShape(20.dp)){
                Row(Modifier.fillMaxWidth().padding(18.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(14.dp)){
                    Column(Modifier.weight(1f)){Text(project.optInt("open_tasks").toString(),fontSize=34.sp,fontWeight=FontWeight.Bold,color=Color.White);Text("tasks left in this project",fontSize=15.sp,color=PlannerPalette.Ice)}
                    Text(project.optDouble("completion_pct").toInt().toString()+"%\ndone",fontSize=23.sp,fontWeight=FontWeight.SemiBold,color=PlannerPalette.Ice)
                }
            }
        }
        if(rows.isEmpty())item{DashboardMessage(dashboardIcon(section),"Nothing here yet","This view will show records when you add them.")}
        when(section){
            "projects"->items(rows){DashboardProject(it){onProject(it)}}
            "tasks"->{
                val openRows=rows.filterNot{recordDone(it)||it.optString("status")=="skipped"}
                val groups=listOf("In progress" to openRows.filter{it.optString("status")=="in_progress"},"Blocked" to openRows.filter{it.optString("status")=="blocked"},"To do" to openRows.filter{it.optString("status") !in listOf("in_progress","blocked")})
                groups.forEach{(label,work)->if(work.isNotEmpty()){item{DashboardHeading(label)};items(work){TaskRecord(it){open(it)}}}}
                val done=rows.filter{recordDone(it)}
                if(done.isNotEmpty()){item{Surface(onClick={showDone=!showDone},color=MaterialTheme.colorScheme.secondaryContainer,shape=RoundedCornerShape(14.dp)){
                    Row(Modifier.fillMaxWidth().padding(16.dp),verticalAlignment=Alignment.CenterVertically){Icon(Icons.Rounded.TaskAlt,null,tint=MaterialTheme.colorScheme.onSecondaryContainer);Text("Completed · "+done.size,fontSize=16.sp,fontWeight=FontWeight.Medium,color=MaterialTheme.colorScheme.onSecondaryContainer,modifier=Modifier.weight(1f).padding(start=10.dp));Icon(if(showDone)Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore,null,tint=MaterialTheme.colorScheme.onSecondaryContainer)}
                }};if(showDone)items(done){TaskRecord(it){open(it)}}}
                val skipped=rows.filter{it.optString("status")=="skipped"}
                if(skipped.isNotEmpty()){item{DashboardHeading("Skipped")};items(skipped){TaskRecord(it){open(it)}}}
            }
            "finance_transactions"->items(rows){TransactionRecord(it){open(it)}}
            "finance_goals"->items(rows){SavingRecord(it){open(it)}}
            "milestones"->items(rows.sortedBy{it.nullString("target_date")?:"9999"}){MilestoneRecord(it){open(it)}}
            "qna"->items(rows){QuestionRecord(it){open(it)}}
            "books"->items(rows){BookRecord(it){open(it)}}
            "habits"->items(rows){HabitRecord(it){open(it)}}
            "topics","revisions","problems","subjects","study_logs"->items(rows){StudyRecord(section,it){open(it)}}
            "widgets"->items(rows){WidgetRecord(it){open(it)}}
            else->items(rows){DomainRecord(section,it){open(it)}}
        }
        if(more)item{OutlinedButton(onClick=onMore,enabled=!loading,modifier=Modifier.fillMaxWidth().padding(top=8.dp)){Text(if(loading)"Loading…" else "Load more",fontSize=15.sp)}}
    }
}
@Composable private fun RecordSurface(onClick:()->Unit,content:@Composable ColumnScope.()->Unit){
    Surface(onClick=onClick,color=MaterialTheme.colorScheme.surface,shape=RoundedCornerShape(18.dp),modifier=Modifier.fillMaxWidth()){
        Column(Modifier.padding(16.dp),content=content)
    }
}
@Composable private fun RecordLabel(text:String){Text(text,fontSize=14.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=5.dp))}
@Composable private fun TaskRecord(row:JSONObject,onClick:()->Unit){RecordSurface(onClick){
    Row(horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.Top){
        Icon(if(recordDone(row))Icons.Rounded.CheckCircle else if(row.optString("status")=="skipped")Icons.Rounded.Block else if(row.optString("status")=="blocked")Icons.Rounded.PauseCircleOutline else Icons.Rounded.RadioButtonUnchecked,null,tint=if(recordDone(row))MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.size(24.dp))
        Column(Modifier.weight(1f)){Text(rowTitle(row),fontSize=17.sp,fontWeight=FontWeight.Medium)
            val date=row.nullString("scheduled_date")?:row.nullString("due_date")
            RecordLabel(listOfNotNull("Skipped".takeIf{row.optString("status")=="skipped"},date?.let{friendlyDate(it)},row.nullString("start_time")?.take(5),row.optInt("estimated_minutes").takeIf{it>0}?.let{durationLabel(it)}).joinToString(" · ").ifBlank{"Not scheduled"})
        }
        Icon(Icons.Rounded.ChevronRight,null,modifier=Modifier.size(20.dp),tint=MaterialTheme.colorScheme.onSurfaceVariant)
    }
}}
@Composable private fun TransactionRecord(row:JSONObject,onClick:()->Unit){
    val income=row.optString("type")=="income";val color=if(income)MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.onSurface
    RecordSurface(onClick){
        Row(horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.Top){
            DashboardIconMark(if(income)Icons.Rounded.SouthWest else Icons.Rounded.NorthEast)
            Column(Modifier.weight(1f)){Text(row.nullString("description")?:row.nullString("merchant")?:row.nullString("category")?:if(income)"Income" else "Expense",fontSize=17.sp,fontWeight=FontWeight.Medium);RecordLabel(listOfNotNull(row.nullString("category"),row.nullString("date")?.let{friendlyDate(it)},row.nullString("merchant")).distinct().joinToString(" · "))}
        }
        Text((if(income)"+ "else "− ")+amount(row.optDouble("amount"),row.optString("currency","INR")),fontSize=25.sp,fontWeight=FontWeight.SemiBold,color=color,modifier=Modifier.fillMaxWidth().padding(top=12.dp))
        row.nullString("payment_method")?.let{RecordLabel(it.replace('_',' '))}
    }
}
@Composable private fun SavingRecord(row:JSONObject,onClick:()->Unit){RecordSurface(onClick){
    Row(horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.CenterVertically){DashboardIconMark(Icons.Rounded.Savings);Text(rowTitle(row),fontSize=18.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.weight(1f))}
    val currency=row.optString("currency","INR")
    Text(amount(row.optDouble("saved_amount"),currency),fontSize=29.sp,fontWeight=FontWeight.Bold,modifier=Modifier.padding(top=16.dp))
    RecordLabel("of "+amount(row.optDouble("target_amount"),currency))
    if(row.optDouble("target_amount")>0)LinearProgressIndicator(progress={(row.optDouble("saved_amount")/row.optDouble("target_amount")).toFloat().coerceIn(0f,1f)},modifier=Modifier.fillMaxWidth().padding(top=14.dp).height(7.dp),color=MaterialTheme.colorScheme.tertiary,trackColor=MaterialTheme.colorScheme.outlineVariant)
    row.nullString("deadline")?.let{RecordLabel("Target · "+friendlyDate(it))}
}}
@Composable private fun MilestoneRecord(row:JSONObject,onClick:()->Unit){RecordSurface(onClick){
    Row(horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.CenterVertically){DeadlineStamp(row.optString("target_date"));Column(Modifier.weight(1f)){Text(rowTitle(row),fontSize=18.sp,fontWeight=FontWeight.SemiBold);RecordLabel(humanStatus(row.optString("status","todo")))}
        if(row.optInt("total_tasks")>0)DashboardRing(row.optInt("done_tasks")*100f/row.optInt("total_tasks"))}
    if(row.optInt("total_tasks")>0)RecordLabel(row.optInt("done_tasks").toString()+" of "+row.optInt("total_tasks")+" tasks finished")
}}
@Composable private fun QuestionRecord(row:JSONObject,onClick:()->Unit){RecordSurface(onClick){
    Icon(Icons.Rounded.QuestionAnswer,null,tint=MaterialTheme.colorScheme.secondary,modifier=Modifier.size(26.dp))
    Text(row.optString("question"),fontSize=18.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.padding(top=10.dp))
    val answer=row.nullString("answer")
    Text(if(answer==null)"Waiting for an answer" else snippet(answer),fontSize=15.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,maxLines=5,overflow=TextOverflow.Ellipsis,modifier=Modifier.padding(top=10.dp))
}}
@Composable private fun BookRecord(row:JSONObject,onClick:()->Unit){RecordSurface(onClick){
    Row(horizontalArrangement=Arrangement.spacedBy(14.dp),verticalAlignment=Alignment.CenterVertically){DashboardIconMark(Icons.Rounded.MenuBook);Column(Modifier.weight(1f)){Text(row.optString("book"),fontSize=19.sp,fontWeight=FontWeight.SemiBold);row.nullString("chapter")?.let{RecordLabel(it)}};DashboardRing(row.optDouble("completion_pct").toFloat())}
    RecordLabel(listOfNotNull(row.nullString("progress"),row.optInt("pages").takeIf{it>0}?.let{it.toString()+" pages"}).joinToString(" · "))
}}
@Composable private fun HabitRecord(row:JSONObject,onClick:()->Unit){RecordSurface(onClick){
    Row(horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.Top){DashboardIconMark(dashboardIcon(row.optString("title")));Column(Modifier.weight(1f)){Text(rowTitle(row),fontSize=18.sp,fontWeight=FontWeight.SemiBold);RecordLabel(if(row.optBoolean("is_active",true))humanStatus(row.optString("cadence","daily"))else "Paused")}}
    val days=row.optJSONArray("days_of_week")
    if(days!=null&&days.length()>0)RecordLabel((0 until days.length()).map{days.optInt(it)}.joinToString(" · "){listOf("Sun","Mon","Tue","Wed","Thu","Fri","Sat").getOrElse(it){""}})
    Row(Modifier.padding(top=14.dp),horizontalArrangement=Arrangement.spacedBy(8.dp),verticalAlignment=Alignment.CenterVertically){Icon(Icons.Rounded.LocalFireDepartment,null,tint=MaterialTheme.colorScheme.tertiary);Text(row.optInt("streak_days").toString()+" day streak",fontSize=22.sp,fontWeight=FontWeight.SemiBold)}
}}
@Composable private fun StudyRecord(section:String,row:JSONObject,onClick:()->Unit){RecordSurface(onClick){
    Row(horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.Top){DashboardIconMark(dashboardIcon(section));Column(Modifier.weight(1f)){Text(typedTitle(section,row),fontSize=18.sp,fontWeight=FontWeight.SemiBold);RecordLabel(listOfNotNull(row.nullString("subject").takeUnless{section=="subjects"},row.nullString("unit"),row.nullString("date")?.let{friendlyDate(it)}).joinToString(" · "))}}
    if(row.has("confidence")&&!row.isNull("confidence")){val confidence=row.optInt("confidence").coerceIn(0,5);Row(Modifier.padding(top=14.dp),horizontalArrangement=Arrangement.spacedBy(5.dp),verticalAlignment=Alignment.CenterVertically){for(i in 1..5)Icon(if(i<=confidence)Icons.Rounded.Star else Icons.Rounded.StarOutline,null,tint=if(i<=confidence)MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.outlineVariant,modifier=Modifier.size(18.dp));Spacer(Modifier.width(5.dp));Text(confidence.toString()+"/5",fontSize=15.sp,fontWeight=FontWeight.Medium)}}
    val facts=listOfNotNull(row.optDouble("hours_spent").takeIf{it>0}?.let{it.toString()+" hours studied"},row.optInt("problems_solved").takeIf{it>0}?.let{it.toString()+" problems solved"},row.optInt("duration_minutes").takeIf{it>0}?.let{durationLabel(it)},row.optInt("target_hours").takeIf{it>0}?.let{"Target · "+it+" hours"},row.nullString("next_revision")?.let{"Review · "+friendlyDate(it)})
    facts.forEach{RecordLabel(it)}
    row.nullString("status")?.let{Spacer(Modifier.height(12.dp));DashboardBadge(humanStatus(it))}
    if(section=="study_logs"&&row.has("completed")&&!row.isNull("completed"))RecordLabel(if(row.optBoolean("completed"))"Completed"else "Not completed")
    if(section=="problems"&&row.has("correct")&&!row.isNull("correct"))RecordLabel(if(row.optBoolean("correct"))"Solved correctly" else "Needs another attempt")
}}
@Composable private fun WidgetRecord(row:JSONObject,onClick:()->Unit){RecordSurface(onClick){
    val type=row.optString("widget_type");val config=row.optJSONObject("config")
    Row(horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.CenterVertically){DashboardIconMark(if(type=="text")Icons.Rounded.Notes else if(type=="csv")Icons.Rounded.TableChart else dashboardIcon(if(type=="qna")"qna" else "tasks"));Text(rowTitle(row),fontSize=18.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.weight(1f))}
    config?.nullString("content")?.let{Text(snippet(it),fontSize=16.sp,maxLines=4,overflow=TextOverflow.Ellipsis,modifier=Modifier.padding(top=12.dp))}
    config?.optJSONObject("table")?.let{RecordLabel((it.optJSONArray("rows")?.length()?:0).toString()+" rows · "+(it.optJSONArray("headers")?.length()?:0)+" columns")}
    if(config==null||row.nullString("file_id")!=null)RecordLabel("Open to see details and source")
}}
@Composable private fun DomainRecord(section:String,row:JSONObject,onClick:()->Unit){RecordSurface(onClick){
    Row(horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.Top){
        DashboardIconMark(dashboardIcon(section));Column(Modifier.weight(1f)){Text(typedTitle(section,row),fontSize=18.sp,fontWeight=FontWeight.SemiBold)
            val keys=when(section){"documents"->listOf("category","status","deadline");"tests"->listOf("status","test_date","registration_deadline","target_score","result");"colleges"->listOf("program","city","status","deadline");"applications"->listOf("professor","research_area","status","deadline","response");"professors"->listOf("institute","research_area","email");"papers"->listOf("authors","status","tags");"files"->listOf("file_type");"goals"->listOf("month","description","status");"weekly_goals"->listOf("week_start","description");else->listOf("status","description","notes")}
            keys.mapNotNull{key->row.nullString(key)?.let{key to it}}.forEach{(key,value)->RecordLabel(when(key){"test_date"->"Test · "+friendlyDate(value);"registration_deadline"->"Register by · "+friendlyDate(value);"target_score"->"Target score · "+value;"result"->"Result · "+value;"deadline"->"Due · "+friendlyDate(value);"week_start"->"Week of "+friendlyDate(value);"status"->humanStatus(value);else->value})}
            if(section=="documents"){
                if(row.optBoolean("needs_apostille"))RecordLabel("Apostille required")
                if(row.optBoolean("needs_translation"))RecordLabel("Translation required")
            }
        }
        Icon(Icons.Rounded.ChevronRight,null,tint=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.size(20.dp))
    }
}}
@Composable internal fun DashboardDetail(row:JSONObject,loading:Boolean,error:String?){
    val context=LocalContext.current
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal=22.dp).padding(bottom=40.dp)){
        DashboardIconMark(dashboardIcon(row.optString("_section",row.optString("widget_type"))))
        Text(typedTitle(row.optString("_section"),row),fontSize=25.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.padding(top=16.dp,bottom=16.dp))
        if(TimerPreferences.enabled(context)&&row.optString("_section") in listOf("tasks","week")&&row.nullString("id")!=null)OutlinedButton(onClick={FocusWorkLogs.open(context,row.getString("id"))},modifier=Modifier.fillMaxWidth()){Icon(Icons.Rounded.Schedule,null);Spacer(Modifier.width(8.dp));Text("Log time")}
        if(loading)Row(horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.CenterVertically){CircularProgressIndicator(Modifier.size(20.dp),strokeWidth=2.dp);Text("Loading full details…",fontSize=14.sp)}
        error?.let{Text(it,fontSize=14.sp,color=MaterialTheme.colorScheme.error)}
        row.optJSONObject("config")?.let{config->
            config.nullString("content")?.let{Text(snippet(it),fontSize=17.sp,lineHeight=25.sp,modifier=Modifier.padding(vertical=12.dp))}
            config.optJSONObject("table")?.let{table->
                val headers=table.optJSONArray("headers")?:JSONArray();val cells=table.optJSONArray("rows")?:JSONArray()
                Column(Modifier.horizontalScroll(rememberScrollState()).padding(vertical=12.dp)){
                    Row{for(c in 0 until headers.length())Text(headers.optString(c),fontSize=15.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.width(150.dp).padding(10.dp))}
                    HorizontalDivider()
                    for(r in 0 until cells.length()){val line=cells.optJSONArray(r)?:continue;Row{for(c in 0 until line.length())Text(line.optString(c),fontSize=15.sp,modifier=Modifier.width(150.dp).padding(10.dp))};HorizontalDivider(color=MaterialTheme.colorScheme.outlineVariant.copy(alpha=.5f))}
                }
            }
        }
        dashboardFields(row).filterNot{it.first in listOf("title","name","question","book","document")}.forEach{(key,value)->
            val link=runCatching{Uri.parse(value)}.getOrNull()?.takeIf{it.scheme=="https"&&!it.host.isNullOrBlank()}
            Surface(color=MaterialTheme.colorScheme.surface,shape=RoundedCornerShape(14.dp),modifier=Modifier.fillMaxWidth().padding(bottom=10.dp)){
                Column(Modifier.padding(14.dp)){Text(key.replace('_',' ').replaceFirstChar{it.uppercase()},fontSize=13.sp,fontWeight=FontWeight.Medium,color=MaterialTheme.colorScheme.onSurfaceVariant)
                    if(link!=null)TextButton(onClick={context.startActivity(Intent(Intent.ACTION_VIEW,link))}){Icon(Icons.Rounded.OpenInNew,null,modifier=Modifier.size(18.dp));Spacer(Modifier.width(8.dp));Text("Open source",fontSize=16.sp)}else Text(value,fontSize=17.sp,lineHeight=24.sp,modifier=Modifier.padding(top=6.dp))
                }
            }
        }
    }
}
