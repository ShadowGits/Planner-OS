package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

class DashboardCachePolicyTest {
    @Test fun usesItsOwnFiveMinuteWindow(){assertTrue(DashboardCachePolicy.fresh(1000,1000));assertTrue(DashboardCachePolicy.fresh(1000,300999));assertFalse(DashboardCachePolicy.fresh(1000,301000))}
    @Test fun reversedClockNeverMakesOldDashboardFresh(){assertFalse(DashboardCachePolicy.fresh(1000,999))}
}
