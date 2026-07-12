from __future__ import annotations

from datetime import date
from unittest import TestCase

from planner_engine.command_router import parse_common_intent


class CommandRouterMVP2Tests(TestCase):
    def test_common_mvp2_phrases_parse_to_safe_commands(self) -> None:
        today = date(2026, 7, 10)

        self.assertEqual(
            parse_common_intent("switch future publishing to Apple Calendar", today=today).command_type,
            "switch_active_execution_target",
        )
        self.assertEqual(parse_common_intent("stop publishing externally", today=today).payload["target"], "none")
        self.assertEqual(
            parse_common_intent("publish today using my active target", today=today).command_type,
            "publish_active_target",
        )
        self.assertEqual(
            parse_common_intent("undo the last planner change", today=today).command_type,
            "undo_last_change",
        )
        self.assertEqual(
            parse_common_intent("diagnose planner", today=today).command_type,
            "planner_doctor",
        )
        self.assertEqual(
            parse_common_intent("daily review", today=today).command_type,
            "daily_review",
        )
        self.assertEqual(
            parse_common_intent("weekly review", today=today).command_type,
            "weekly_review",
        )
        self.assertEqual(
            parse_common_intent("monthly review", today=today).payload["month"],
            "Jul 2026",
        )
        self.assertEqual(
            parse_common_intent("move gym to evening", today=today).command_type,
            "update_preference",
        )
        delete = parse_common_intent(
            "delete tomorrow's Planner OS events from Apple Calendar",
            today=today,
        )
        self.assertEqual(delete.command_type, "delete_external_items")
        self.assertTrue(delete.requires_confirmation)
