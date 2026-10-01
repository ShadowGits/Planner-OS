package dev.planneros.android

/** elapsedRealtime drives live timers; wall time is only a reboot recovery anchor. */
data class TimerState(val taskId: String, val title: String, val durationMs: Long,
    val elapsedBeforeMs: Long=0, val anchorElapsedMs: Long=0, val anchorWallMs: Long=0,
    val bootCount: Int=0, val running: Boolean=true, val completionAlerted:Boolean=false) {
    fun elapsed(nowElapsed: Long,nowWall: Long,nowBoot: Int): Long = elapsedBeforeMs + if(!running) 0 else
        (if(nowBoot==bootCount) nowElapsed-anchorElapsedMs else nowWall-anchorWallMs).coerceAtLeast(0)
    fun remaining(nowElapsed: Long,nowWall: Long,nowBoot: Int): Long = durationMs-elapsed(nowElapsed,nowWall,nowBoot)
    /** Persist this transition before posting a sound: ticks and service restarts cannot replay it. */
    fun claimCompletion(nowElapsed:Long,nowWall:Long,nowBoot:Int):TimerState? =
        if(running&&!completionAlerted&&remaining(nowElapsed,nowWall,nowBoot)<=0)copy(completionAlerted=true)else null
    fun toggle(nowElapsed: Long,nowWall: Long,nowBoot: Int): TimerState = if(running)
        copy(elapsedBeforeMs=elapsed(nowElapsed,nowWall,nowBoot),running=false) else
        copy(anchorElapsedMs=nowElapsed,anchorWallMs=nowWall,bootCount=nowBoot,running=true)
    /** Reboot recovery uses wall time once, then returns to a monotonic clock. */
    fun recover(nowElapsed: Long,nowWall: Long,nowBoot: Int): TimerState = if(nowBoot==bootCount) this else
        copy(elapsedBeforeMs=elapsed(nowElapsed,nowWall,nowBoot),anchorElapsedMs=nowElapsed,
            anchorWallMs=nowWall,bootCount=nowBoot)
    fun metadata(newTitle: String,newDurationMs: Long): TimerState =
        copy(title=newTitle,durationMs=newDurationMs.coerceAtLeast(1))
}
fun timerText(remainingMs: Long): String {
    val seconds=kotlin.math.abs(remainingMs)/1000
    return (if(remainingMs<0) "+" else "") + "%02d:%02d".format(seconds/60,seconds%60)
}
