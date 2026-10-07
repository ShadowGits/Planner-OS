package dev.planneros.android

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject
import java.time.LocalDate
import java.time.temporal.ChronoUnit

/* ── Status colours ─────────────────────────────────────────── */
private val StatusRed    = Color(0xFFCF4444)   // At risk / overdue
private val StatusAmber  = Color(0xFFD4912E)   // Behind schedule
private val StatusGreen  = Color(0xFF3A8E6A)   // On track
private val StatusTeal   = Color(0xFF2F6B64)   // Done
private val StatusGray   = Color(0xFF8896A4)   // No schedule / to-do

private val StatusRedBg    = Color(0x1ACF4444)
private val StatusAmberBg  = Color(0x1AD4912E)
private val StatusGreenBg  = Color(0x1A3A8E6A)

private fun statusColor(status: String): Color = when (status.lowercase()) {
    "red", "overdue" -> StatusRed
    "amber" -> StatusAmber
    "green", "on_track" -> StatusGreen
    "done", "complete", "completed" -> StatusTeal
    else -> StatusGray
}

private fun statusBgColor(status: String): Color = when (status.lowercase()) {
    "red", "overdue" -> StatusRedBg
    "amber" -> StatusAmberBg
    "green", "on_track" -> StatusGreenBg
    else -> Color.Transparent
}

