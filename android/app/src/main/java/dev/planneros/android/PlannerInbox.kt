package dev.planneros.android

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable internal fun InboxOverview(rows:List<Task>,dayTasks:List<Task>,dayLabel:String,overdueCount:Int,filter:String,onFilter:(String)->Unit){
    val open=rows.filterNot{it.done};val completed=dayTasks.count{it.done}
    Column(Modifier.fillMaxWidth().padding(horizontal=18.dp)){
        Text("${open.size} open · $overdueCount overdue · ${durationLabel(open.sumOf{it.minutes})}",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
        Row(Modifier.fillMaxWidth().padding(top=6.dp,bottom=3.dp),horizontalArrangement=Arrangement.SpaceBetween){
            Text("$dayLabel progress",fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
            Text("$completed / ${dayTasks.size} done",fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if(dayTasks.isNotEmpty())LinearProgressIndicator(progress={completed.toFloat()/dayTasks.size},modifier=Modifier.fillMaxWidth().height(3.dp),trackColor=MaterialTheme.colorScheme.primary.copy(alpha=.1f))
        Row(Modifier.horizontalScroll(rememberScrollState()).padding(vertical=5.dp),horizontalArrangement=Arrangement.spacedBy(7.dp)){
            listOf("Open","Overdue","Done").forEach{label->FilterChip(selected=filter==label,onClick={onFilter(label)},label={Text(label,fontSize=12.sp)})}
        }
    }
}

@Composable internal fun InboxSection(label:String,count:Int,minutes:Int){
    Row(Modifier.fillMaxWidth().padding(start=20.dp,end=20.dp,top=11.dp,bottom=5.dp),horizontalArrangement=Arrangement.SpaceBetween){
        Text("$label · $count",fontSize=12.sp,fontWeight=FontWeight.SemiBold,color=MaterialTheme.colorScheme.onSurfaceVariant)
        Text(durationLabel(minutes),fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
