package dev.planneros.android

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject
import java.text.NumberFormat
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.abs

/** Finance uses cash amounts, a category comparison and a dated cash-flow chart. */
@Composable internal fun FinanceSummary(data: JSONObject) {
    val currencies = data.optJSONObject("currencies") ?: JSONObject()
    val codes = currencies.keys().asSequence().toList().sorted()
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 28.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        item {
            Text("${data.optInt("transaction_count")} recorded transactions", fontSize = 15.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (codes.isEmpty()) item {
            MoneyEmpty("No transactions this month", "Your funding plan and earlier transactions have their own tabs.")
        }
        codes.forEach { code ->
            val values = currencies.optJSONObject(code) ?: JSONObject()
            val net = values.moneyNumber("net")
            item {
                MoneyHero(
                    title = if (net < 0) "Spending exceeds income" else "Left after spending",
                    amount = abs(net), currency = code,
                    detail = if (net < 0) "This is the gap between recorded income and spending." else "Recorded income minus spending this month.",
                    icon = Icons.Rounded.AccountBalanceWallet,
                    fill = if (net < 0) PlannerPalette.Wine else PlannerPalette.Navy
                )
            }
            item {
                MoneyPair(
                    first = { MoneyMetric("Income", values.moneyNumber("income"), code, Icons.Rounded.SouthWest, MaterialTheme.colorScheme.tertiary) },
                    second = { MoneyMetric("Spending", values.moneyNumber("expense"), code, Icons.Rounded.NorthEast, MaterialTheme.colorScheme.primary) }
                )
            }
            if (values.has("change_pct") && !values.isNull("change_pct")) item {
                val change = values.moneyNumber("change_pct")
                val previous = values.moneyNumber("previous_expense")
                val down = change < 0
                Row(Modifier.fillMaxWidth().padding(horizontal = 2.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.Top) {
                    Icon(if (down) Icons.Rounded.TrendingDown else Icons.Rounded.TrendingUp, null,
                        tint = if (down) MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(24.dp))
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text(if (abs(change) < 0.05) "Spending matches last month" else "Spending ${moneyPercent(abs(change))}% ${if (down) "lower" else "higher"}",
                            fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
                        Text("Last month: ${moneyAmount(previous, code)}", fontSize = 15.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            val categories = values.moneyObjects("by_category")
            if (categories.isNotEmpty()) {
                item { MoneySectionTitle(Icons.Rounded.PieChart, "Where it went", "Share of spending · $code") }
                itemsIndexed(categories) { _, category -> MoneyCategory(category, code) }
            }
            if (codes.size > 1) item { HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant) }
        }
    }
}

@Composable internal fun FundingPlan(data: JSONObject, onRecord: (JSONObject) -> Unit) {
    val plan = data.optJSONObject("plan")
    if (plan == null) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp)) {
            item { MoneyEmpty("No funding plan yet", "Your transactions and saving goals remain available.") }
        }
        return
    }
    val totals = data.optJSONObject("totals") ?: JSONObject()
    val code = totals.moneyText("base_currency") ?: plan.moneyText("base_currency") ?: "INR"
    val gap = totals.moneyNumber("gap")
    val loan = totals.moneyNumber("loan_needed")
    val shortfall = gap < -0.01
    val timingGap = !shortfall && loan > 0.01
    val timeline = data.optJSONObject("timeline") ?: JSONObject()
    val costs = data.moneyObjects("costs")
    val funds = data.moneyObjects("funds")
    var ledger by rememberSaveable(plan.moneyText("id") ?: "plan") { mutableStateOf("costs") }
    val rows = if (ledger == "costs") costs else funds
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 28.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        item { MoneySectionTitle(Icons.Rounded.AccountBalance, plan.moneyText("name") ?: "Funding plan", "Expected funding and remaining costs · $code") }
        item {
            MoneyHero(
                title = when { shortfall -> "Funding shortfall"; timingGap -> "Timing gap"; else -> "Covered" },
                amount = when { shortfall -> abs(gap); timingGap -> loan; else -> gap.coerceAtLeast(0.0) },
                currency = code,
                detail = when {
                    shortfall -> "More funding is needed to cover the remaining costs."
                    timingGap -> "There is enough funding overall, but some arrives after payments are due."
                    else -> "Expected funding covers remaining costs. This amount is left over."
                },
                icon = when { shortfall -> Icons.Rounded.PriorityHigh; timingGap -> Icons.Rounded.Schedule; else -> Icons.Rounded.Verified },
                fill = when { shortfall -> PlannerPalette.Wine; timingGap -> PlannerPalette.Amber; else -> PlannerPalette.Navy }
            )
        }
        item {
            MoneyPair(
                first = { MoneyMetric("Available to fund", totals.moneyNumber("fund_available"), code, Icons.Rounded.SouthWest, MaterialTheme.colorScheme.tertiary) },
                second = { MoneyMetric("Costs still to pay", totals.moneyNumber("cost_outstanding"), code, Icons.Rounded.NorthEast, MaterialTheme.colorScheme.primary) }
            )
        }
        val unconfirmed = funds.count { it.moneyText("certainty") != "confirmed" }
        if (unconfirmed > 0) item {
            MoneyNotice(Icons.Rounded.Info, "Includes $unconfirmed unconfirmed funding ${if (unconfirmed == 1) "source" else "sources"}.")
        }
        val unconverted = totals.optJSONArray("unconvertible_currencies")
        if (unconverted != null && unconverted.length() > 0) item {
            val names = (0 until unconverted.length()).map { unconverted.optString(it) }.joinToString(", ")
            MoneyNotice(Icons.Rounded.WarningAmber, "Amounts in $names need a conversion rate. Coverage may be incomplete.")
        }
        item { MoneySectionTitle(Icons.Rounded.BarChart, "When money is needed", "Expected inflows and payments, month by month") }
        item { MoneyCashFlow(timeline, code) }
        val undated = timeline.moneyObjects("undated_costs")
        if (undated.isNotEmpty()) item {
            MoneyNotice(Icons.Rounded.EventBusy, "${undated.size} ${if (undated.size == 1) "cost has" else "costs have"} no date. The timing estimate excludes ${if (undated.size == 1) "it" else "them"}.")
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                MoneySectionTitle(Icons.Rounded.ReceiptLong, "Plan ledger", "Tap a line for its details")
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    FilterChip(selected = ledger == "costs", onClick = { ledger = "costs" }, label = { Text("Costs · ${costs.size}", fontSize = 16.sp) }, leadingIcon = { Icon(Icons.Rounded.NorthEast, null, Modifier.size(18.dp)) })
                    FilterChip(selected = ledger == "funds", onClick = { ledger = "funds" }, label = { Text("Funds · ${funds.size}", fontSize = 16.sp) }, leadingIcon = { Icon(Icons.Rounded.SouthWest, null, Modifier.size(18.dp)) })
                }
            }
        }
        if (rows.isEmpty()) item { MoneyEmpty(if (ledger == "costs") "No cost lines" else "No funding sources", "This part of the plan is empty.") }
        itemsIndexed(rows) { _, row -> MoneyPlanRow(row, code, ledger == "costs") { onRecord(row) } }
    }
}

