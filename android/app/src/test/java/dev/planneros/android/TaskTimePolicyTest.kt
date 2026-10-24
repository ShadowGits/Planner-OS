package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

class TaskTimePolicyTest {
    @Test fun midnightNoonAndLastMinuteUse24HourClock(){
        for(time in listOf("00:00","12:00","14:30","23:59"))assertEquals(time,normalizeTaskTime(time))
    }
    @Test fun typingSingleDigitsAndExactMinutesIsSupported(){
        assertEquals("09:07",normalizeTaskTime("9:7"))
        assertEquals("14:17",normalizeTaskTime("14:17"))
    }
    @Test fun onlyFullyBlankMeansUnscheduled(){
        assertEquals("",normalizeTaskTime(""))
        for(time in listOf(":",":30","14:","24:00","14:60","-1:30","1:2:3","1a:30","01:001"))assertNull(time,normalizeTaskTime(time))
    }
}