@Composable
internal fun DayMilestonesView(
    milestones: List<JSONObject>,
    loading: Boolean,
    error: String?,
    modifier: Modifier = Modifier,
    onRefresh: () -> Unit = {},
    onMilestoneClick: (JSONObject) -> Unit = {}
) {
    var selectedProject by rememberSaveable { mutableStateOf("All") }
    var showCompleted by rememberSaveable { mutableStateOf(false) }
    var expandedId by rememberSaveable { mutableStateOf<String?>(null) }

    val total = milestones.size
    val done = milestones.count { recordDone(it) }
    val active = total - done
    val totalTasks = milestones.sumOf { it.optInt("total_tasks") }
    val doneTasks = milestones.sumOf { it.optInt("done_tasks") }
    val milestonePct = if (total > 0) (done * 100f / total) else 0f
    val taskPct = if (totalTasks > 0) (doneTasks * 100f / totalTasks) else 0f

    // Health counts
    val redCount = milestones.count { !recordDone(it) && it.optString("status") in listOf("red", "overdue") }
    val amberCount = milestones.count { !recordDone(it) && it.optString("status") == "amber" }
    val greenCount = milestones.count { !recordDone(it) && it.optString("status") == "green" }
    val otherActive = active - redCount - amberCount - greenCount

    val projects = remember(milestones) {
        listOf("All") + milestones.mapNotNull { it.nullString("project_name") }.distinct().sorted()
    }

    // Per-project breakdown
    val projectBreakdown = remember(milestones) {
        milestones.groupBy { it.optString("project_name", "General") }
            .map { (name, items) ->
                val pTotal = items.size
                val pDone = items.count { recordDone(it) }
                val pRed = items.count { !recordDone(it) && it.optString("status") in listOf("red", "overdue") }
                val pAmber = items.count { !recordDone(it) && it.optString("status") == "amber" }
                val pGreen = items.count { !recordDone(it) && it.optString("status") == "green" }
                val pTasks = items.sumOf { it.optInt("total_tasks") }
                val pDoneTasks = items.sumOf { it.optInt("done_tasks") }
                ProjectHealth(name, pTotal, pDone, pRed, pAmber, pGreen, pTasks, pDoneTasks)
            }
            .sortedByDescending { it.red + it.amber }
    }

    val activeMilestones = remember(milestones, selectedProject) {
        milestones.filter { !recordDone(it) && (selectedProject == "All" || it.optString("project_name") == selectedProject) }
            .sortedWith(compareBy<JSONObject> {
                when (it.optString("status").lowercase()) {
                    "red", "overdue" -> 0; "amber" -> 1; "green" -> 2; else -> 3
                }
            }.thenBy { it.nullString("target_date") ?: "9999-99-99" })
    }

    val completedMilestones = remember(milestones, selectedProject) {
        milestones.filter { recordDone(it) && (selectedProject == "All" || it.optString("project_name") == selectedProject) }
            .sortedByDescending { it.nullString("target_date") ?: "" }
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        // ── 1. HERO SUMMARY CARD ──
        item(key = "hero") {
            Surface(
                color = PlannerPalette.Navy,
                shape = RoundedCornerShape(22.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(Modifier.padding(20.dp)) {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("MILESTONES", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = PlannerPalette.Ice)
                        Icon(Icons.Rounded.Flag, null, tint = PlannerPalette.IceBlue, modifier = Modifier.size(22.dp))
                    }

                    Row(
                        Modifier.fillMaxWidth().padding(top = 14.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Column(Modifier.weight(1f)) {
                            Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text(active.toString(), fontSize = 40.sp, fontWeight = FontWeight.Bold, color = Color.White)
                                Text(
                                    if (active == 1) "active" else "active",
                                    fontSize = 14.sp, color = PlannerPalette.Ice,
                                    modifier = Modifier.padding(bottom = 8.dp)
                                )
                            }
                            Text(
                                "$done of $total complete · $doneTasks/$totalTasks tasks",
                                fontSize = 13.sp, color = PlannerPalette.Ice.copy(alpha = 0.9f),
                                modifier = Modifier.padding(top = 2.dp)
                            )
                        }
                        if (total > 0) {
                            StatusRing(milestonePct, if (milestonePct >= 75) StatusGreen else if (milestonePct >= 40) PlannerPalette.IceBlue else StatusAmber)
                        }
                    }

                    // Health breakdown bar
                    if (active > 0) {
                        Spacer(Modifier.height(16.dp))
                        HealthBar(red = redCount, amber = amberCount, green = greenCount, other = otherActive)
                        Spacer(Modifier.height(10.dp))
                        Row(
                            Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(16.dp)
                        ) {
                            HealthLegend(StatusRed, "At risk", redCount)
                            HealthLegend(StatusAmber, "Behind", amberCount)
                            HealthLegend(StatusGreen, "On track", greenCount)
                            if (otherActive > 0) HealthLegend(StatusGray, "Other", otherActive)
                        }
                    }
                }
            }
        }

        // Error
        if (error != null) {
            item(key = "error") {
                Surface(color = MaterialTheme.colorScheme.errorContainer, shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(Icons.Rounded.Warning, null, tint = MaterialTheme.colorScheme.error)
                        Text(error, fontSize = 12.sp, color = MaterialTheme.colorScheme.onErrorContainer, modifier = Modifier.weight(1f))
                        TextButton(onClick = onRefresh) { Text("Retry") }
                    }
                }
            }
        }

        // ── 2. PER-PROJECT HEALTH CARDS ──
        if (projectBreakdown.size > 1) {
            item(key = "project_health_header") {
                Text("Project Health", fontSize = 18.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 6.dp))
            }
            items(projectBreakdown, key = { "ph:${it.name}" }) { ph ->
                ProjectHealthCard(ph)
            }
        }

        // ── 3. PROJECT FILTER CHIPS ──
        if (projects.size > 2) {
            item(key = "project_filters") {
                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    projects.forEach { proj ->
                        val selected = proj == selectedProject
                        FilterChip(
                            selected = selected,
                            onClick = { selectedProject = proj },
                            label = { Text(proj, fontSize = 13.sp) },
                            leadingIcon = if (selected) {
                                { Icon(Icons.Rounded.Check, null, modifier = Modifier.size(16.dp)) }
                            } else null,
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = PlannerPalette.Wine,
                                selectedLabelColor = Color.White
                            )
                        )
                    }
                }
            }
        }

        // ── 4. ACTIVE MILESTONES ──
        item(key = "active_header") {
            Row(
                Modifier.fillMaxWidth().padding(top = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text("Active Milestones", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                Text("${activeMilestones.size} open", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }

        if (activeMilestones.isEmpty()) {
            item(key = "active_empty") {
                Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(Icons.Rounded.CheckCircleOutline, null, tint = StatusGreen, modifier = Modifier.size(36.dp))
                        Spacer(Modifier.height(8.dp))
                        Text("No active milestones", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                        Text(
                            if (total == 0) "Create milestones in your projects to track progress here."
                            else "All milestones are completed!",
                            fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp)
                        )
                    }
                }
            }
        } else {
            items(activeMilestones, key = { "active:${it.optString("id")}" }) { row ->
                ColoredMilestoneCard(
                    row = row,
                    expanded = expandedId == row.optString("id"),
                    onToggle = { expandedId = if (expandedId == row.optString("id")) null else row.optString("id") }
                )
            }
        }

        // ── 5. COMPLETED ACCORDION ──
        if (completedMilestones.isNotEmpty()) {
            item(key = "completed_accordion") {
                Surface(
                    onClick = { showCompleted = !showCompleted },
                    color = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.6f),
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp)
                ) {
                    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Rounded.TaskAlt, null, tint = StatusTeal, modifier = Modifier.size(20.dp))
                        Text(
                            "Completed · ${completedMilestones.size}",
                            fontSize = 14.sp, fontWeight = FontWeight.Medium,
                            color = MaterialTheme.colorScheme.onSecondaryContainer,
                            modifier = Modifier.weight(1f).padding(start = 10.dp)
                        )
                        Icon(
                            if (showCompleted) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore,
                            contentDescription = if (showCompleted) "Collapse" else "Expand",
                            tint = MaterialTheme.colorScheme.onSecondaryContainer
                        )
                    }
                }
            }

            if (showCompleted) {
                items(completedMilestones, key = { "completed:${it.optString("id")}" }) { row ->
                    ColoredMilestoneCard(row = row, completed = true, expanded = false, onToggle = {})
                }
            }
        }
    }
}