@Composable private fun MoneyHero(title: String, amount: Double, currency: String, detail: String, icon: ImageVector, fill: Color) {
    Surface(color = fill, contentColor = Color.White, shape = RoundedCornerShape(22.dp)) {
        Column(Modifier.fillMaxWidth().padding(22.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.Top) {
                Icon(icon, null, Modifier.size(27.dp))
                Text(title, Modifier.weight(1f), fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
            }
            Text(currency, fontSize = 15.sp, fontWeight = FontWeight.Medium, color = PlannerPalette.Ice)
            val formatted = moneyNumberText(amount)
            Text(formatted, fontSize = if (formatted.length > 13) 28.sp else 36.sp, lineHeight = 42.sp, fontWeight = FontWeight.Bold)
            Text(detail, fontSize = 16.sp, lineHeight = 23.sp, color = Color.White)
        }
    }
}

@Composable private fun MoneyMetric(label: String, amount: Double, currency: String, icon: ImageVector, tint: Color) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
            Icon(icon, null, Modifier.size(22.dp), tint = tint)
            Text(label, Modifier.weight(1f), fontSize = 16.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Text(currency, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(moneyNumberText(amount), fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onSurface)
    }
}

@Composable private fun MoneyPair(first: @Composable () -> Unit, second: @Composable () -> Unit) {
    val fontScale = LocalDensity.current.fontScale
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        if (maxWidth < 330.dp || fontScale > 1.15f) {
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                first()
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                second()
            }
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                Box(Modifier.weight(1f)) { first() }
                Box(Modifier.weight(1f)) { second() }
            }
        }
    }
}

