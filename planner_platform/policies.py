"""Policy types used by the guarded Planner OS Tool Registry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EffectType(str, Enum):
    READ = "read"
    PREVIEW = "preview"
    WORKBOOK_WRITE = "workbook_write"
    LOCAL_STATE_WRITE = "local_state_write"
    EXTERNAL_WRITE = "external_write"
    MIXED = "mixed"


class ConfirmationPolicy(str, Enum):
    NONE = "none"
    EXPLICIT_CALL = "explicit_call"
    PREVIEW_REQUIRED = "preview_required"
    EXPLICIT_RESOURCE = "explicit_resource"


class AuditPolicy(str, Enum):
    METADATA = "metadata"
    MUTATION = "mutation"
    SECURITY = "security"


class CloudStatus(str, Enum):
    CANDIDATE = "candidate"
    ADAPTATION_REQUIRED = "adaptation_required"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ToolPolicy:
    effect: EffectType
    confirmation: ConfirmationPolicy
    workspace_required: bool
    calendar_required: bool
    timeout_seconds: int
    audit: AuditPolicy
    cloud_status: CloudStatus
    cloud_reason: str


def policy_for(tool: dict) -> ToolPolicy:
    """Resolve complete policy metadata from one manifest record."""

    name = str(tool["name"])
    effect = EffectType(str(tool["effect"]))
    if name.startswith("apply_"):
        confirmation = ConfirmationPolicy.PREVIEW_REQUIRED
    elif name in {
        "apple_calendar_delete_event",
        "apple_calendar_update_event",
        "calendar_delete_event",
        "calendar_delete_future_series",
        "calendar_delete_series",
        "calendar_update_event",
    }:
        confirmation = ConfirmationPolicy.EXPLICIT_RESOURCE
    elif effect in {EffectType.READ, EffectType.PREVIEW}:
        confirmation = ConfirmationPolicy.NONE
    else:
        confirmation = ConfirmationPolicy.EXPLICIT_CALL

    google_calendar_required = (
        name.startswith("calendar_")
        and name not in {"calendar_repair_mapping"}
    )
    timeout = 120 if effect == EffectType.EXTERNAL_WRITE else 60
    if effect in {EffectType.READ, EffectType.PREVIEW}:
        timeout = 30
    audit = (
        AuditPolicy.SECURITY
        if effect == EffectType.MIXED
        else AuditPolicy.MUTATION
        if effect not in {EffectType.READ, EffectType.PREVIEW}
        else AuditPolicy.METADATA
    )
    cloud = tool["cloud"]
    return ToolPolicy(
        effect=effect,
        confirmation=confirmation,
        workspace_required=True,
        calendar_required=google_calendar_required,
        timeout_seconds=timeout,
        audit=audit,
        cloud_status=CloudStatus(str(cloud["status"])),
        cloud_reason=str(cloud["reason"]),
    )

