package dev.planneros.android

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
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
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

class DashboardActivity:ComponentActivity(){
    private val dashboardSession=mutableStateOf("")
    override fun onResume(){super.onResume();dashboardSession.value="${SecureConfig(this).generation}:${Reminders.revision(this)}"}
    override fun onCreate(savedInstanceState:Bundle?){
        super.onCreate(savedInstanceState);enableEdgeToEdge()
        setContent{
            val theme=getSharedPreferences("appearance",MODE_PRIVATE).getString("theme","system")
            val dark=theme=="dark"||theme!="light"&&isSystemInDarkTheme()
            val colors=if(dark)darkColorScheme(primary=Color(0xFFF286A8),onPrimary=Color(0xFF451027),background=Color(0xFF17181C),surface=Color(0xFF202127),onSurface=Color(0xFFF7F2F5),onSurfaceVariant=Color(0xFFCAC0C7))
                else lightColorScheme(primary=Wine,onPrimary=Color.White,background=Color.White,surface=Color.White,onSurface=Color(0xFF292A35),onSurfaceVariant=Color(0xFF77707A))
            MaterialTheme(colorScheme=colors){key(dashboardSession.value){DashboardScreen{finish()}}}
        }
    }
}

private data class DashboardPage(val data:JSONObject?=null,val loading:Boolean=false,val error:String?=null,val unavailable:Boolean=false)
private val groups=listOf("Overview","Week","Projects","Study","Books","Habits","Money","Germany")
private fun tabs(group:String,project:String?):List<Pair<String,String>> = when {
    group=="Projects"&&project!=null->listOf("Tasks" to "tasks","Milestones" to "milestones","Monthly goals" to "goals","Weekly goals" to "weekly_goals","Q&A" to "qna","Widgets" to "widgets","Files" to "files")
    group=="Study"->listOf("Topics" to "topics","Subjects" to "subjects","Revision" to "revisions","Problems" to "problems","Study log" to "study_logs")
    group=="Money"->listOf("Summary" to "finance_summary","Funding plan" to "finance_plan","Transactions" to "finance_transactions","Goals" to "finance_goals")
    group=="Germany"->listOf("Documents" to "documents","Tests" to "tests","Colleges" to "colleges","Applications" to "applications","Professors" to "professors","Papers" to "papers")
    else->listOf(group to group.lowercase())
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun DashboardScreen(exit:()->Unit){
    val context=LocalContext.current;val repo=remember{DashboardRepository(context)};val scope=rememberCoroutineScope()
    var group by rememberSaveable{mutableStateOf("Overview")};var subtab by rememberSaveable{mutableIntStateOf(0)}
    var project by rememberSaveable{mutableStateOf<String?>(null)};var projectName by rememberSaveable{mutableStateOf("")}
    var query by rememberSaveable{mutableStateOf("")};var record by remember{mutableStateOf<JSONObject?>(null)}
    var weekDate by rememberSaveable{mutableStateOf(LocalDate.now().toString())}
    var monthDate by rememberSaveable{mutableStateOf(LocalDate.now().withDayOfMonth(1).toString())}
    var detailSerial by remember{mutableIntStateOf(0)}
    var recordLoading by remember{mutableStateOf(false)};var recordError by remember{mutableStateOf<String?>(null)}
    val pages=remember{mutableStateMapOf<String,DashboardPage>()};val jobs=remember{mutableMapOf<String,Job>()}
    val requestSerials=remember{mutableMapOf<String,Int>()}
    val choices=tabs(group,project);val section=choices[subtab.coerceIn(choices.indices)].second
    val selectedDate=when(section){"week"->weekDate;"finance_summary"->monthDate;else->null}
    val path=repo.path(section,if(group=="Projects")project else null,date=selectedDate)
    val generation=repo.generation
    val page=pages[path]?:DashboardPage(repo.cached(path))
    fun load(force:Boolean=false,offset:Int=0){
        val key=path;val request=repo.path(section,if(group=="Projects")project else null,offset,date=selectedDate)
        val serial=(requestSerials[key]?:0)+1;requestSerials[key]=serial
        jobs[key]?.cancel()
        pages[key]=(pages[key]?:DashboardPage(repo.cached(key))).copy(loading=true,error=null,unavailable=false)
        jobs[key]=scope.launch{
            try{
                val fresh=repo.load(request,force)
                if(generation!=repo.generation||requestSerials[key]!=serial)return@launch
                val data=if(offset>0){val merged=JSONObject(fresh.toString());val rows=JSONArray()
                    val old=pages[key]?.data?.optJSONArray("rows")?:JSONArray();for(i in 0 until old.length())rows.put(old.get(i))
                    val added=fresh.optJSONArray("rows")?:JSONArray();for(i in 0 until added.length())rows.put(added.get(i));merged.put("rows",rows)
                }else fresh
                pages[key]=DashboardPage(data)
            }catch(cancel:CancellationException){throw cancel}catch(error:Exception){
                if(generation==repo.generation&&requestSerials[key]==serial)pages[key]=(pages[key]?:DashboardPage()).copy(loading=false,error=error.message?:"This section couldn't refresh.",unavailable=error is PlannerHttpException&&error.statusCode==409)
            }
        }
    }
    fun selectProject(row:JSONObject){
        if(row.optString("name")=="Finance"){group="Money";subtab=1;project=null}
        else{group="Projects";project=row.nullString("id");projectName=row.optString("name","Project");subtab=0};query=""
    }
    fun showRecord(row:JSONObject){
        detailSerial+=1;val serial=detailSerial
        record=row;recordError=null;recordLoading=false
        val id=row.nullString("id")?:return
        if(section=="week"||section.startsWith("finance_")&&section!="finance_transactions")return
        val key=id;val recordPath=repo.path(section,if(group=="Projects")project else null,row=id)
        recordLoading=true
        scope.launch{
            try{val data=repo.load(recordPath);if(detailSerial==serial&&record?.nullString("id")==key&&generation==repo.generation)record=data.getJSONObject("record")}
            catch(cancel:CancellationException){throw cancel}catch(error:Exception){if(detailSerial==serial&&record?.nullString("id")==key)recordError=error.message}
            finally{if(detailSerial==serial&&record?.nullString("id")==key)recordLoading=false}
        }
    }
    LaunchedEffect(path,generation){query="";load()}
    Scaffold(topBar={
        TopAppBar(title={Text(if(project!=null&&group=="Projects")projectName else "Dashboard",fontSize=20.sp,maxLines=1,overflow=TextOverflow.Ellipsis)},
            navigationIcon={IconButton(onClick={if(project!=null&&group=="Projects"){project=null;subtab=0}else exit()}){Icon(Icons.Rounded.ArrowBack,"Back to ${if(project!=null&&group=="Projects")"projects" else "day"}")}},
            actions={IconButton(onClick={load(true)},enabled=!page.loading){Icon(Icons.Rounded.Refresh,"Refresh dashboard section")}})
    }){padding->
        Column(Modifier.fillMaxSize().padding(padding)){
            ScrollableTabRow(selectedTabIndex=groups.indexOf(group),edgePadding=8.dp){groups.forEach{label->
                Tab(selected=group==label,onClick={group=label;subtab=0;query=""},text={Text(label,fontSize=13.sp,maxLines=1)})
            }}
            if(choices.size>1)ScrollableTabRow(selectedTabIndex=subtab.coerceIn(choices.indices),edgePadding=8.dp){choices.forEachIndexed{index,choice->
                Tab(selected=subtab==index,onClick={subtab=index;query=""},text={Text(choice.first,fontSize=12.sp,maxLines=1)})
            }}
            if(page.loading)LinearProgressIndicator(Modifier.fillMaxWidth().height(2.dp))
            if(section=="week"||section=="finance_summary"){
                val anchor=LocalDate.parse(selectedDate)
                Row(Modifier.fillMaxWidth().padding(horizontal=12.dp),verticalAlignment=Alignment.CenterVertically){
                    IconButton(onClick={if(section=="week")weekDate=anchor.minusWeeks(1).toString()else monthDate=anchor.minusMonths(1).toString()}){Icon(Icons.Rounded.ChevronLeft,"Previous ${if(section=="week")"week" else "month"}")}
                    val displayDate=if(section=="week")anchor.minusDays((anchor.dayOfWeek.value-1).toLong())else anchor
                    Text(displayDate.format(DateTimeFormatter.ofPattern(if(section=="week")"'Week of' d MMM" else "MMMM yyyy",Locale.getDefault())),fontSize=13.sp,modifier=Modifier.weight(1f))
                    IconButton(onClick={if(section=="week")weekDate=anchor.plusWeeks(1).toString()else monthDate=anchor.plusMonths(1).toString()}){Icon(Icons.Rounded.ChevronRight,"Next ${if(section=="week")"week" else "month"}")}
                }
            }
            page.error?.takeUnless{page.unavailable}?.let{message->Row(Modifier.fillMaxWidth().padding(horizontal=16.dp,vertical=8.dp),verticalAlignment=Alignment.CenterVertically){
                Text(message,color=MaterialTheme.colorScheme.error,fontSize=12.sp,modifier=Modifier.weight(1f));TextButton(onClick={load(true)}){Text("Retry")}
            }}
            val data=page.data
            if(page.unavailable)EmptyState("Tracker not set up",page.error.orEmpty())
            if(data==null&&!page.loading&&page.error==null)EmptyState("Choose a section","Your daily plan loads separately.")
            if(data!=null&&!page.unavailable){
                val warnings=data.optJSONArray("warnings")
                if(warnings!=null&&warnings.length()>0)Text((0 until warnings.length()).joinToString(" "){warnings.optString(it)},fontSize=12.sp,color=MaterialTheme.colorScheme.error,modifier=Modifier.padding(16.dp))
                if(section=="overview")DashboardOverview(data.optJSONObject("snapshot")?:JSONObject(),::selectProject)
                else if(section=="finance_summary")FinanceSummary(data)
                else if(section=="finance_plan")FundingPlan(data,::showRecord)
                else{
                    val array=when(section){"finance_goals"->data.optJSONArray("goals");"week"->data.optJSONArray("items");else->data.optJSONArray("rows")}?:JSONArray()
                    val rows=(0 until array.length()).mapNotNull{array.optJSONObject(it)}
                    if(rows.isNotEmpty())OutlinedTextField(query,{query=it},modifier=Modifier.fillMaxWidth().padding(horizontal=16.dp,vertical=6.dp),singleLine=true,label={Text("Find in this list")},leadingIcon={Icon(Icons.Rounded.Search,null)})
                    val visible=rows.filter{query.isBlank()||visibleFields(it).any{entry->entry.second.contains(query,true)}}
                    LazyColumn(Modifier.weight(1f).fillMaxWidth(),contentPadding=PaddingValues(bottom=24.dp)){
                        item{Text("${visible.size} ${if(query.isBlank())"items" else "matches"}",fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(horizontal=20.dp,vertical=6.dp))}
                        if(visible.isEmpty())item{EmptyState(if(query.isBlank())"Nothing here yet" else "No matches",if(query.isBlank())"This section is ready when you add records." else "Try another word.")}
                        itemsIndexed(visible){_,row->DashboardRow(rowTitle(row),rowCaption(row),rowProgress(row),{if(section=="projects")selectProject(row)else showRecord(row)})}
                        if(!data.isNull("next_offset")&&data.has("next_offset"))item{TextButton(enabled=!page.loading,onClick={load(offset=data.getInt("next_offset"))},modifier=Modifier.fillMaxWidth()){Text("Load more")}}
                    }
                }
            }
        }
    }
    record?.let{row->ModalBottomSheet(onDismissRequest={detailSerial+=1;record=null}){
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal=20.dp).padding(bottom=32.dp)){
            Text(rowTitle(row),fontSize=21.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.padding(bottom=12.dp))
            if(recordLoading)LinearProgressIndicator(Modifier.fillMaxWidth())
            recordError?.let{Text(it,color=MaterialTheme.colorScheme.error,fontSize=12.sp)}
            row.optJSONObject("config")?.let{config->
                config.nullString("content")?.let{Text(android.text.Html.fromHtml(it,android.text.Html.FROM_HTML_MODE_COMPACT).toString(),fontSize=14.sp)}
                config.optJSONObject("table")?.let{table->
                    val headers=table.optJSONArray("headers")?:JSONArray();val values=table.optJSONArray("rows")?:JSONArray()
                    for(i in 0 until values.length()){
                        val cells=values.optJSONArray(i)?:continue
                        Text((0 until cells.length()).joinToString("\n"){j->"${headers.optString(j,"Column ${j+1}")}: ${cells.optString(j)}"},fontSize=14.sp,modifier=Modifier.padding(vertical=10.dp))
                        HorizontalDivider()
                    }
                }
            }
            visibleFields(row).forEach{(key,value)->
                Text(key.replace('_',' ').replaceFirstChar{it.uppercase()},fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=10.dp))
                Text(value,fontSize=14.sp)
                if(value.startsWith("https://")&&runCatching{Uri.parse(value).host}.getOrNull()!=null)TextButton(onClick={context.startActivity(Intent(Intent.ACTION_VIEW,Uri.parse(value)))}){Text("Open link")}
            }
        }
    }}
}

