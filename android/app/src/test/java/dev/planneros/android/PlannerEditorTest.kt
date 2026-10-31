package dev.planneros.android

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.LocalDate

/** Typing a new name into the editor, for a task and for a habit, and saving it. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35],qualifiers="w393dp-h852dp-xxhdpi")
class PlannerEditorTest {
    @get:Rule val rule=createComposeRule()
    private val date=LocalDate.parse("2026-05-13")

    private fun renames(task:Task){
        var saved:String?=null
        rule.setContent{
            MaterialTheme{
                PlannerEditor(task,date,null,null,false,null,emptyList(),emptyMap(),emptyList(),null,{},{},
                    {title,_,_,_,_,_,_->saved=title},{},{},{},{},{})
            }
        }
        // A read-only field (as a habit's name was) offers no typing at all and is not editable.
        val field=rule.onNode(hasText(task.title)and hasSetTextAction())
        field.assert(SemanticsMatcher.expectValue(androidx.compose.ui.semantics.SemanticsProperties.IsEditable,true))
        field.performSemanticsAction(androidx.compose.ui.semantics.SemanticsActions.RequestFocus)
        field.assertIsFocused()
        field.performTextReplacement("${task.title} renamed")
        rule.onNode(hasText("${task.title} renamed")and hasSetTextAction()).assertExists()
        // The half-open sheet keeps Save below the fold, so it is pressed through its click action.
        rule.onNodeWithText("Save").performSemanticsAction(androidx.compose.ui.semantics.SemanticsActions.OnClick)
        rule.waitForIdle()
        assertEquals("${task.title} renamed",saved)
    }

    @Test fun aTaskCanBeRenamed()=renames(Task("t1","Draft SOP","10:00",30,false,false,false,null,date.toString(),null,null))

    @Test fun aHabitCanBeRenamed()=renames(Task("habit:gym:2026-05-13","Gym","17:30",90,false,false,true,null,date.toString(),null,null))
}
