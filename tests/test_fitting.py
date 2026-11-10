"""What "fit it in without clashing" has to get right."""
from __future__ import annotations

from planner_core.fitting import (
    DEFAULT_MINUTES,
    busy_spans,
    fit_day,
    fit_sentence,
    format_clock,
    free_gaps,
    is_slipped,
    item_minutes,
    merge_spans,
    parse_clock,
    placement_order,
    spoken_clock,
)


def task(id, title, start=None, minutes=60, done=False, **extra):
    return {
        "id": id,
        "title": title,
        "start_time": start,
        "estimated_minutes": minutes,
        "done": done,
        **extra,
    }


class TestClock:
    def test_reads_the_shapes_the_day_view_returns(self):
        assert parse_clock("09:30:00") == 570
        assert parse_clock("09:30") == 570
        assert parse_clock("7:05") == 425

    def test_reads_a_small_hours_slot_as_part_of_tonight(self):
        # The day view hands back 25:30 for half past midnight.
        assert parse_clock("25:30") == 1530

    def test_shrugs_at_nonsense(self):
        for bad in (None, "", "not a time", "09:99", "-1:00"):
            assert parse_clock(bad) is None

    def test_writes_a_time_the_task_api_accepts(self):
        assert format_clock(570) == "09:30"
        assert format_clock(1530) == "25:30"

    def test_says_a_time_out_loud(self):
        assert spoken_clock(570) == "9:30 am"
        assert spoken_clock(1145) == "7:05 pm"
        assert spoken_clock(720) == "12:00 pm"
        assert spoken_clock(0) == "12:00 am"
        assert spoken_clock(1530) == "1:30 am"


class TestDuration:
    def test_uses_what_the_task_says(self):
        assert item_minutes(task("1", "Call", minutes=45)) == 45

    def test_falls_back_when_nobody_said(self):
        for missing in (None, 0, -5, "nonsense"):
            assert item_minutes(task("1", "Call", minutes=missing)) == DEFAULT_MINUTES


class TestSpans:
    def test_joins_overlapping_and_touching_spans(self):
        assert merge_spans([(540, 600), (580, 660), (660, 700)]) == [(540, 700)]

    def test_keeps_separate_spans_apart(self):
        assert merge_spans([(540, 600), (660, 700)]) == [(540, 600), (660, 700)]

    def test_a_finished_task_still_holds_its_hour(self):
        items = [task("1", "Gym", start="07:00", minutes=60, done=True)]
        assert busy_spans(items, moving=set()) == [(420, 480)]

    def test_a_task_about_to_move_does_not_block_itself(self):
        items = [task("1", "Gym", start="07:00", minutes=60)]
        assert busy_spans(items, moving={"1"}) == []

    def test_an_untimed_task_blocks_nothing(self):
        assert busy_spans([task("1", "Someday")], moving=set()) == []


class TestGaps:
    def test_an_empty_window_is_one_gap(self):
        assert free_gaps([], 420, 1320) == [(420, 1320)]

    def test_finds_the_space_between_two_bookings(self):
        busy = [(540, 600), (720, 780)]
        assert free_gaps(busy, 420, 1320) == [(420, 540), (600, 720), (780, 1320)]

    def test_ignores_everything_before_now(self):
        busy = [(540, 600)]
        assert free_gaps(busy, 420, 1320, after=660) == [(660, 1320)]

    def test_a_booking_running_past_now_pushes_the_first_gap_later(self):
        busy = [(600, 720)]
        assert free_gaps(busy, 420, 1320, after=660) == [(720, 1320)]

    def test_no_gaps_once_the_window_has_passed(self):
        assert free_gaps([], 420, 1320, after=1320) == []

    def test_a_booking_outside_the_window_is_clipped(self):
        busy = [(300, 480)]
        assert free_gaps(busy, 420, 1320) == [(480, 1320)]


