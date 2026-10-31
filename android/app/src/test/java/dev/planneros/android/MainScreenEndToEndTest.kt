package dev.planneros.android

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.test.core.app.ActivityScenario
import androidx.work.Configuration
import androidx.work.WorkManager
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.UUID

/**
 * The real main screen against a running Planner OS API whose writes are slow
 * (e2e/server.py delays them, like a phone network): a tick shows before the
 * server answers and then reaches it, and a change the server refuses is
 * undone on screen with a message. Skipped unless PLANNER_E2E_URL is set.
 */
@RunWith(RobolectricTestRunner::class)
// A phone-sized screen, as on a Pixel or Galaxy.
@Config(sdk=[35],qualifiers="w411dp-h891dp-xxhdpi")
class MainScreenEndToEndTest {
    @get:Rule val rule=createEmptyComposeRule()
    private val url=System.getenv("PLANNER_E2E_URL")
    private val app get()=RuntimeEnvironment.getApplication()
    private val run=UUID.randomUUID().toString().take(6)
    private val today=logicalToday(ZonedDateTime.now(ZoneId.of("Asia/Kolkata")))
    private var scenario:ActivityScenario<MainActivity>?=null

    @Before fun connect(){
        assumeTrue("Set PLANNER_E2E_URL to a running API (see e2e/run.sh)",url!=null)
        PatchCapableHttp.install()
        SecureConfig.testConnection=url!! to "app-secret"
        runCatching{WorkManager.initialize(app,Configuration.Builder().build())}
    }
    @After fun disconnect(){scenario?.close();SecureConfig.testConnection=null}

    /** What the server holds, read directly: the app's own data layer rightly waits while its writes are out. */
    private fun onServer(title:String):Task?{
        val connection=java.net.URL("$url/v2/day?date=$today").openConnection() as java.net.HttpURLConnection
        connection.setRequestProperty("X-App-Key","app-secret")
        val body=connection.inputStream.readBytes().toString(Charsets.UTF_8)
        return Day.from(org.json.JSONObject(body).getJSONObject("data")).tasks.firstOrNull{it.title==title}
    }
    private fun waitFor(what:String,timeout:Long=10_000,condition:()->Boolean){
        val end=System.currentTimeMillis()+timeout
        while(System.currentTimeMillis()<end){rule.waitForIdle();if(condition())return;Thread.sleep(50)}
        fail("Timed out waiting for $what")
    }
    private fun shows(description:String)=rule.onAllNodesWithContentDescription(description).fetchSemanticsNodes().isNotEmpty()
    /** Scroll to the tick circle and tap it with a finger, as on the phone. */
    private fun tapTick(title:String){
        rule.onNodeWithContentDescription("Complete $title").performScrollTo().performTouchInput{click()}
        rule.waitForIdle()
    }

    @Test fun aTickShowsAtOnceAndReachesTheServer(){
        val title="Stretch $run"
        runBlocking{PlannerRepository(app).create(title,today,"23:00",15)}
        scenario=ActivityScenario.launch(MainActivity::class.java)
        waitFor("the task on the timeline"){shows("Complete $title")}

        tapTick(title)
        assertTrue("the tick shows straight away",shows("Reopen $title"))
        assertFalse("before the server has saved it",onServer(title)!!.done)

        waitFor("the server to save the tick"){onServer(title)!!.done}
        assertTrue("and the screen keeps it",shows("Reopen $title"))
    }

    @Test fun aRefusedChangeIsUndoneWithAMessage(){
        val title="Gone $run"
        val repo=PlannerRepository(app)
        runBlocking{repo.create(title,today,"23:15",15)}
        scenario=ActivityScenario.launch(MainActivity::class.java)
        waitFor("the task on the timeline"){shows("Complete $title")}
        // Deleted on another device: this phone still shows it, so the tick will be refused.
        runBlocking{repo.delete(repo.day(today).tasks.first{it.title==title})}

        tapTick(title)
        assertTrue("the tick shows straight away",shows("Reopen $title"))

        waitFor("the refused tick to be undone"){!shows("Reopen $title")}
        waitFor("a message about it"){rule.onAllNodesWithText("Details").fetchSemanticsNodes().isNotEmpty()}
    }
}
