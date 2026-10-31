package dev.planneros.android

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
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
 * Real touch input against the Timeline, wired the way MainActivity wires it
 * (DragState → DragPreview → finishDrag), so a frozen list or a dead drag
 * fails here instead of on the phone.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35])
class StructuredTimelineGestureTest {
    @get:Rule val rule=createComposeRule()
    private val date=LocalDate.parse("2026-05-13")
    private fun task(id:String,hour:Int,minutes:Int=45)=Task(id,"Task $id","%02d:00".format(hour),minutes,false,false,false,null,date.toString(),null,null)
    private val day=(6..22).map{task("t$it",it)}

    private class Harness{
        var scrollValue=0;var edited:String?=null;var dropped:Pair<String,ScheduleSlot>?=null;var started=false
    }

    private fun show(h:Harness){
        rule.setContent{
            MaterialTheme{
                val scroll=rememberScrollState()
                var drag by remember{mutableStateOf<DragState?>(null)}
                val density=LocalDensity.current.density
                val entries=remember{dayEntries(day)}
                val preview=dragPreviewOf(drag,scroll.value,density,entries)
                h.scrollValue=scroll.value
                Box(Modifier.size(400.dp,700.dp)){
                    StructuredTimeline(day,emptyList(),date,-1,null,true,scroll,preview,Modifier.fillMaxSize(),
                        edit={h.edited=it.id},done={},focus={},gap={},
                        dragStart={h.started=true;drag=DragState(it,date,scroll.value)},
                        dragMove={_,offset,pointer->drag=drag?.let{d->d.copy(deltaX=d.deltaX+offset.x,deltaY=d.deltaY+offset.y,pointerY=pointer.y,pointerX=pointer.x)}},
                        dragEnd={t->dragPreviewOf(drag,scroll.value,density,entries)?.let{h.dropped=t.id to it.target};drag=null},
                        dragCancel={drag=null},viewport={_,_->})
                }
            }
        }
    }

    @Test fun listScrolls(){
        val h=Harness();show(h)
        rule.onNodeWithText("Task t6").assertIsDisplayed()
        rule.onRoot().performTouchInput{swipeUp(startY=bottom-40f,endY=top+40f,durationMillis=300)}
        rule.waitForIdle()
        assertTrue("timeline should scroll, was ${h.scrollValue}",h.scrollValue>0)
    }

    @Test fun dragWithFramesBetweenMovesTracksTheFinger(){
        val h=Harness();show(h)
        val node=rule.onNodeWithText("Task t9")
        node.performTouchInput{down(center)}
        rule.mainClock.advanceTimeBy(400)
        val step=with(rule.density){30.dp.toPx()}
        repeat(4){node.performTouchInput{moveBy(androidx.compose.ui.geometry.Offset(0f,step))};rule.mainClock.advanceTimeBy(16)}
        node.performTouchInput{up()}
        rule.waitForIdle()
        assertEquals("t9",h.dropped?.first)
        assertEquals("10:15",h.dropped?.second?.clock)
    }

    @Test fun swipingOverATaskScrollsInsteadOfDragging(){
        val h=Harness();show(h)
        rule.onNodeWithText("Task t8").performTouchInput{swipeUp(startY=centerY,endY=centerY-300f,durationMillis=150)}
        rule.waitForIdle()
        assertTrue("a quick swipe on a task should scroll, was ${h.scrollValue}",h.scrollValue>0)
        assertFalse("a quick swipe should not pick the task up",h.started)
    }

    @Test fun tapOpensTheTask(){
        val h=Harness();show(h)
        rule.onNodeWithText("Task t7").performClick()
        rule.waitForIdle()
        assertEquals("t7",h.edited)
    }

    @Test fun holdAndDragMovesTheTask(){
        val h=Harness();show(h)
        val node=rule.onNodeWithText("Task t7")
        node.performTouchInput{
            down(center)
            advanceEventTime(600)
            // 120dp down from the 07:00 task is a quarter of the way into the 08:00 one
            // (rows of 80dp, 16dp of spine between), so the drop lands where it shows: 08:15.
            val step=(120.dp.toPx())/12
            repeat(12){moveBy(androidx.compose.ui.geometry.Offset(0f,step));advanceEventTime(16)}
            up()
        }
        rule.waitForIdle()
        assertTrue("long press should start a drag",h.started)
        assertEquals("t7",h.dropped?.first)
        assertEquals("08:15",h.dropped?.second?.clock)
    }
}
