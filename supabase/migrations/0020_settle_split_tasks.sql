-- Split tasks used to hide their leading row from the day and week views, so a
-- task you split and then finished had no reachable tick box. The leader stayed
-- `todo` for ever, and since the counts only look at leaders, it sat in the
-- overdue list permanently.
--
-- The views now show every slot as a peer, and finishing the last slot settles
-- the leader. This closes the ones already stuck.

update planner_tasks as leader
set status = 'done',
    completed_at = coalesce(leader.completed_at, now())
where leader.parent_task_id is null
  and leader.status not in ('done', 'skipped')
  and exists (
      select 1 from planner_tasks as slot
      where slot.parent_task_id = leader.id
  )
  and not exists (
      select 1 from planner_tasks as slot
      where slot.parent_task_id = leader.id
        and slot.status not in ('done', 'skipped')
  );
