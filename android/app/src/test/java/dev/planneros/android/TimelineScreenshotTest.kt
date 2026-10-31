package dev.planneros.android

import android.graphics.Bitmap
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.unit.dp
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File
import java.time.LocalDate

/**
 * Draws the Timeline with the same day as Structured's help screenshots, to put
 * side by side with them. Writes PNGs to SCREENSHOT_DIR; skipped without it.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk=[35],qualifiers="w393dp-h852dp-xxhdpi")
class TimelineScreenshotTest {
    @get:Rule val rule=createAndroidComposeRule<ComponentActivity>()
    private val dir=System.getenv("SCREENSHOT_DIR")
    private val date=LocalDate.parse("2025-10-16")
    private fun task(title:String,time:String?,minutes:Int,done:Boolean=false)=
        Task(title,title,time,minutes,done,false,false,null,date.toString(),null,null)
    private val day=listOf(
        task("Lunch break","12:30",60,done=true),task("Blogpost draft","13:30",120),task("Coffee break","15:45",15),
        task("Check emails","16:00",30),task("Get home","17:00",30),task("Me time","17:30",60),
        task("Prepare dinner","18:45",15),task("Dinner","19:00",30),
    )
    private val allDay=listOf(task("Water plants",null,15),task("Take out trash",null,15,done=true))

    @Composable private fun Screen(now:Int,preview:DragPreview?=null){
        MaterialTheme{
            Column(Modifier.fillMaxSize().background(Color(0xFFF2F2F7))){
                Box(Modifier.padding(start=16.dp,top=12.dp,bottom=6.dp)){MonthTitle(date)}
                StructuredWeekStrip(date,date,{d->if(d==date)day.map(::blockColor) else listOf(Color(0xFF6085A8),Color(0xFF91BE6C))}){}
                Box(Modifier.fillMaxSize().background(Color.White,RoundedCornerShape(topStart=28.dp,topEnd=28.dp)).padding(top=10.dp)){
                    StructuredTimeline(day,allDay,date,now,null,true,rememberScrollState(),preview,Modifier.fillMaxSize(),
                        {},{},{},{},{},{_,_,_->},{},{}){_,_->}
                }
            }
        }
    }

    private fun save(name:String){
        rule.waitForIdle()
        val view=rule.activity.window.decorView
        val bitmap=Bitmap.createBitmap(view.width,view.height,Bitmap.Config.ARGB_8888)
        view.draw(android.graphics.Canvas(bitmap))
        File(dir!!).apply{mkdirs()}.resolve("$name.png").outputStream().use{bitmap.compress(Bitmap.CompressFormat.PNG,100,it)}
    }

    @Test fun dayAt1401(){
        assumeTrue("Set SCREENSHOT_DIR to write screenshots",dir!=null)
        rule.setContent{Screen(now=14*60+1)}
        save("timeline-1401")
    }

    @Test fun draggingCheckEmails(){
        assumeTrue("Set SCREENSHOT_DIR to write screenshots",dir!=null)
        val entries=dayEntries(day)
        val drag=DragState(day[3],date,0,deltaY=40f*3f,pointerY=0f)
        rule.setContent{Screen(now=16*60+1,preview=dragPreviewOf(drag,0,3f,entries))}
        save("timeline-dragging")
    }
}
