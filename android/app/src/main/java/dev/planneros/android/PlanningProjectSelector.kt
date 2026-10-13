package dev.planneros.android

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable internal fun PlanningProjectSelector(projects:List<PlanningProject>,selectedId:String?,onSelect:(String)->Unit,modifier:Modifier=Modifier,enabled:Boolean=true){
    Row(modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(MaterialTheme.colorScheme.surfaceContainer).padding(3.dp),horizontalArrangement=Arrangement.spacedBy(3.dp)){
        projects.forEach{project->
            val selected=project.id==selectedId
            Box(Modifier.weight(1f).clip(RoundedCornerShape(9.dp))
                .background(if(selected)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainer)
                .semantics{this.selected=selected}
                .clickable(enabled=enabled,role=Role.RadioButton,onClick={onSelect(project.id)})
                .heightIn(min=44.dp).padding(horizontal=6.dp,vertical=6.dp),contentAlignment=Alignment.Center){
                Text(project.name,fontSize=12.sp,lineHeight=15.sp,fontWeight=if(selected)FontWeight.SemiBold else FontWeight.Normal,
                    color=if(selected)MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface)
            }
        }
    }
}
