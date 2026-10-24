package dev.planneros.android

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@OptIn(ExperimentalMaterial3Api::class)
@Composable internal fun TaskTimeField(value:String,onChange:(String)->Unit,enabled:Boolean=true){
    val hour=value.substringBefore(':',"")
    val minute=value.substringAfter(':',"")
    val valid=normalizeTaskTime(value)!=null
    Column(Modifier.fillMaxWidth().padding(top=8.dp)){
        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically){
            Text("Start time · 24-hour",modifier=Modifier.weight(1f),fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
            TextButton(onClick={onChange("")},enabled=enabled&&value.isNotEmpty()){Text("Clear time")}
        }
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(12.dp)){
            ClockSegment("Hour",hour,(0..23).map{"%02d".format(java.util.Locale.ROOT,it)},enabled,Modifier.weight(1f)){h->
                onChange(if(h.isEmpty()&&minute.isEmpty())"" else "$h:${minute.ifEmpty{if(h.isNotEmpty())"00"else ""}}")
            }
            ClockSegment("Minute",minute,((0..55 step 5).map{"%02d".format(java.util.Locale.ROOT,it)}+listOfNotNull(minute.toIntOrNull()?.takeIf{it in 0..59}?.let{"%02d".format(java.util.Locale.ROOT,it)})).distinct().sorted(),enabled,Modifier.weight(1f)){m->onChange(if(hour.isEmpty()&&m.isEmpty())"" else "$hour:$m")}
        }
        Text(if(!valid)"Choose an hour 00–23 and minute 00–59, or clear the time." else if(value.isEmpty())"No start time · stays in Inbox" else "24-hour time · type any minute or choose a 5-minute step",fontSize=12.sp,color=if(valid)MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.error,modifier=Modifier.padding(top=6.dp))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun ClockSegment(label:String,value:String,choices:List<String>,enabled:Boolean,modifier:Modifier,onChange:(String)->Unit){
    var expanded by remember{mutableStateOf(false)}
    ExposedDropdownMenuBox(expanded=expanded&&enabled,onExpandedChange={if(enabled)expanded=it},modifier=modifier){
        OutlinedTextField(value=value,onValueChange={text->
            if(text.length<=2&&text.all{it in '0'..'9'}){expanded=false;onChange(text)}
        },label={Text(label)},placeholder={Text("—")},enabled=enabled,singleLine=true,
            keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number),
            trailingIcon={ExposedDropdownMenuDefaults.TrailingIcon(expanded=expanded,modifier=Modifier.menuAnchor(MenuAnchorType.SecondaryEditable))},
            modifier=Modifier.fillMaxWidth().menuAnchor(MenuAnchorType.PrimaryEditable))
        ExposedDropdownMenu(expanded=expanded&&enabled,onDismissRequest={expanded=false},modifier=Modifier.heightIn(max=240.dp)){
            choices.forEach{choice->DropdownMenuItem(text={Text(choice)},onClick={expanded=false;onChange(choice)})}
        }
    }
}