/* ── Health breakdown bar ─────────────────────────────── */
@Composable
private fun HealthBar(red: Int, amber: Int, green: Int, other: Int) {
    val total = (red + amber + green + other).coerceAtLeast(1).toFloat()
    Row(
        Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp))
    ) {
        if (red > 0) Box(Modifier.weight(red / total).fillMaxHeight().background(StatusRed))
        if (amber > 0) Box(Modifier.weight(amber / total).fillMaxHeight().background(StatusAmber))
        if (green > 0) Box(Modifier.weight(green / total).fillMaxHeight().background(StatusGreen))
        if (other > 0) Box(Modifier.weight(other / total).fillMaxHeight().background(StatusGray))
    }
}

@Composable
private fun HealthLegend(color: Color, label: String, count: Int) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(color))
        Text("$count $label", fontSize = 11.sp, color = PlannerPalette.Ice.copy(alpha = 0.85f))
    }
}

/* ── Status-colored progress ring ──────────────────── */
@Composable
private fun StatusRing(percent: Float, ringColor: Color, modifier: Modifier = Modifier) {
    val value = percent.coerceIn(0f, 100f)
    Box(modifier.size(64.dp), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize().padding(4.dp)) {
            val stroke = Stroke(5.dp.toPx(), cap = StrokeCap.Round)
            drawArc(Color.White.copy(alpha = 0.15f), -90f, 360f, false, style = stroke)
            if (value > 0) drawArc(ringColor, -90f, 360f * value / 100f, false, style = stroke)
        }
        Text(value.toInt().toString() + "%", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = Color.White)
    }
}

/* ── Per-project health card ──────────────────────── */
private data class ProjectHealth(
    val name: String, val total: Int, val done: Int,
    val red: Int, val amber: Int, val green: Int,
    val totalTasks: Int, val doneTasks: Int
)