class TestSlipped:
    def test_a_slot_that_finished_unticked_has_slipped(self):
        assert is_slipped(task("1", "Call", start="09:00", minutes=30), after=600)

    def test_a_task_under_way_is_left_alone(self):
        # Started at 9, an hour long, and it is half past: it is happening.
        assert not is_slipped(task("1", "Deep work", start="09:00", minutes=60), after=570)

    def test_a_finished_task_has_not_slipped(self):
        assert not is_slipped(task("1", "Gym", start="07:00", done=True), after=600)

    def test_a_task_still_to_come_has_not_slipped(self):
        assert not is_slipped(task("1", "Dinner", start="19:00"), after=600)


class TestOrder:
    def test_a_starred_task_gets_first_refusal(self):
        items = [task("1", "Small", minutes=15), task("2", "Top win", minutes=15, starred=True)]
        assert [item["id"] for item in placement_order(items)] == ["2", "1"]

    def test_then_whatever_is_due_soonest(self):
        items = [task("1", "Later", due_date="2026-12-01"), task("2", "Sooner", due_date="2026-11-06")]
        assert [item["id"] for item in placement_order(items)] == ["2", "1"]

    def test_then_the_longest_first_because_it_has_fewest_homes(self):
        items = [task("1", "Quick", minutes=15), task("2", "Long", minutes=120)]
        assert [item["id"] for item in placement_order(items)] == ["2", "1"]


class TestFitting:
    def test_places_an_untimed_task_in_the_first_gap(self):
        items = [task("1", "Write", minutes=60)]
        result = fit_day(items)
        assert result["placements"] == [
            {
                "id": "1",
                "title": "Write",
                "start_time": "07:00",
                "start_minutes": 420,
                "minutes": 60,
                "was": None,
            }
        ]
        assert result["unplaced"] == []

    def test_never_books_over_something_already_there(self):
        items = [
            task("fixed", "Appointment", start="11:30", minutes=60),
            task("loose", "Write", minutes=180),
        ]
        result = fit_day(items)
        placed = result["placements"][0]
        # 07:00 to 11:30 is only 4h30, so a 3h task fits before the appointment.
        assert placed["start_time"] == "07:00"
        assert placed["start_minutes"] + placed["minutes"] <= 690

    def test_takes_the_next_gap_when_the_first_is_too_small(self):
        items = [
            task("a", "Standup", start="07:30", minutes=30),
            task("b", "Appointment", start="08:30", minutes=60),
            task("loose", "Deep work", minutes=120),
        ]
        result = fit_day(items)
        # 07:00-07:30 and 08:00-08:30 are too short; it lands after 09:30.
        assert result["placements"][0]["start_time"] == "09:30"

    def test_several_tasks_queue_up_without_overlapping(self):
        items = [task(str(n), f"Task {n}", minutes=60) for n in range(3)]
        result = fit_day(items)
        spans = [(one["start_minutes"], one["start_minutes"] + one["minutes"]) for one in result["placements"]]
        assert len(spans) == 3
        for earlier, later in zip(spans, spans[1:]):
            assert earlier[1] <= later[0]

    def test_says_so_rather_than_cramming_when_the_day_is_full(self):
        items = [
            task("fixed", "All day", start="07:00", minutes=15 * 60),
            task("loose", "Write", minutes=60),
        ]
        result = fit_day(items)
        assert result["placements"] == []
        assert result["unplaced"][0]["id"] == "loose"
        assert result["unplaced"][0]["reason"] in {"day_is_full", "no_gap_big_enough"}

    def test_a_task_too_long_for_any_gap_is_refused_not_trimmed(self):
        items = [
            task("a", "Morning", start="09:00", minutes=60),
            task("b", "Afternoon", start="13:00", minutes=60),
            task("loose", "Marathon", minutes=10 * 60),
        ]
        result = fit_day(items)
        assert result["placements"] == []
        assert result["unplaced"][0]["reason"] == "no_gap_big_enough"

    def test_nothing_is_placed_outside_the_window(self):
        items = [task(str(n), f"Task {n}", minutes=120) for n in range(10)]
        result = fit_day(items, window_start=9 * 60, window_end=17 * 60)
        for one in result["placements"]:
            assert one["start_minutes"] >= 9 * 60
            assert one["start_minutes"] + one["minutes"] <= 17 * 60

    def test_running_late_moves_the_slots_that_went_by(self):
        items = [
            task("missed", "Call", start="09:00", minutes=30),
            task("done", "Gym", start="07:00", minutes=60, done=True),
            task("later", "Dinner", start="19:00", minutes=60),
        ]
        result = fit_day(items, after=10 * 60)
        moved = {one["id"] for one in result["placements"]}
        assert moved == {"missed"}
        assert result["placements"][0]["start_minutes"] >= 10 * 60

    def test_running_late_leaves_what_is_under_way(self):
        items = [task("now", "Deep work", start="09:00", minutes=120)]
        result = fit_day(items, after=10 * 60)
        assert result["placements"] == []

    def test_a_habit_is_never_moved_by_itself(self):
        items = [
            task("habit:7:2026-11-05", "Meditate", start="09:00", minutes=15),
            task("loose", "Write", minutes=60),
        ]
        result = fit_day(
            items,
            after=10 * 60,
            is_fixed=lambda item: str(item["id"]).startswith("habit:"),
        )
        assert [one["id"] for one in result["placements"]] == ["loose"]

    def test_a_named_task_that_cannot_move_says_why(self):
        items = [
            task("done", "Gym", start="07:00", done=True),
            task("habit:7:2026-11-05", "Meditate", start="09:00"),
        ]
        result = fit_day(
            items,
            move_ids=["done", "habit:7:2026-11-05", "ghost"],
            is_fixed=lambda item: str(item["id"]).startswith("habit:"),
        )
        reasons = {one["id"]: one["reason"] for one in result["unplaced"]}
        assert reasons == {"done": "already_done", "habit:7:2026-11-05": "fixed", "ghost": "not_on_this_day"}
        assert result["placements"] == []

    def test_a_gap_between_tasks_is_respected(self):
        items = [task("a", "One", minutes=60), task("b", "Two", minutes=60)]
        result = fit_day(items, gap=15)
        first, second = result["placements"]
        assert second["start_minutes"] >= first["start_minutes"] + first["minutes"] + 15

    def test_it_reports_how_full_the_day_is(self):
        items = [task("a", "Booked", start="09:00", minutes=120)]
        result = fit_day(items, window_start=9 * 60, window_end=17 * 60)
        assert result["booked_minutes"] == 120
        assert result["free_minutes"] == 6 * 60

    def test_it_changes_nothing_it_was_given(self):
        items = [task("1", "Write", minutes=60)]
        before = [dict(item) for item in items]
        fit_day(items)
        assert items == before


