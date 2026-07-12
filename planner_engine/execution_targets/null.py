"""No-op execution target."""

from datetime import date

from planner_engine.execution_targets.base import ExecutionTargetCapabilities, ExternalExecutionItem, PublishResult, ReconciliationReport
from planner_engine.models import ScheduledBlock


class NullExecutionTarget:
    name = "none"
    capabilities = ExecutionTargetCapabilities(False, False, False, False, False, False, False, False, False)

    def health(self):
        return {"success": True, "target": self.name, "status": "disabled", "capabilities": self.capabilities.__dict__}

    def publish_blocks(self, blocks: list[ScheduledBlock], *, replace_existing: bool = False) -> PublishResult:
        del replace_existing
        return PublishResult(True, self.name, warnings=[f"External publication skipped for {len(blocks)} block(s)"])

    def update_block(self, block: ScheduledBlock, external_id: str) -> PublishResult:
        del block, external_id
        return PublishResult(False, self.name, errors=["No execution target is active"])

    def delete_item(self, external_id: str, *, delete_scope: str = "single") -> PublishResult:
        del external_id, delete_scope
        return PublishResult(False, self.name, errors=["No execution target is active"])

    def list_items(self, start_date: date, end_date: date) -> list[ExternalExecutionItem]:
        del start_date, end_date
        return []

    def reconcile(self, planned_blocks: list[ScheduledBlock], start_date: date, end_date: date) -> ReconciliationReport:
        del planned_blocks
        return ReconciliationReport(self.name, start_date.isoformat(), end_date.isoformat(), warnings=["No downstream target configured"])