@Composable
private fun ProjectHealthCard(ph: ProjectHealth) {
    val pct = if (ph.total > 0) (ph.done * 100f / ph.total) else 0f
    val taskPct = if (ph.totalTasks > 0) (ph.doneTasks * 100f / ph.totalTasks) else 0f
    val dominant = when {
        ph.red > 0 -> StatusRed; ph.amber > 0 -> StatusAmber; ph.green > 0 -> StatusGreen; else -> StatusTeal
    }
    Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth()) {
            // Color edge strip
            Box(Modifier.width(5.dp).fillMaxHeight().clip(RoundedCornerShape(topStart = 16.dp, bottomStart = 16.dp)).background(dominant))
            Column(Modifier.weight(1f).padding(14.dp)) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(Icons.Rounded.FolderOpen, null, tint = dominant, modifier = Modifier.size(18.dp))
                        Text(ph.name, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Text("${ph.done}/${ph.total}", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Spacer(Modifier.height(8.dp))
                // Mini health bar
                Row(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp))) {
                    val activeTotal = (ph.total - ph.done).coerceAtLeast(1).toFloat()
                    if (ph.red > 0) Box(Modifier.weight(ph.red / activeTotal).fillMaxHeight().background(StatusRed))
                    if (ph.amber > 0) Box(Modifier.weight(ph.amber / activeTotal).fillMaxHeight().background(StatusAmber))
                    if (ph.green > 0) Box(Modifier.weight(ph.green / activeTotal).fillMaxHeight().background(StatusGreen))
                    val other = (ph.total - ph.done - ph.red - ph.amber - ph.green).coerceAtLeast(0)
                    if (other > 0) Box(Modifier.weight(other / activeTotal).fillMaxHeight().background(StatusGray))
                    if (ph.done > 0 && ph.total > 0) Box(Modifier.weight(ph.done.toFloat() / ph.total).fillMaxHeight().background(StatusTeal.copy(alpha = 0.5f)))
                }
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (ph.red > 0) StatusChip("${ph.red} at risk", StatusRed)
                    if (ph.amber > 0) StatusChip("${ph.amber} behind", StatusAmber)
                    if (ph.green > 0) StatusChip("${ph.green} on track", StatusGreen)
                }
                if (ph.totalTasks > 0) {
                    Text(
                        "${ph.doneTasks} of ${ph.totalTasks} tasks done",
                        fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp)
                    )
                }
            }
        }
    }
}

@Composable
private fun StatusChip(text: String, color: Color) {
    Surface(color = color.copy(alpha = 0.15f), shape = RoundedCornerShape(6.dp)) {
        Text(text, fontSize = 11.sp, fontWeight = FontWeight.Medium, color = color, modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp))
    }
}