@Composable private fun MoneySectionTitle(icon: ImageVector, title: String, subtitle: String) {
    Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.Top) {
        Icon(icon, null, Modifier.size(25.dp), tint = MaterialTheme.colorScheme.secondary)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text(title, fontSize = 22.sp, lineHeight = 28.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onSurface)
            Text(subtitle, fontSize = 15.sp, lineHeight = 22.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable private fun MoneyCategory(row: JSONObject, currency: String) {
    val name = row.moneyText("category") ?: "Uncategorised"
    val amount = row.moneyNumber("amount")
    val share = row.moneyNumber("share_pct").coerceIn(0.0, 100.0)
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.Top) {
            Icon(moneyCategoryIcon(name), null, Modifier.size(23.dp), tint = MaterialTheme.colorScheme.secondary)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(name.replaceFirstChar { it.titlecase() }, fontSize = 18.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
                Text("${moneyAmount(amount, currency)} · ${moneyPercent(share)}%", fontSize = 18.sp, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface)
            }
        }
        LinearProgressIndicator(progress = { (share / 100.0).toFloat() }, modifier = Modifier.fillMaxWidth().height(7.dp),
            color = MaterialTheme.colorScheme.secondary, trackColor = MaterialTheme.colorScheme.surfaceVariant)
    }
}

