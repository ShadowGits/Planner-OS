package dev.planneros.android

import java.time.LocalDate
import java.time.ZonedDateTime
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.roundToInt

const val TIMELINE_DP_PER_MINUTE = 2f
/** Every visible time edge uses the same scale, including short task blocks. */
fun timelineOffsetDp(minute:Int,startMinute:Int):Float=(minute-startMinute)*TIMELINE_DP_PER_MINUTE
fun timelineDurationDp(minutes:Int):Float=minutes.coerceAtLeast(1)*TIMELINE_DP_PER_MINUTE
const val DRAG_SNAP_MINUTES = 5
const val LOGICAL_DAY_CUTOFF = 4 * 60

data class ScheduleSlot(val date: LocalDate, val clockMinute: Int) {
    val clock: String get() = "%02d:%02d".format(clockMinute / 60, clockMinute % 60)
}
data class TimeBlock(val id: String, val start: Int, val duration: Int) { val end: Int get() = start + duration.coerceAtLeast(1) }
data class Lane(val column: Int, val columns: Int)
data class TimelineBounds(val start: Int, val end: Int)

fun logicalToday(now: ZonedDateTime): LocalDate = now.toLocalDate().let { if (now.hour < 4) it.minusDays(1) else it }
fun logicalNowMinute(now: ZonedDateTime): Int = now.hour * 60 + now.minute + if (now.hour < 4) 1440 else 0
fun durationLabel(minutes: Int): String = when {
    minutes >= 60 && minutes % 60 != 0 -> "${minutes / 60}h ${minutes % 60}m"
    minutes >= 60 -> "${minutes / 60}h"
    else -> "${minutes}m"
}
fun displayClock(minute: Int, twelveHour: Boolean = false): String {
    val clock = Math.floorMod(minute, 1440)
    val h = clock / 60
    return if (twelveHour) "%d:%02d %s".format(if (h % 12 == 0) 12 else h % 12, clock % 60, if (h < 12) "AM" else "PM")
    else "%02d:%02d".format(h, clock % 60)
}
fun normalizeSlot(viewDate: LocalDate, minute: Int): ScheduleSlot = ScheduleSlot(
    viewDate.plusDays(Math.floorDiv(minute, 1440).toLong()), Math.floorMod(minute, 1440))

/** Coordinates map to real minutes, irrespective of the rendered title/card height. */
fun dragSlot(viewDate: LocalDate, startMinute: Int, deltaDp: Float, horizontalDay: Int = 0, minimum: Int = 0, maximum: Int = 1675): ScheduleSlot {
    val snapped = ((startMinute + deltaDp / TIMELINE_DP_PER_MINUTE) / DRAG_SNAP_MINUTES).roundToInt() * DRAG_SNAP_MINUTES
    return normalizeSlot(viewDate.plusDays(horizontalDay.toLong()), snapped.coerceIn(minimum, maximum.coerceAtLeast(minimum)))
}
fun visibleMinute(viewDate: LocalDate, slot: ScheduleSlot): Int? = when {
    slot.date == viewDate -> slot.clockMinute
    slot.date == viewDate.plusDays(1) && slot.clockMinute < LOGICAL_DAY_CUTOFF -> slot.clockMinute + 1440
    else -> null
}
fun timelineBounds(blocks: List<TimeBlock>): TimelineBounds = if (blocks.isEmpty()) TimelineBounds(8 * 60, 18 * 60) else
    TimelineBounds((floor(blocks.minOf { it.start } / 60.0).toInt() - 1).coerceAtLeast(0) * 60,
        (ceil(blocks.maxOf { it.end } / 60.0).toInt() + 1) * 60)

/** Half-open intervals. A transitive overlap group uses its widest concurrency. */
fun overlapLanes(blocks: List<TimeBlock>): Map<String, Lane> {
    val result = mutableMapOf<String, Lane>()
    val ordered = blocks.sortedWith(compareBy<TimeBlock> { it.start }.thenBy { it.id })
    var group = mutableListOf<Pair<TimeBlock, Int>>()
    var laneEnds = mutableListOf<Int>()
    var groupEnd = Int.MIN_VALUE
    fun flush() {
        val width = laneEnds.size.coerceAtLeast(1)
        group.forEach { (block, column) -> result[block.id] = Lane(column, width) }
        group = mutableListOf(); laneEnds = mutableListOf(); groupEnd = Int.MIN_VALUE
    }
    for (block in ordered) {
        if (group.isNotEmpty() && block.start >= groupEnd) flush()
        var column = laneEnds.indexOfFirst { it <= block.start }
        if (column == -1) { column = laneEnds.size; laneEnds.add(block.end) } else laneEnds[column] = block.end
        group.add(block to column); groupEnd = maxOf(groupEnd, block.end)
    }
    if (group.isNotEmpty()) flush()
    return result
}
fun nextFreeSlot(viewDate: LocalDate, today: LocalDate, nowMinute: Int, duration: Int, blocks: List<TimeBlock>): ScheduleSlot {
    var candidate = if (viewDate == today) ceil(nowMinute / 30.0).toInt() * 30 else 9 * 60
    for (block in blocks.sortedBy { it.start }) {
        if (candidate + duration <= block.start) break
        if (candidate < block.end) candidate = block.end
    }
    return normalizeSlot(viewDate, candidate)
}
fun canToggleStar(currentlyStarred: Boolean, selectedCount: Int, limit: Int): Boolean = currentlyStarred || selectedCount < limit
fun rollbackForDate(snapshot: Day, current: Day?): Day? = if (current?.date == snapshot.date) snapshot else current
fun replaceTask(day: Day, task: Task): Day = day.copy(tasks = day.tasks.map { if (it.id == task.id) task else it })

private val categoryEmojiRules = listOf(
    "german|deutsch|\\ba1\\b|\\ba2\\b|duolingo|babbel" to "🇩🇪",
    "gym|workout|lift|train|exercise|brahmri|yoga" to "🏋️",
    "run|jog|walk" to "🏃", "math|calc|algebra|geometry|applied" to "📐",
    "read|book" to "📖", "study|learn|course|revise" to "📚",
    "call|phone|hr\\b" to "📞", "mail|email|reply" to "✉️",
    "visa|embassy|passport|apostille|aps" to "🛂",
    "college|uni|apply|application|sop|lor|shortlist" to "🎓",
    "plan|schedule|organi[sz]e" to "🗓️", "doc|form|paper|print|transcript|cv" to "📄",
    "bank|money|finance|pay|invest|tax|fund|blocked account" to "💰",
    "food|cook|meal|lunch|dinner|breakfast" to "🍳", "clean|laundry|tidy" to "🧹",
    "meet|sync|standup|interview" to "👥", "code|build|deploy|bug|dev" to "💻",
    "write|journal|blog|note" to "✍️", "piano|music|guitar" to "🎹",
    "ielts|toefl|test|exam|mock" to "📝", "wind down|skin|sleep|rest|nap|night" to "🌙"
).map { (pattern, emoji) -> Regex(pattern,RegexOption.IGNORE_CASE) to emoji }
fun taskEmoji(title: String): String = categoryEmojiRules.firstOrNull { it.first.containsMatchIn(title) }?.second ?: "✨"
