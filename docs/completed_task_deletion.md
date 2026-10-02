# Completed task deletion repair

A completed nonrecurring task could not be deleted: `task_completions.task_id` has an `ON DELETE SET NULL` foreign key, but the original source-reference check required `task_id` or `recurrence_key` to remain present. Deleting the task therefore failed with a check violation, returned by Supabase as HTTP 400. Single and batch deletion both encounter the same database constraint.

Migration `0034_preserve_deleted_task_history.sql` adds `deleted_task_id` and a tenant-scoped before-delete trigger. The trigger saves the original task ID before the existing foreign key clears the live reference. The revised check still rejects completions with no source, while allowing preserved history for deleted tasks. Completion dates, recurrence keys and counts stay intact. This does not mark other tasks complete or erase completion records.

Apply migration 0034 to the linked Supabase database using its SQL editor or an authorized database connection. It is independently applicable; unrelated migration 0033 is not a prerequisite. The migration is transactional and rerunnable. Supabase service-role REST credentials cannot apply DDL. At preparation time, live SQL access was unavailable; do not assume the migration is live until deployment is verified.

Regression checks use an isolated embedded PostgreSQL engine, with no production access:

```sh
pnpm --dir tests/sql install --frozen-lockfile
pnpm --dir tests/sql test
```

The test reproduces the original constraint failure, applies the exact migration twice, deletes one completed task and a batch, verifies all history and original task IDs remain, verifies unrelated tasks remain, and verifies source-less completions are rejected.
