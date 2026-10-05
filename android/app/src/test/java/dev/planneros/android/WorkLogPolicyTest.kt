package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

class WorkLogPolicyTest {
    private val timer=TimerState("task","Study",10_800_000,anchorElapsedMs=1000,anchorWallMs=1000,bootCount=1)
    @Test fun expiredTimerAlwaysRequiresActualWorkEntry(){
        assertTrue(WorkLogPolicy.requiresActualEntry(timer,10_800_000))
        assertTrue(WorkLogPolicy.requiresActualEntry(timer.copy(completionAlerted=true),0))
    }
    @Test fun scheduledExpiryNeverRequiresAutomaticPromptButManualTimerStillDoes(){
        assertFalse(WorkLogPolicy.requiresAutomaticPrompt(timer.copy(scheduled=true),timer.durationMs))
        assertFalse(WorkLogPolicy.requiresAutomaticPrompt(timer.copy(scheduled=true,completionAlerted=true),0))
        assertTrue(WorkLogPolicy.requiresAutomaticPrompt(timer,timer.durationMs))
        assertFalse(WorkLogPolicy.requiresAutomaticPrompt(timer,timer.durationMs-1))
        assertTrue(timer.copy(scheduled=true).toggle(2000,2000,1).recover(3000,3000,2).scheduled)
    }
    @Test fun pausedFinishUsesElapsedFocusWithoutPromptOrPausedTime(){
        val paused=timer.toggle(5_401_000,5_401_000,1)
        val elapsed=paused.elapsed(10_801_000,10_801_000,1)
        assertEquals(5400,WorkLogPolicy.elapsedSeconds(elapsed))
        assertFalse(WorkLogPolicy.requiresActualEntry(paused,elapsed))
    }
    @Test fun exactSecondEntryAndRemainder(){
        assertEquals(5417,WorkLogPolicy.parse("1","30","17"))
        assertEquals(43,WorkLogPolicy.remaining(60,0,17))
        assertNull(WorkLogPolicy.parse("24","1"))
        assertNull(WorkLogPolicy.parse("2147483647","0"))
        assertNull(WorkLogPolicy.parse("0","60"))
        assertNull(WorkLogPolicy.parse("0","0","60"))
        assertEquals("1h 30m 17s",workDuration(5417))
    }
    @Test fun scheduledFocusUsesExactRemainingTime(){
        val block=autoFocusBlock("task","Study",540,180,false,"2026-10-02","Asia/Kolkata",43)!!
        assertEquals(43_000,block.endMillis-block.startMillis)
        assertNull(autoFocusBlock("task","Study",540,180,false,"2026-10-02","Asia/Kolkata",0))
    }
    @Test fun timerCopiesRetainRetryIdentityAndNewSessionsAreDistinct(){
        assertEquals(timer.sessionId,timer.toggle(2000,2000,1).sessionId)
        assertNotEquals(timer.sessionId,TimerState("task","Study",60_000).sessionId)
    }
}
