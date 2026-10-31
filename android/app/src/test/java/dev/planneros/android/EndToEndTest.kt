package dev.planneros.android

import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.UUID

/**
 * The Android app's data layer against a running Planner OS API, making the
 * same calls the screens make (editor save, timeline drop, tick, star, Focus
 * move and drop, delete) and checking the server after each. Skipped unless
 * PLANNER_E2E_URL is set; e2e/run.sh starts a local API and sets it.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35])
class EndToEndTest {
    private val url=System.getenv("PLANNER_E2E_URL")

    @Before fun connect(){
        assumeTrue("Set PLANNER_E2E_URL to a running API (see e2e/run.sh)",url!=null)
        PatchCapableHttp.install()
        SecureConfig.testConnection=url!! to "app-secret"
    }
    @After fun disconnect(){SecureConfig.testConnection=null}

    @Test fun everyActionReachesTheServer()=runBlocking{
        val repo=PlannerRepository(RuntimeEnvironment.getApplication())
        val today=logicalToday(ZonedDateTime.now(ZoneId.of("Asia/Kolkata")));val tomorrow=today.plusDays(1)
        val run=UUID.randomUUID().toString().take(6)
        suspend fun on(date:java.time.LocalDate,title:String)=repo.day(date).tasks.firstOrNull{it.title=="$title $run"}

        // Add, as the editor does.
        repo.create("Yoga $run",today,"07:15",30)
        repo.create("Coffee $run",today,"08:45",15,"oat milk")
        repo.create("Read $run",today,null,20)
        val yoga=on(today,"Yoga")!!
        assertEquals("07:15",yoga.time?.take(5))
        assertEquals("oat milk",on(today,"Coffee")?.notes)

        // Drop on the timeline, as finishDrag does.
        val slot=ScheduleSlot(today,10*60)
        repo.patch(yoga,JSONObject().put("scheduled_date",slot.date.toString()).put("start_time",slot.clock))
        assertEquals("a dragged task stays where it was dropped","10:00",on(today,"Yoga")?.time?.take(5))

        // Tick, untick and star, as toggleDone and toggleStar do.
        val coffee=on(today,"Coffee")!!
        repo.patch(coffee,JSONObject().put("done",true))
        assertTrue(on(today,"Coffee")!!.done)
        repo.patch(coffee.copy(done=true),JSONObject().put("done",false))
        assertFalse(on(today,"Coffee")!!.done)
        repo.patch(coffee,JSONObject().put("starred",true))
        assertTrue(on(today,"Coffee")!!.starred)

        // Edit, as the editor saves it.
        repo.patch(on(today,"Yoga")!!,JSONObject().put("title","Yoga flow $run").put("scheduled_date",today.toString())
            .put("start_time",JSONObject.NULL).put("estimated_minutes",45).put("notes","mat"))
        val flow=on(today,"Yoga flow")!!
        assertNull("time cleared",flow.time);assertEquals(45,flow.minutes);assertEquals("mat",flow.notes)

        // Focus: move to tomorrow, then drop an idea.
        repo.triage(listOf(on(today,"Read")!!.id),"move",tomorrow)
        assertNull(on(today,"Read"))
        assertEquals(tomorrow.toString(),on(tomorrow,"Read")?.date)
        assertTrue("the week view has it",repo.week(tomorrow).tasks.any{it.title=="Read $run"})
        repo.create("Idea $run",null,null,30)
        val idea=repo.inbox(true).tasks.first{it.title=="Idea $run"}
        repo.triage(listOf(idea.id),"drop")
        assertFalse("a dropped task leaves the inbox",repo.inbox(true).tasks.any{it.id==idea.id})

        // Delete.
        repo.delete(flow)
        assertNull(on(today,"Yoga flow"))
    }
}
