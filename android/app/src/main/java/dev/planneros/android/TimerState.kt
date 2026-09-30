package dev.planneros.android

/** elapsedRealtime drives live timers; wall time is only a reboot recovery anchor. */
data class TimerState(val taskId: String, val title: String, val durationMs: Long,
    val elapsedBeforeMs: Long=0, val anchorElapsedMs: Long=0, val anchorWallMs: Long=0,
    val bootCount: Int=0, val running: Boolean=true) {
    fun elapsed(nowElapsed: Long,nowWall: Long,nowBoot: Int): Long = elapsedBeforeMs + if(!running) 0 else
        (if(nowBoot==bootCount) nowElapsed-anchorElapsedMs else nowWall-anchorWallMs).coerceAtLeast(0)
    fun remaining(nowElapsed: Long,nowWall: Long,nowBoot: Int): Long = durationMs-elapsed(nowElapsed,nowWall,nowBoot)
    fun toggle(nowElapsed: Long,nowWall: Long,nowBoot: Int): TimerState = if(running)
        copy(elapsedBeforeMs=elapsed(nowElapsed,nowWall,nowBoot),running=false) else
        copy(anchorElapsedMs=nowElapsed,anchorWallMs=nowWall,bootCount=nowBoot,running=true)
}
fun timerText(remainingMs: Long): String {
    val seconds=kotlin.math.abs(remainingMs)/1000
    return (if(remainingMs<0) "+" else "") + "%02d:%02d".format(seconds/60,seconds%60)
}