/* ── Color-coded milestone card ─────────────────────── */
@Composable
private fun ColoredMilestoneCard(
    row: JSONObject,
    completed: Boolean = false,
    expanded: Boolean = false,
    onToggle: () -> Unit = {}
) {
    val totalTasks = row.optInt("total_tasks")
    val doneTasks = row.optInt("done_tasks")
    val taskPct = if (totalTasks > 0) (doneTasks * 100f / totalTasks) else 0f
    val status = row.optString("status", if (completed) "done" else "todo")
    val projectName = row.optString("project_name", "General")
    val targetDateStr = row.nullString("target_date")
    val color = statusColor(status)
    val bgTint = statusBgColor(status)

    val daysText = remember(targetDateStr) {
        targetDateStr?.let {
            runCatching {
                val target = LocalDate.parse(it)
                val days = ChronoUnit.DAYS.between(LocalDate.now(), target)
                when {
                    days < 0 -> "${-days}d overdue"
                    days == 0L -> "Due today"
                    days == 1L -> "Due tomorrow"
                    days <= 7L -> "${days}d left"
                    else -> "${days}d left"
                }
            }.getOrNull()
        }
    }

    Surface(
        onClick = onToggle,
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().alpha(if (completed) 0.65f else 1f)
    ) {
        Row(Modifier.fillMaxWidth()) {
            // ── Color status strip on left edge ──
            Box(
                Modifier
                    .width(5.dp)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(topStart = 16.dp, bottomStart = 16.dp))
                    .background(color)
            )
            Column(Modifier.weight(1f).padding(14.dp)) {
                // Top row: project + status badge
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        modifier = Modifier.weight(1f, fill = false)
                    ) {
                        Icon(Icons.Rounded.FolderOpen, null, tint = color, modifier = Modifier.size(15.dp))
                        Text(projectName, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = color, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    // Status badge with color
                    Surface(color = color.copy(alpha = 0.15f), shape = RoundedCornerShape(8.dp)) {
                        Text(
                            humanStatus(status),
                            fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = color,
                            modifier = Modifier.padding(horizontal = 9.dp, vertical = 5.dp)
                        )
                    }
                }

                Spacer(Modifier.height(10.dp))

                // Body: Deadline + Title + Progress
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    if (!targetDateStr.isNullOrBlank()) {
                        DeadlineStamp(targetDateStr)
                    } else {
                        Surface(
                            color = MaterialTheme.colorScheme.secondaryContainer,
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.size(46.dp)
                        ) {
                            Box(contentAlignment = Alignment.Center) {
                                Icon(Icons.Rounded.Flag, null, tint = color, modifier = Modifier.size(22.dp))
                            }
                        }
                    }

                    Column(Modifier.weight(1f)) {
                        Text(
                            rowTitle(row),
                            fontSize = 16.sp,
                            fontWeight = FontWeight.SemiBold,
                            textDecoration = if (completed) TextDecoration.LineThrough else null,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis
                        )

                        val metaList = listOfNotNull(
                            friendlyDate(targetDateStr).takeIf { it.isNotBlank() },
                            daysText
                        )
                        if (metaList.isNotEmpty()) {
                            Text(
                                metaList.joinToString(" · "),
                                fontSize = 12.sp,
                                color = if (status in listOf("red", "overdue")) StatusRed else MaterialTheme.colorScheme.onSurfaceVariant,
                                fontWeight = if (status in listOf("red", "overdue", "amber")) FontWeight.Medium else FontWeight.Normal,
                                modifier = Modifier.padding(top = 3.dp)
                            )
                        }

                        if (totalTasks > 0 && !completed) {
                            Spacer(Modifier.height(6.dp))
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                LinearProgressIndicator(
                                    progress = { (taskPct / 100f).coerceIn(0f, 1f) },
                                    modifier = Modifier.weight(1f).height(4.dp),
                                    color = color,
                                    trackColor = color.copy(alpha = 0.15f)
                                )
                                Text(
                                    "$doneTasks/$totalTasks",
                                    fontSize = 11.sp, fontWeight = FontWeight.Medium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                    }

                    if (totalTasks > 0 && !completed) {
                        // Color-coded mini ring
                        MiniStatusRing(taskPct, color)
                    }
                }

                // Expanded details
                AnimatedVisibility(visible = expanded, enter = expandVertically(), exit = shrinkVertically()) {
                    Column(Modifier.padding(top = 12.dp)) {
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f))
                        Spacer(Modifier.height(10.dp))
                        DetailRow("Status", humanStatus(status), color)
                        DetailRow("Project", projectName)
                        if (!targetDateStr.isNullOrBlank()) DetailRow("Deadline", friendlyDate(targetDateStr))
                        if (daysText != null) DetailRow("Time left", daysText, if (status in listOf("red", "overdue")) StatusRed else null)
                        if (totalTasks > 0) DetailRow("Tasks", "$doneTasks of $totalTasks complete (${taskPct.toInt()}%)")
                        row.nullString("description")?.takeIf { it.isNotBlank() }?.let {
                            Spacer(Modifier.height(6.dp))
                            Text(it, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, lineHeight = 18.sp)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DetailRow(label: String, value: String, valueColor: Color? = null) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 3.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(label, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(
            value, fontSize = 12.sp, fontWeight = FontWeight.Medium,
            color = valueColor ?: MaterialTheme.colorScheme.onSurface
        )
    }
}

@Composable
private fun MiniStatusRing(percent: Float, ringColor: Color) {
    val value = percent.coerceIn(0f, 100f)
    Box(Modifier.size(44.dp), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize().padding(3.dp)) {
            val stroke = Stroke(4.dp.toPx(), cap = StrokeCap.Round)
            drawArc(ringColor.copy(alpha = 0.15f), -90f, 360f, false, style = stroke)
            if (value > 0) drawArc(ringColor, -90f, 360f * value / 100f, false, style = stroke)
        }
        Text(value.toInt().toString() + "%", fontSize = 11.sp, fontWeight = FontWeight.Bold, color = ringColor)
    }
}
