package dev.planneros.android

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.LocalDate

/**
 * Two things at eleven have to look like two things at eleven.
 *
 * The timeline used to lay overlapping tasks out in columns and lost it in a
 * rewrite without a single test failing: the lane arithmetic was covered, the
 * screen that used it was not, so deleting the caller was invisible. This
 * checks the screen.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35],qualifiers="w393dp-h852dp-xxhdpi")
class OverlapScreenTest {
    @get:Rule val rule=createComposeRule()
    private val date=LocalDate.parse("2026-05-13")
    private fun task(id:String,time:String,minutes:Int)=
        Task(id,id,time,minutes,false,false,false,null,date.toString(),null,null)

    private fun show(day:List<Task>){
        rule.setContent{
            MaterialTheme{
                Box(Modifier.size(393.dp,852.dp)){
                    StructuredTimeline(day,emptyList(),date,-1,null,true,rememberScrollState(),null,Modifier.fillMaxSize(),
                        {},{},{},{},{},{},{_,_,_->},{},{}){_,_->}
                }
            }
        }
        rule.waitForIdle()
    }

    @Test fun twoTasksAtOnceAreDrawnBesideEachOther(){
        show(listOf(task("Standup","11:00",30),task("Deep work","11:00",120)))

        val standup=rule.onNodeWithText("Standup").assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        val deep=rule.onNodeWithText("Deep work").assertIsDisplayed().fetchSemanticsNode().boundsInRoot

        assertTrue("they should share the same stretch of the day, not follow one another: $standup vs $deep",
            standup.top < deep.bottom && deep.top < standup.bottom)
        assertTrue("and sit in separate columns: $standup vs $deep",
            standup.right <= deep.left || deep.right <= standup.left)
    }

    @Test fun oneAfterAnotherStaysASingleColumn(){
        show(listOf(task("First","09:00",30),task("Second","09:30",30)))

        val first=rule.onNodeWithText("First").fetchSemanticsNode().boundsInRoot
        val second=rule.onNodeWithText("Second").fetchSemanticsNode().boundsInRoot

        assertTrue("back to back belongs in one column, one above the other: $first vs $second",
            first.bottom <= second.top)
        assertEquals("and at the same place across", first.left.toDouble(), second.left.toDouble(), 1.0)
    }

    @Test fun eachOneCanStillBeOpenedAndTicked(){
        var opened:String?=null
        var ticked:String?=null
        val day=listOf(task("Standup","11:00",30),task("Deep work","11:00",120))
        rule.setContent{
            MaterialTheme{
                Box(Modifier.size(393.dp,852.dp)){
                    StructuredTimeline(day,emptyList(),date,-1,null,true,rememberScrollState(),null,Modifier.fillMaxSize(),
                        {opened=it.id},{ticked=it.id},{},{},{},{},{_,_,_->},{},{}){_,_->}
                }
            }
        }
        rule.waitForIdle()
        rule.onNodeWithText("Deep work").performClick()
        rule.waitForIdle()
        assertEquals("tapping one opens that one","Deep work",opened)
        rule.onNodeWithContentDescription("Complete Standup").performClick()
        rule.waitForIdle()
        assertEquals("and its own tick ticks it","Standup",ticked)
    }
}