@Composable private fun MoneyCashFlow(timeline: JSONObject, currency: String) {
    val months = timeline.moneyObjects("months")
    val incoming = MaterialTheme.colorScheme.tertiary
    val outgoing = MaterialTheme.colorScheme.primary
    Surface(color = MaterialTheme.colorScheme.surfaceContainerLow, shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("Starting balance", fontSize = 16.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(moneyAmount(timeline.moneyNumber("opening_balance"), currency), fontSize = 24.sp, fontWeight = FontWeight.Bold)
            if (months.isEmpty()) {
                Text("No dated cash flows yet", fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
            } else {
                MoneyPair(
                    first = { MoneyLegend("Money in", incoming, Icons.Rounded.SouthWest) },
                    second = { MoneyLegend("Payments out", outgoing, Icons.Rounded.NorthEast) }
                )
                val maxFlow = months.maxOf { maxOf(it.moneyNumber("in"), it.moneyNumber("out")) }.coerceAtLeast(1.0)
                val fontScale = LocalDensity.current.fontScale
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                    months.forEach { month ->
                        val inAmount = month.moneyNumber("in")
                        val outAmount = month.moneyNumber("out")
                        val balance = month.moneyNumber("balance")
                        val label = moneyMonth(month.moneyText("month") ?: "")
                        Column(Modifier.width(if (fontScale > 1.15f) 152.dp else 130.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                            Row(Modifier.fillMaxWidth().height(116.dp).semantics {
                                contentDescription = "$label: money in ${moneyAmount(inAmount, currency)}, payments out ${moneyAmount(outAmount, currency)}"
                            }, horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.Bottom) {
                                MoneyChartBar(inAmount / maxFlow, incoming)
                                Spacer(Modifier.width(10.dp))
                                MoneyChartBar(outAmount / maxFlow, outgoing)
                            }
                            Text(label, fontSize = 17.sp, fontWeight = FontWeight.Bold)
                            Text("In ${moneyAmount(inAmount, currency)}", fontSize = 15.sp, color = MaterialTheme.colorScheme.onSurface)
                            Text("Out ${moneyAmount(outAmount, currency)}", fontSize = 15.sp, color = MaterialTheme.colorScheme.onSurface)
                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                            Text(if (balance < 0) "Shortfall" else "Balance", fontSize = 15.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(moneyAmount(balance, currency), fontSize = 18.sp, fontWeight = FontWeight.Bold,
                                color = if (balance < 0) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface)
                        }
                    }
                }
                if (months.size > 1) Text("Swipe for later months →", fontSize = 15.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            val loanBy = timeline.moneyText("loan_by_month")
            if (loanBy != null) MoneyNotice(Icons.Rounded.Schedule, "First funding gap: ${moneyMonth(loanBy)}")
        }
    }
}

@Composable private fun MoneyChartBar(fraction: Double, color: Color) {
    Box(Modifier.width(28.dp).height((fraction.coerceIn(0.0, 1.0) * 110).dp)
        .background(color, RoundedCornerShape(topStart = 5.dp, topEnd = 5.dp)))
}

@Composable private fun MoneyLegend(label: String, color: Color, icon: ImageVector) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
        Icon(icon, null, Modifier.size(20.dp), tint = color)
        Text(label, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
    }
}

@Composable private fun MoneyPlanRow(row: JSONObject, currency: String, isCost: Boolean, onClick: () -> Unit) {
    val outstanding = row.moneyNumber("outstanding")
    val settled = row.moneyNumber("settled")
    val estimate = row.moneyNumber("estimate")
    val date = row.moneyText("due_date")
    val certainty = row.moneyText("certainty") ?: "likely"
    val fullySettled = outstanding <= 0.01
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.Top) {
            Icon(if (fullySettled) Icons.Rounded.CheckCircle else if (isCost) Icons.Rounded.NorthEast else Icons.Rounded.SouthWest,
                null, Modifier.size(25.dp), tint = if (fullySettled) MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.secondary)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(row.moneyText("label") ?: "Plan item", fontSize = 19.sp, lineHeight = 26.sp, fontWeight = FontWeight.SemiBold)
                Text("${moneyAmount(outstanding, currency)} ${if (isCost) "left to pay" else "still expected"}", fontSize = 19.sp, lineHeight = 26.sp, fontWeight = FontWeight.Bold)
                Text("${if (isCost) "Paid" else "Received"} ${moneyAmount(settled, currency)} · Total ${moneyAmount(estimate, currency)}", fontSize = 15.sp, lineHeight = 22.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                val perCode = row.moneyText("currency") ?: currency
                val instalments = row.optInt("instalments", 1).coerceAtLeast(1)
                if (instalments > 1 || perCode != currency) {
                    Text("${moneyAmount(row.moneyNumber("amount"), perCode)} × $instalments ${if (instalments == 1) "payment" else "payments"}", fontSize = 15.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Text(if (date != null) "${if (isCost) "Due" else "Expected"} ${moneyDate(date)}" else if (isCost) "No date set" else "Available without a date", fontSize = 15.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (!isCost) {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.Top) {
                        Icon(if (certainty == "confirmed") Icons.Rounded.Verified else Icons.Rounded.Info, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.tertiary)
                        Text(certainty.replaceFirstChar { it.titlecase() }, fontSize = 15.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                val overBy = row.moneyNumber("over_by")
                if (overBy > 0.01) Text("${moneyAmount(overBy, currency)} ${if (isCost) "over budget" else "above estimate"}", fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.error)
            }
            Icon(Icons.Rounded.ChevronRight, "Details", Modifier.size(22.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

@Composable private fun MoneyNotice(icon: ImageVector, text: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(9.dp), verticalAlignment = Alignment.Top) {
        Icon(icon, null, Modifier.size(21.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(text, Modifier.weight(1f), fontSize = 15.sp, lineHeight = 22.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable private fun MoneyEmpty(title: String, message: String) {
    Surface(color = MaterialTheme.colorScheme.surfaceContainerLow, shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Icon(Icons.Rounded.AccountBalanceWallet, null, Modifier.size(32.dp), tint = MaterialTheme.colorScheme.secondary)
            Text(title, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            Text(message, fontSize = 16.sp, lineHeight = 23.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

private fun moneyCategoryIcon(category: String): ImageVector = when {
    category.contains("food", true) || category.contains("dining", true) || category.contains("groc", true) -> Icons.Rounded.Restaurant
    category.contains("travel", true) || category.contains("transport", true) -> Icons.Rounded.DirectionsBus
    category.contains("rent", true) || category.contains("home", true) -> Icons.Rounded.Home
    category.contains("health", true) || category.contains("medical", true) -> Icons.Rounded.LocalHospital
    category.contains("study", true) || category.contains("education", true) || category.contains("book", true) -> Icons.Rounded.School
    category.contains("shop", true) || category.contains("cloth", true) -> Icons.Rounded.ShoppingBag
    else -> Icons.Rounded.ReceiptLong
}

private fun JSONObject.moneyObjects(key: String): List<JSONObject> {
    val array = optJSONArray(key) ?: return emptyList()
    return (0 until array.length()).mapNotNull { array.optJSONObject(it) }
}
private fun JSONObject.moneyText(key: String): String? = if (!has(key) || isNull(key)) null else optString(key).takeIf { it.isNotBlank() }
private fun JSONObject.moneyNumber(key: String): Double = optDouble(key, 0.0).takeIf { it.isFinite() } ?: 0.0
private fun moneyNumberText(amount: Double): String = NumberFormat.getNumberInstance(Locale.US).apply {
    minimumFractionDigits = 0
    maximumFractionDigits = 2
}.format(amount)
private fun moneyAmount(amount: Double, code: String): String = "$code ${moneyNumberText(amount)}"
private fun moneyPercent(number: Double): String = NumberFormat.getNumberInstance(Locale.US).apply { maximumFractionDigits = 1 }.format(number)
private fun moneyDate(date: String): String = runCatching { LocalDate.parse(date.take(10)).format(DateTimeFormatter.ofPattern("d MMM yyyy", Locale.getDefault())) }.getOrDefault(date)
private fun moneyMonth(month: String): String = runCatching { YearMonth.parse(month).format(DateTimeFormatter.ofPattern("MMM yyyy", Locale.getDefault())) }.getOrDefault(month)
