package dev.planneros.android

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.font.FontWeight
import kotlin.math.roundToInt
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject

/** Health is separate from the milestone's editable workflow status. */
internal fun milestoneHealthStatus(row:JSONObject):String = row.nullString("health_status")
    ?: row.optJSONObject("health")?.nullString("status")
    ?: if(recordDone(row))"complete" else if(row.optInt("total_tasks")>0&&row.optInt("done_tasks")>=row.optInt("total_tasks"))"complete" else "no_date"
internal fun milestoneIsComplete(row:JSONObject)=recordDone(row)||milestoneHealthStatus(row)=="complete"
internal fun milestoneHealthLabel(status:String)=when(status){
    "overdue"->"Overdue";"red"->"At risk";"amber"->"Slipping";"green"->"On track";"done","complete"->"Complete";"no_tasks"->"No tasks";else->"No dates"
}
// Exact Tailwind palette used by Deutschland-Dash/MilestoneHealth.tsx.
internal fun milestoneHealthColor(status:String)=Color(when(status){
    "overdue"->0xFFDC2626;"red"->0xFFEF4444;"amber"->0xFFF59E0B;"green"->0xFF10B981;"done","complete"->0xFF059669;else->0xFF9CA3AF
})
@Composable internal fun MilestoneHealthChip(status:String,modifier:Modifier=Modifier){
    val dark=MaterialTheme.colorScheme.surface.luminance()<.5f
    val (background,text)=when(status){
        "overdue","red"->Color(0xFFFEE2E2) to Color(0xFFB91C1C)
        "amber"->Color(0xFFFEF3C7) to Color(0xFFB45309)
        "green","complete","done"->Color(0xFFD1FAE5) to Color(0xFF047857)
        else->Color(0xFFF3F4F6) to Color(0xFF4B5563)
    }
    val nightText=when(status){"overdue","red"->Color(0xFFFCA5A5);"amber"->Color(0xFFFCD34D);"green","complete","done"->Color(0xFF6EE7B7);else->Color(0xFFD1D5DB)}
    Surface(modifier=modifier,color=if(dark)milestoneHealthColor(status).copy(alpha=.18f)else background,shape=RoundedCornerShape(8.dp)){
        Text(milestoneHealthLabel(status),color=if(dark)nightText else text,fontSize=12.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.padding(horizontal=9.dp,vertical=5.dp))
    }
}
@Composable internal fun MilestoneProgress(row:JSONObject,modifier:Modifier=Modifier){
    val health=row.optJSONObject("health")
    val total=row.optInt("total_tasks",health?.optInt("total")?:0)
    val done=row.optInt("done_tasks",health?.optInt("done")?:0)
    val progress=(if(total>0)done.toFloat()/total else 0f).coerceIn(0f,1f)
    val elapsed=health?.takeIf{!it.isNull("elapsed")}?.optDouble("elapsed")?.toFloat()?.coerceIn(0f,1f)
    val color=milestoneHealthColor(milestoneHealthStatus(row));val marker=MaterialTheme.colorScheme.onSurface
    Column(modifier){
        Box(Modifier.fillMaxWidth().height(18.dp),contentAlignment=Alignment.CenterStart){
            Box(Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)).background(MaterialTheme.colorScheme.surfaceVariant))
            if(progress>0)Box(Modifier.fillMaxWidth(progress).height(8.dp).clip(RoundedCornerShape(4.dp)).background(color))
            if(elapsed!=null)Canvas(Modifier.fillMaxWidth().height(16.dp)){
                val x=(size.width*elapsed).coerceIn(1.dp.toPx(),size.width-1.dp.toPx())
                drawLine(marker,Offset(x,0f),Offset(x,size.height),strokeWidth=2.dp.toPx())
            }
        }
        Text("${(progress*100).roundToInt()}% · $done/$total tasks"+elapsed?.let{" · ${(it*100).roundToInt()}% of time gone"}.orEmpty(),fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Recalculate the web's drift rule from its last known schedule after a local edit. */
internal fun recalculateMilestoneHealth(row:JSONObject,today:java.time.LocalDate):JSONObject{
    val next=JSONObject(row.toString());val health=next.optJSONObject("health")?.let{JSONObject(it.toString())}?:JSONObject()
    val total=next.optInt("total_tasks");val done=next.optInt("done_tasks")
    val progress=if(total>0)done.toDouble()/total else 0.0
    fun date(value:String?)=value?.let{runCatching{java.time.LocalDate.parse(it)}.getOrNull()}
    val target=date(next.nullString("target_date")?:next.nullString("tracking_last_date"))
    val start=date(next.nullString("tracking_start_date"))
    val elapsed=if(target!=null&&start!=null&&start<target)((java.time.temporal.ChronoUnit.DAYS.between(start,today).toDouble()/java.time.temporal.ChronoUnit.DAYS.between(start,target)).coerceIn(0.0,1.0))else null
    val status=milestoneRating(recordDone(next),done,total,target!=null&&today>target,elapsed)
    health.put("status",status).put("progress",progress).put("done",done).put("total",total).put("elapsed",elapsed?:JSONObject.NULL)
        .put("start_date",start?.toString()?:JSONObject.NULL).put("target_date",target?.toString()?:JSONObject.NULL)
    return next.put("health_status",status).put("health",health)
}
