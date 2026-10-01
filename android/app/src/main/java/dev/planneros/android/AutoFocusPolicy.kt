package dev.planneros.android

import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId

data class AutoFocusBlock(val id:String,val title:String,val startMillis:Long,val endMillis:Long,
                          val originDate:String) {
    // Metadata edits do not turn a canceled occurrence into a new occurrence.
    val occurrence:String get()="$id@$startMillis"
    fun elapsed(now:Long)=(now-startMillis).coerceIn(0,endMillis-startMillis)
}

fun autoFocusBlock(id:String,title:String,clockMinutes:Int,duration:Int,done:Boolean,
                   dayDate:String,timezone:String):AutoFocusBlock? {
    if(done||id.isBlank()||id.startsWith("draft:")||id.startsWith("local:")||id.startsWith("pending:")||
        clockMinutes !in 0 until 30*60||duration !in 1..1440)return null
    val local=LocalDate.parse(dayDate).plusDays((clockMinutes/1440).toLong())
        .atTime(LocalTime.of((clockMinutes/60)%24,clockMinutes%60))
    val start=local.atZone(ZoneId.of(timezone)).toInstant().toEpochMilli()
    return AutoFocusBlock(id,title,start,start+duration*60_000L,dayDate)
}

/** Latest-starting active block wins overlaps; IDs break equal-time ties. */
fun autoFocusCandidate(blocks:List<AutoFocusBlock>,now:Long,consumed:Set<String>):AutoFocusBlock? {
    val selected=blocks.filter{it.startMillis<=now&&now<it.endMillis}
        .sortedWith(compareByDescending<AutoFocusBlock>{it.startMillis}.thenBy{it.id}).firstOrNull()
    // Do not fall back to an older overlapping block after pausing/canceling
    // the selected occurrence. The next block may start a new timer.
    return selected?.takeIf{it.occurrence !in consumed}
}
