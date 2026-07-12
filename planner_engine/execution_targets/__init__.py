"""Local downstream execution targets for Planner OS."""

from planner_engine.execution_targets.base import (
    ExternalExecutionItem,
    ExecutionTargetCapabilities,
    PublishResult,
    ReconciliationReport,
)
from planner_engine.execution_targets.google_calendar import GoogleCalendarExecutionTarget
from planner_engine.execution_targets.apple_calendar import AppleCalendarExecutionTarget
from planner_engine.execution_targets.null import NullExecutionTarget

__all__ = [
    "ExternalExecutionItem",
    "ExecutionTargetCapabilities",
    "AppleCalendarExecutionTarget",
    "GoogleCalendarExecutionTarget",
    "NullExecutionTarget",
    "PublishResult",
    "ReconciliationReport",
]
