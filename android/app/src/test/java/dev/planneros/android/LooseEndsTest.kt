package dev.planneros.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * The day's loose ends: what "Fit my day" finds a time for.
 *
 * The same cases as the iPhone's looseEnds checks in apple/PolicyTests and the
 * same rule the server applies, so the count on the button matches what comes
 * back whichever app is in your hand.
 */
// Robolectric, because reading the server's JSON needs Android's real parser.
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35])
class LooseEndsTest {
    private fun task(id: String, time: String? = null, minutes: Int = 30, done: Boolean = false, habit: Boolean = false) =
        Task(id, id, time, minutes, done, false, habit, null, "2026-05-13", null, null)

    private val day = listOf(
        task("untimed"),
        task("missed", time = "09:00", minutes = 30),
        task("underway", time = "12:00", minutes = 120),
        task("later", time = "19:00"),
        task("ticked", time = "08:00", done = true),
        task("habit", habit = true),
    )

    @Test fun `takes what has no time and what has slipped`() {
        assertEquals(listOf("untimed", "missed"), looseEnds(day, 13 * 60).map { it.id })
    }

    @Test fun `another day has no clock so only the untimed count`() {
        assertEquals(listOf("untimed"), looseEnds(day, null).map { it.id })
    }

    @Test fun `a slot still running has not slipped`() {
        assertEquals(listOf("untimed"), looseEnds(day, 9 * 60 + 15).map { it.id })
    }

    @Test fun `a habit is a standing commitment, not a loose end`() {
        assertTrue(looseEnds(listOf(task("habit", habit = true)), 13 * 60).isEmpty())
    }

    @Test fun `a finished task is not a loose end`() {
        assertTrue(looseEnds(listOf(task("ticked", time = "08:00", done = true)), 13 * 60).isEmpty())
    }

    @Test fun `a calendar event is an appointment, timed or not`() {
        val festival = task("festival").copy(source = "apple_calendar")
        val danceClass = task("class", time = "09:00").copy(source = "apple_calendar")
        assertEquals(listOf("own"), looseEnds(listOf(festival, danceClass, task("own")), 13 * 60).map { it.id })
    }

    @Test fun `the day view says where an item came from`() {
        val event = Task.from(org.json.JSONObject("""{"id":"e1","title":"Dance","source":"apple_calendar"}"""))
        assertTrue(event.fromCalendar)
        assertTrue(!Task.from(org.json.JSONObject("""{"id":"t1","title":"Own"}""")).fromCalendar)
    }

    @Test fun `an empty day has no loose ends`() {
        assertTrue(looseEnds(emptyList(), 13 * 60).isEmpty())
    }
}
