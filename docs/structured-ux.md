# Structured UX reference

What both apps copy, taken from Structured 4.6.7 (App Store, 28 Oct 2026): its
App Store screenshots and the step-by-step screenshots in its help centre
(help.structured.app, Tasks & Timeline). Colours were sampled from the
screenshots' pixels; sizes were measured on a 393-pt-wide iPhone screen.
Read this before changing the Timeline on either app.

## Colours

| Use | Hex |
|---|---|
| Accent (year, selected today, + button, buttons, "30m" in gap text) | `#F19E98` |
| Task presets | coral `#F19E98`, orange `#F19C74`, amber `#EAA93B`, green `#91BE6C`, blue `#6085A8`, dark green `#3A8564`, wine `#974667`, navy `#2B5073`, black |
| Capsule and spine ahead of now | `#EBEBEB` |
| Header background | system grouped grey; the timeline sits on a white sheet with rounded top corners and a small grabber |

## Header and week

* Title: **"16. October"** bold black (about 28 pt) then **"2025 ›"** in the accent colour.
* Week strip: weekday (Mon…) small grey, date number semibold.
  * Selected day: filled circle — accent if it is today, black otherwise, white number.
  * Today when not selected: number in the accent colour.
  * Under every day: a row of small overlapping circles in the colours of that day's tasks.
  * Swipe the strip for the previous or next week.

## All-day tasks

Row of round chips above the timeline (about 46 pt), label underneath (12 pt semibold).
Open: grey circle, icon in the task colour. Done: solid task colour, white icon, label struck through.
Drag horizontally to reorder; drag one onto the timeline to give it a time.

## Timeline

* **Scale**: time runs down the page at about **1.6 pt per minute** (2 h ≈ 190 pt), so a phone
  screen shows around six to seven hours. A 15-minute task is a circle (about 48 pt), the minimum.
* **Left column**: each task's start (unless it continues straight from the previous task) and
  end, whole hours inside long tasks, and the **current time in bold black** at its height.
* **Capsule** (about 48 pt wide, fully rounded) on a **spine** that runs through every capsule.
  The spine is coloured (blending from one task's colour to the next) up to now and `#EBEBEB` after.
* **Capsule states**:
  * Ahead of now: `#EBEBEB` fill, icon in the task colour.
  * Under way: filled with the task colour from the top **down to now**, `#EBEBEB` below, with a
    soft edge. The subtitle reads **"28m remaining"** instead of the time range.
  * Time passed: solid task colour, white icon (checked or not).
  * Done: solid, title struck through, tick circle filled with a white check.
* **Text**: subtitle "7:00–7:15 AM (15 min)" grey (↻ when it repeats), title 17 pt semibold,
  "☑ 0/4" under it when there are subtasks.
* **Tick circle** at the far right, outlined in the task colour; filled with a white check when done.
* **Free time**: "You'll have **30m** free. Anything you'd like to fit in?" with a clock icon. A long
  stretch reads "A window: **15h 59m** of potential." with an **Add Task** pill. Gaps of a few
  minutes are just a short piece of spine.

## Drag

1. Hold a task: it lifts as a white card with a shadow (haptic).
2. Move: it becomes a **compact floating chip** (icon, time range, title) under the finger.
3. An **empty outlined capsule** (white, grey border) shows where it will land, with the new start and
   end in **bold** in the left column ("4:15 PM / 4:45 PM"). Nothing else moves.
4. The landing time is the time **at that point of the layout**, so moving across the screen moves
   several hours, and the outline always sits exactly where the task will appear.
5. While dragging, the **+ button turns into a red bin**; drop there to delete (repeating tasks ask
   which occurrences).
6. Drop on the top of the timeline to make it all-day; hover a day in the week strip to move it there;
   hover the Inbox tab to unschedule it.

## Bottom

A floating white pill holding **Inbox · Timeline · AI · Settings** (icon over label, selected in the
accent colour), and a separate round **accent + button** to its right.

## Adding and editing a task

1. Header in the task's colour: round icon, title field, "Suggestions" list, **Continue**.
2. Date row, **time wheel** with the chosen range highlighted as an accent pill, **duration** chips
   (1, 15m, 30, 45, 1h, 1.5h; "…" for custom and presets), **Continue**.
3. Date, time, **Alerts** ("3 Alerts · Nudge"), **Repeat** (Once/Daily/Weekly/Monthly, days, start,
   end), **subtasks**, **notes**, then **Create Task** / **Update Task**.

Colour & Icon sheet: the eight preset colours plus black, suggested icons, recently used, categories,
search; "…" opens a custom colour picker.

## Inbox

A list of white cards (icon, duration, title) with a **+** on each to schedule it; drag one onto the
timeline. Swipe right to check off, left to delete.