private val hiddenFields=setOf("id","user_id","workspace_id","project_id","milestone_id","parent_task_id","created_at","updated_at","_saved_at","recurrence_key","config")
private fun visibleFields(row:JSONObject):List<Pair<String,String>> = row.keys().asSequence().filter{it !in hiddenFields&&!row.isNull(it)}.map{key->key to when(val value=row.get(key)){
    is JSONObject->value.keys().asSequence().filter{!value.isNull(it)}.joinToString("\n"){"$it: ${value.get(it)}"}
    is JSONArray->(0 until value.length()).joinToString(", "){value.get(it).toString()}
    else->value.toString()
}}.filter{it.second.isNotBlank()}.toList()
private fun rowTitle(row:JSONObject)=listOf("title","name","label","goal","book","question","test","university","professor","institute","description","topic","task","subject","month").firstNotNullOfOrNull{row.nullString(it)}?:"Record"
private fun rowCaption(row:JSONObject):String {
    val labels=listOf("status","scheduled_date","due_date","target_date","deadline","date","month","cadence","subject","author","progress","chapter","widget_type").mapNotNull{row.nullString(it)}.toMutableList()
    if(row.has("total_tasks"))labels.add("${row.optInt("done_tasks")}/${row.optInt("total_tasks")} done")
    if(row.has("streak_days"))labels.add("${row.optInt("streak_days")} day streak")
    if(row.has("amount"))labels.add("${row.optString("currency")} ${row.optDouble("amount")}")
    if(row.has("outstanding"))labels.add("${row.optDouble("outstanding")} outstanding")
    if(row.has("target_amount"))labels.add("${row.optString("currency")} ${row.optDouble("saved_amount")} / ${row.optDouble("target_amount")}")
    return labels.joinToString(" · ").ifBlank{row.nullString("answer")?:row.nullString("notes")?:"Tap for details"}
}
private fun rowProgress(row:JSONObject):Float?=when {
    row.has("completion_pct")->(row.optDouble("completion_pct")/100).toFloat().coerceIn(0f,1f)
    row.optInt("total_tasks")>0->row.optInt("done_tasks").toFloat()/row.optInt("total_tasks")
    row.optInt("total_pages")>0->row.optInt("current_page").toFloat()/row.optInt("total_pages")
    row.optDouble("target_amount")>0->(row.optDouble("saved_amount")/row.optDouble("target_amount")).toFloat().coerceIn(0f,1f)
    else->null
}
@Composable private fun DashboardRow(title:String,caption:String,progress:Float?=null,onClick:(()->Unit)?=null){
    Column(Modifier.fillMaxWidth().then(if(onClick!=null)Modifier.clickable(onClick=onClick)else Modifier).padding(horizontal=20.dp,vertical=12.dp)){
        Row(verticalAlignment=Alignment.CenterVertically){Text(title,fontSize=15.sp,fontWeight=FontWeight.Medium,modifier=Modifier.weight(1f),maxLines=3,overflow=TextOverflow.Ellipsis);if(onClick!=null)Icon(Icons.Rounded.ChevronRight,null,tint=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.size(18.dp))}
        Text(caption,fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,maxLines=3,overflow=TextOverflow.Ellipsis,modifier=Modifier.padding(top=4.dp))
        if(progress!=null){LinearProgressIndicator(progress={progress.coerceIn(0f,1f)},modifier=Modifier.fillMaxWidth().padding(top=8.dp).height(3.dp));Text("${(progress*100).toInt()}%",fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=3.dp))}
    }
    HorizontalDivider(color=MaterialTheme.colorScheme.outlineVariant.copy(alpha=.4f),modifier=Modifier.padding(horizontal=20.dp))
}
@Composable private fun DashboardHeading(text:String){Text(text,fontSize=13.sp,fontWeight=FontWeight.SemiBold,color=MaterialTheme.colorScheme.primary,modifier=Modifier.padding(start=20.dp,top=20.dp,bottom=4.dp))}
private fun JSONObject.objects(key:String):List<JSONObject>{val a=optJSONArray(key)?:return emptyList();return (0 until a.length()).mapNotNull{a.optJSONObject(it)}}

