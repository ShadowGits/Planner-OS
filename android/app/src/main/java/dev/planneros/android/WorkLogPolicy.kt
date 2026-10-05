package dev.planneros.android

internal object WorkLogPolicy {
    fun requiresActualEntry(state:TimerState,elapsed:Long)=state.completionAlerted||elapsed>=state.durationMs
    fun requiresAutomaticPrompt(state:TimerState,elapsed:Long)=!state.scheduled&&requiresActualEntry(state,elapsed)
    fun elapsedSeconds(elapsed:Long)=(elapsed.coerceAtLeast(0)/1000).coerceAtMost(86400).toInt()
    fun remaining(planned:Int,worked:Int,entry:Int)=(planned-worked-entry).coerceAtLeast(0)
    fun parse(hours:String,minutes:String,seconds:String="0"):Int? {
        val h=hours.ifBlank{"0"}.toIntOrNull()?:return null
        val m=minutes.ifBlank{"0"}.toIntOrNull()?:return null
        val s=seconds.ifBlank{"0"}.toIntOrNull()?:return null
        return (h.toLong()*3600+m*60+s).takeIf{h in 0..24&&m in 0..59&&s in 0..59&&it in 0..86400}?.toInt()
    }
}
internal fun workDuration(seconds:Int):String {
    val n=seconds.coerceAtLeast(0);val parts=mutableListOf<String>()
    if(n/3600>0)parts.add("${n/3600}h")
    if(n/60%60>0)parts.add("${n/60%60}m")
    if(n%60>0)parts.add("${n%60}s")
    return parts.joinToString(" ").ifBlank{"0m"}
}
