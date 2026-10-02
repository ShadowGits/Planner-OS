package dev.planneros.android

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.BackHandler
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
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
import java.util.UUID
import androidx.core.view.WindowInsetsControllerCompat

class DashboardActivity:ComponentActivity(){
    private val dashboardSession=mutableStateOf("")
    override fun onResume(){super.onResume();FocusWorkLogs.foreground++;dashboardSession.value="${SecureConfig(this).generation}:${Reminders.revision(this)}"}
    override fun onPause(){FocusWorkLogs.foreground=(FocusWorkLogs.foreground-1).coerceAtLeast(0);super.onPause()}
    override fun onCreate(savedInstanceState:Bundle?){
        super.onCreate(savedInstanceState);enableEdgeToEdge()
        setContent{
            val theme=getSharedPreferences("appearance",MODE_PRIVATE).getString("theme","system")
            val dark=theme=="dark"||theme!="light"&&isSystemInDarkTheme()
            val colors=plannerColorScheme(dark)
            SideEffect{WindowInsetsControllerCompat(window,window.decorView).apply{isAppearanceLightStatusBars=!dark;isAppearanceLightNavigationBars=!dark}}
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
    val compactNav=LocalConfiguration.current.screenWidthDp<360&&LocalDensity.current.fontScale>1.2f
    val context=LocalContext.current;val repo=remember{DashboardRepository(context)};val scope=rememberCoroutineScope()
    LaunchedEffect(Unit){while(true){FocusWorkLogs.prompt(context);kotlinx.coroutines.delay(1000)}}
    var group by rememberSaveable{mutableStateOf("Overview")};var subtab by rememberSaveable{mutableIntStateOf(0)}
    var menuOpen by rememberSaveable{mutableStateOf(false)};var searchOpen by rememberSaveable{mutableStateOf(false)}
    var projectInfo by rememberSaveable{mutableStateOf("{}")}
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
        projectInfo=row.toString()
        if(row.optString("name")=="Finance"){group="Money";subtab=1;project=null}
        else{group="Projects";project=row.nullString("id");projectName=row.optString("name","Project");subtab=0};query=""
    }
    fun showRecord(row:JSONObject){
        detailSerial+=1;val serial=detailSerial
        record=row;recordError=null;recordLoading=false
        val id=row.nullString("id")?:return
        val detailSection=row.nullString("_section")?:section
        if(detailSection in listOf("overview","week")||detailSection.startsWith("finance_")&&detailSection!="finance_transactions"||runCatching{UUID.fromString(id)}.isFailure)return
        val key=id;val recordPath=repo.path(detailSection,if(group=="Projects")project else null,row=id)
        recordLoading=true
        scope.launch{
            try{val data=repo.load(recordPath);if(detailSerial==serial&&record?.nullString("id")==key&&generation==repo.generation)record=data.getJSONObject("record").put("_section",detailSection)}
            catch(cancel:CancellationException){throw cancel}catch(error:Exception){if(detailSerial==serial&&record?.nullString("id")==key)recordError=error.message}
            finally{if(detailSerial==serial&&record?.nullString("id")==key)recordLoading=false}
        }
    }
    LaunchedEffect(path,generation){query="";load()}
    BackHandler(enabled=project!=null&&group=="Projects"){project=null;subtab=0}
    val data=page.data
    val array=when(section){"finance_goals"->data?.optJSONArray("goals");"week"->data?.optJSONArray("items");else->data?.optJSONArray("rows")}?:JSONArray()
    val rows=(0 until array.length()).mapNotNull{array.optJSONObject(it)}
    val visible=rows.filter{query.isBlank()||dashboardFields(it).any{entry->entry.second.contains(query,true)}||rowTitle(it).contains(query,true)}
    fun selectGroup(label:String){group=label;subtab=0;query="";searchOpen=false;menuOpen=false}
    Scaffold(containerColor=MaterialTheme.colorScheme.background,topBar={
        TopAppBar(title={Column{
            Text(if(project!=null&&group=="Projects")projectName else if(group=="Overview")"Dashboard" else group,fontSize=22.sp,fontWeight=FontWeight.SemiBold,maxLines=1,overflow=TextOverflow.Ellipsis)
            if(!compactNav)Text(if(project!=null&&group=="Projects")"Project workspace" else "Your work at a glance",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,maxLines=1,overflow=TextOverflow.Ellipsis)
        }},navigationIcon={IconButton(onClick={if(project!=null&&group=="Projects"){project=null;subtab=0}else exit()}){Icon(Icons.AutoMirrored.Rounded.ArrowBack,"Back to "+if(project!=null&&group=="Projects")"projects" else "day")}},
            actions={if(rows.isNotEmpty()&&section!="week")IconButton(onClick={searchOpen=!searchOpen;if(!searchOpen)query=""}){Icon(Icons.Rounded.Search,"Search this section")}
                IconButton(onClick={load(true)},enabled=!page.loading){if(page.loading)CircularProgressIndicator(Modifier.size(20.dp),strokeWidth=2.dp)else Icon(Icons.Rounded.Refresh,"Refresh dashboard section")}},
            colors=TopAppBarDefaults.topAppBarColors(containerColor=MaterialTheme.colorScheme.background))
    },bottomBar={
        NavigationBar(containerColor=MaterialTheme.colorScheme.surface,tonalElevation=0.dp){
            listOf("Overview","Projects","Money","Browse").forEach{label->
                val selected=if(label=="Browse")group !in listOf("Overview","Projects","Money")else group==label
                NavigationBarItem(selected=selected,onClick={if(label=="Browse")menuOpen=true else selectGroup(label)},icon={Icon(dashboardIcon(label),if(compactNav&&label=="Projects")"Projects"else null)},label={Text(if(label=="Overview")"Home"else if(label=="Projects"&&compactNav)"Work"else label,fontSize=12.sp,maxLines=1)},
                    colors=NavigationBarItemDefaults.colors(selectedIconColor=Color.White,indicatorColor=PlannerPalette.Wine,selectedTextColor=MaterialTheme.colorScheme.onSurface,unselectedIconColor=MaterialTheme.colorScheme.onSurfaceVariant,unselectedTextColor=MaterialTheme.colorScheme.onSurfaceVariant))
            }
        }
    }){padding->
        Column(Modifier.fillMaxSize().padding(padding)){
            if(choices.size>1)Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal=16.dp),horizontalArrangement=Arrangement.spacedBy(8.dp)){
                choices.forEachIndexed{index,choice->
                    val bringIntoView=remember(choice.second){BringIntoViewRequester()}
                    LaunchedEffect(subtab,choice.second){if(subtab==index)bringIntoView.bringIntoView()}
                    FilterChip(selected=subtab==index,onClick={subtab=index;query=""},modifier=Modifier.bringIntoViewRequester(bringIntoView),label={Text(choice.first,fontSize=14.sp)},leadingIcon={Icon(dashboardIcon(choice.second),null,modifier=Modifier.size(18.dp))},
                    colors=FilterChipDefaults.filterChipColors(selectedContainerColor=PlannerPalette.Wine,selectedLabelColor=Color.White,selectedLeadingIconColor=Color.White))}
            }
            if(section=="week"||section=="finance_summary"){
                val anchor=LocalDate.parse(selectedDate);val displayDate=if(section=="week")anchor.minusDays((anchor.dayOfWeek.value-1).toLong())else anchor
                Row(Modifier.fillMaxWidth().padding(horizontal=16.dp,vertical=2.dp),verticalAlignment=Alignment.CenterVertically){
                    IconButton(onClick={if(section=="week")weekDate=anchor.minusWeeks(1).toString()else monthDate=anchor.minusMonths(1).toString()}){Icon(Icons.Rounded.ChevronLeft,"Previous "+if(section=="week")"week" else "month")}
                    Text(displayDate.format(DateTimeFormatter.ofPattern(if(section=="week")if(displayDate.year==LocalDate.now().year)"'Week of' d MMM"else "'Week of' d MMM yyyy" else "MMMM yyyy",Locale.getDefault())),fontSize=17.sp,fontWeight=FontWeight.Medium,modifier=Modifier.weight(1f))
                    IconButton(onClick={if(section=="week")weekDate=anchor.plusWeeks(1).toString()else monthDate=anchor.plusMonths(1).toString()}){Icon(Icons.Rounded.ChevronRight,"Next "+if(section=="week")"week" else "month")}
                }
            }
            if(searchOpen)OutlinedTextField(query,{query=it},modifier=Modifier.fillMaxWidth().padding(horizontal=16.dp,vertical=6.dp),singleLine=true,label={Text("Search "+group.lowercase())},leadingIcon={Icon(Icons.Rounded.Search,null)})
            if(page.unavailable)DashboardMessage(dashboardIcon(group),"Tracker not set up",page.error.orEmpty())
            else if(page.error!=null&&data==null)DashboardMessage(Icons.Rounded.CloudOff,"Couldn't load this view",page.error.orEmpty()){load(true)}
            else if(data==null)DashboardMessage(dashboardIcon(group),"Loading "+group.lowercase(),"Opening this view…",loading=true)
            else{
                page.error?.let{DashboardNotice(it)}
                val warnings=data.optJSONArray("warnings")
                if(section!="overview"&&warnings!=null&&warnings.length()>0)DashboardNotice((0 until warnings.length()).joinToString(" "){warnings.optString(it)})
                when(section){
                    "overview"->DashboardOverview(data.optJSONObject("snapshot")?:JSONObject(),::selectProject,::showRecord,{selectGroup("Projects")}){selectGroup("Week")}
                    "finance_summary"->FinanceSummary(data)
                    "finance_plan"->FundingPlan(data,::showRecord)
                    "week"->DashboardWeek(data,::showRecord)
                    else->DashboardRecords(section,visible,if(project!=null&&group=="Projects")runCatching{JSONObject(projectInfo)}.getOrNull()else null,::showRecord,::selectProject,
                        !data.isNull("next_offset")&&data.has("next_offset"),page.loading){load(offset=data.optInt("next_offset"))}
                }
            }
        }
    }
    if(menuOpen)ModalBottomSheet(onDismissRequest={menuOpen=false},sheetState=rememberModalBottomSheetState(skipPartiallyExpanded=true)){
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal=20.dp).padding(bottom=32.dp)){
            Text("Explore your workspace",fontSize=24.sp,fontWeight=FontWeight.SemiBold)
            Text("Choose what you want to see",fontSize=15.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=4.dp,bottom=16.dp))
            groups.chunked(2).forEach{pair->Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(12.dp)){
                pair.forEach{label->Surface(onClick={selectGroup(label)},shape=RoundedCornerShape(18.dp),color=MaterialTheme.colorScheme.secondaryContainer,modifier=Modifier.weight(1f).padding(bottom=12.dp)){
                    Column(Modifier.padding(16.dp)){Icon(dashboardIcon(label),null,modifier=Modifier.size(28.dp),tint=MaterialTheme.colorScheme.onSecondaryContainer);Text(label,fontSize=17.sp,fontWeight=FontWeight.SemiBold,color=MaterialTheme.colorScheme.onSecondaryContainer,modifier=Modifier.padding(top=12.dp))}
                }
            }}}
        }
    }
    record?.let{row->ModalBottomSheet(onDismissRequest={detailSerial+=1;record=null},sheetState=rememberModalBottomSheetState(skipPartiallyExpanded=true)){DashboardDetail(row,recordLoading,recordError)}}
}