class TestSentence:
    def test_one_task(self):
        result = fit_day([task("1", "Write", minutes=60)])
        assert fit_sentence(result) == "Moved Write to 7:00 am."

    def test_several_tasks(self):
        result = fit_day([task(str(n), f"Task {n}", minutes=60) for n in range(3)])
        assert fit_sentence(result) == "Moved 3 tasks, from 7:00 am."

    def test_nothing_to_do(self):
        assert fit_sentence({"placements": [], "unplaced": []}) == "Nothing needed moving."

    def test_mentions_what_would_not_fit(self):
        items = [
            task("fixed", "All day", start="07:00", minutes=15 * 60),
            task("loose", "Write", minutes=60),
        ]
        sentence = fit_sentence(fit_day(items))
        assert "would not fit" in sentence


class TestStartsOnAFiveMinuteMark:
    def test_a_ragged_minute_is_rounded_up_never_back(self):
        result = fit_day([task("1", "Write", minutes=30)], after=15 * 60 + 7)
        assert result["placements"][0]["start_time"] == "15:10"

    def test_a_clean_minute_is_left_alone(self):
        result = fit_day([task("1", "Write", minutes=30)], after=15 * 60 + 5)
        assert result["placements"][0]["start_time"] == "15:05"

    def test_what_has_slipped_is_still_judged_by_the_real_minute(self):
        # Ends at 15:09; at 15:07 it is still running, whatever the rounding.
        items = [task("now", "Call", start="14:39", minutes=30)]
        assert fit_day(items, after=15 * 60 + 7)["placements"] == []
