package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

class TimerStateTest {
    private val start=TimerState("a","Reading",60_000,anchorElapsedMs=1000,anchorWallMs=10_000,bootCount=3)
    @Test fun countdownUsesMonotonicTimeEvenIfWallClockChanges(){assertEquals(40_000,start.remaining(21_000,999_999,3))}
    @Test fun pauseAndResumeDoNotCountPausedTime(){
        val paused=start.toggle(21_000,30_000,3)
        assertEquals(40_000,paused.remaining(71_000,80_000,3))
        val resumed=paused.toggle(71_000,80_000,3)
        assertEquals(30_000,resumed.remaining(81_000,90_000,3))
    }
    @Test fun recoveryAfterRebootUsesPersistedWallAnchor(){assertEquals(30_000,start.remaining(5000,40_000,4))}
    @Test fun overtimeKeepsCountingAndDoesNotCompleteTask(){assertEquals(-15_000,start.remaining(76_000,85_000,3));assertEquals("+00:15",timerText(-15_000))}
    @Test fun clockMovingBackwardsAtRebootNeverAddsTimeToDuration(){assertEquals(60_000,start.remaining(0,5000,4))}
    @Test fun repeatedPauseResumePreservesAllFocusTime(){
        val one=start.toggle(11_000,20_000,3).toggle(31_000,40_000,3)
        val two=one.toggle(41_000,50_000,3).toggle(61_000,70_000,3)
        assertEquals(30_000,two.remaining(71_000,80_000,3))
    }
    @Test fun longDurationAndOvertimeFormatting(){assertEquals("120:00",timerText(7_200_000));assertEquals("00:00",timerText(0))}
    @Test fun rebootRecoveryReturnsToMonotonicTiming(){
        val restored=start.recover(5000,40_000,4)
        assertEquals(30_000,restored.remaining(5000,40_000,4))
        assertEquals(20_000,restored.remaining(15_000,900_000,4))
    }
    @Test fun metadataRefreshPreservesFocusedAndPausedTime(){
        val paused=start.toggle(21_000,30_000,3)
        val updated=paused.metadata("Updated title",120_000)
        assertFalse(updated.running)
        assertEquals("Updated title",updated.title)
        assertEquals(100_000,updated.remaining(100_000,200_000,3))
        assertEquals(20_000,updated.elapsedBeforeMs)
    }
    @Test fun shorteningAnActiveTaskKeepsWorkAlreadyDoneAsOvertime(){
        val updated=start.metadata("Shortened block",10_000)
        assertEquals(-10_000,updated.remaining(21_000,30_000,3))
        assertTrue(updated.running)
    }
}
