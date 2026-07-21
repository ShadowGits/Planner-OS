"""Postgres-backed Planner OS core: projects, milestones, tasks, metrics, reminders.

This package is the v2 source of truth. Rows live in Supabase Postgres and are
queried directly — no workbook download, locking, or checksum cycle. The Excel
workbook path in planner_engine remains for legacy tools and export.
"""

from planner_core.repository import PlannerCoreRepository
from planner_core.services import (
    MetricsService,
    ProjectService,
    ReminderService,
    TaskService,
)

__all__ = [
    "MetricsService",
    "PlannerCoreRepository",
    "ProjectService",
    "ReminderService",
    "TaskService",
]