@Composable private fun DashboardOverview(snapshot:JSONObject,onProject:(JSONObject)->Unit){
    val totals=snapshot.optJSONObject("totals")?:JSONObject()
    LazyColumn(Modifier.fillMaxSize(),contentPadding=PaddingValues(bottom=24.dp)){
        item{DashboardHeading("Progress today");DashboardRow("${totals.optInt("completed_today")} completed","${totals.optInt("open_tasks")} open · ${totals.optInt("overdue_tasks")} overdue · ${totals.optInt("completions_last_7_days")} finished in 7 days")}
        item{DashboardHeading("Projects")}
        itemsIndexed(snapshot.objects("projects")){_,project->DashboardRow(project.optString("name"),"${project.optInt("open_tasks")} left"+project.nullString("target_date")?.let{" · Due $it"}.orEmpty(),rowProgress(project)){onProject(project)}}
        item{DashboardHeading("Milestone health")}
        itemsIndexed(snapshot.objects("milestone_health")){_,row->DashboardRow(row.optString("name"),"${row.optString("project_name")} · ${row.optString("status")} · ${row.optInt("done")}/${row.optInt("total")}",row.optDouble("progress").toFloat())}
        item{DashboardHeading("Upcoming deadlines")}
        itemsIndexed(snapshot.objects("upcoming_deadlines")){_,row->DashboardRow(row.optString("name"),row.optString("date")+if(row.optBoolean("overdue"))" · Overdue"else " · ${row.optInt("days_left")} days left")}
        item{DashboardHeading("Habit streaks")}
        val streaks=snapshot.optJSONObject("streaks")?:JSONObject()
        streaks.keys().forEach{key->item{DashboardRow(key,"${streaks.optInt(key)} days")}}
    }
}
@Composable private fun FinanceSummary(data:JSONObject){
    val currencies=data.optJSONObject("currencies")?:JSONObject()
    LazyColumn(Modifier.fillMaxSize(),contentPadding=PaddingValues(bottom=24.dp)){
        item{DashboardHeading(data.optString("month_label","This month"))}
        if(currencies.length()==0)item{EmptyState("No transactions this month","Your funding plan and earlier transactions have their own tabs.")}
        currencies.keys().forEach{code->val values=currencies.getJSONObject(code);item{DashboardHeading(code);DashboardRow("Income ${values.optDouble("income")}","Expenses ${values.optDouble("expense")} · Net ${values.optDouble("net")}")}
            itemsIndexed(values.objects("by_category")){_,row->DashboardRow(row.optString("category"),"$code ${row.optDouble("amount")}")}
        }
    }
}
@Composable private fun FundingPlan(data:JSONObject,onRecord:(JSONObject)->Unit){
    val totals=data.optJSONObject("totals")?:JSONObject()
    val currency=totals.optString("base_currency")
    LazyColumn(Modifier.fillMaxSize(),contentPadding=PaddingValues(bottom=24.dp)){
        if(data.isNull("plan"))item{EmptyState("No funding plan yet","Your expenses and saving goals remain available.")}
        else{
            item{DashboardHeading("Funding position")}
            item{DashboardRow(totals.optString("headline","Funding plan"),totals.optString("status"))}
            listOf("cost_estimate","cost_paid","cost_outstanding","fund_expected","fund_received","fund_outstanding","gap","loan_needed").forEach{key->if(totals.has(key))item{DashboardRow(key.replace('_',' ').replaceFirstChar{it.uppercase()},"$currency ${totals.get(key)}")}}
            listOf("costs" to "Costs","funds" to "Funds").forEach{(key,label)->item{DashboardHeading(label)};itemsIndexed(data.objects(key)){_,row->DashboardRow(rowTitle(row),rowCaption(row),rowProgress(row)){onRecord(row)}}}
            item{DashboardHeading("Cash flow timeline")}
            itemsIndexed(data.optJSONObject("timeline")?.objects("months").orEmpty()){_,row->DashboardRow(row.optString("month"),"In $currency ${row.optDouble("in")} · Out ${row.optDouble("out")} · Balance ${row.optDouble("balance")}")}
        }
    }
}
