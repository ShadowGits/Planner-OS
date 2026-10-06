# Planner OS interface inventory

Generated from committed revision `fcf407485a3049fa10d5aef8f4c94d88b0408858`. Regenerate with `python3 scripts/generate_reference_inventory.py --ref HEAD`.

This is a source inventory, not proof of live deployment. Auth, invariants, feature behavior and operational instructions are in [technical_reference.md](technical_reference.md). Signatures include framework parameters, not just JSON body fields. Source links include line labels for lookup; GitHub links open files. Dynamic routes and OAuth/MCP transport endpoints are explained in the handoff.

Inventory: 71 decorated HTTP routes, 52 MCP tools, 14 request/model classes, 66 public core service methods, 33 tracked SQL migrations.

## HTTP routes

| Method | Path | Handler / parameters | Source |
|---|---|---|---|
| GET | `/api/health` | `health_check() → dict[str, Any]` | [planner_api/app.py:162](../planner_api/app.py) |
| GET | `/api/health` | `configuration_health()` | [planner_api/app.py:451](../planner_api/app.py) |
| GET | `/api/mcp-status` | `mcp_status() → dict[str, Any]` | [planner_api/app.py:196](../planner_api/app.py) |
| GET | `/api/workspaces` | `list_workspaces(user=Depends(current_user))` | [planner_api/app.py:204](../planner_api/app.py) |
| POST | `/api/workspaces` | `create_workspace(body: WorkspaceCreate, user=Depends(current_user))` | [planner_api/app.py:209](../planner_api/app.py) |
| POST | `/api/workspaces/{workspace_id}/activate` | `activate_workspace(workspace_id: UUID, user=Depends(current_user))` | [planner_api/app.py:220](../planner_api/app.py) |
| DELETE | `/api/workspaces/{workspace_id}/google-calendar` | `disconnect_google(workspace_id: UUID, user=Depends(current_user))` | [planner_api/app.py:301](../planner_api/app.py) |
| POST | `/api/workspaces/{workspace_id}/google-calendar/connect` | `connect_google(workspace_id: UUID, user=Depends(current_user))` | [planner_api/app.py:228](../planner_api/app.py) |
| GET | `/api/workspaces/{workspace_id}/google-calendar/status` | `google_status(workspace_id: UUID, user=Depends(current_user))` | [planner_api/app.py:283](../planner_api/app.py) |
| GET | `/app/` | `pwa_index()` | [planner_api/day.py:601](../planner_api/day.py) |
| GET | `/app/index.html` | `pwa_index()` | [planner_api/day.py:601](../planner_api/day.py) |
| GET | `/app/sw.js` | `pwa_service_worker()` | [planner_api/day.py:605](../planner_api/day.py) |
| GET | `/auth/google/callback` | `google_callback(state: str=Query(min_length=32), code: str=Query(min_length=1))` | [planner_api/app.py:243](../planner_api/app.py) |
| GET | `/oauth/authorize/confirm` | `oauth_confirm_page(client_id: str=Query(...), redirect_uri: str=Query(...), state: str=Query(''), code_challenge: str=Query(...), redirect_uri_provided_explicitly: bool=Query(True))` | [planner_api/app.py:320](../planner_api/app.py) |
| POST | `/oauth/authorize/submit` | `oauth_submit(request: Request)` | [planner_api/app.py:373](../planner_api/app.py) |
| POST | `/v2/admin/cleanup-duplicates` | `retired_drive_cleanup(user=Depends(current_user))` | [planner_api/v2.py:651](../planner_api/v2.py) |
| GET | `/v2/books` | `get_books(user=Depends(current_user))` | [planner_api/v2.py:595](../planner_api/v2.py) |
| POST | `/v2/calendar/import-apple` | `import_apple_calendar(days: int=Query(default=30, ge=1, le=90), forget_deletions: bool=Query(default=False), x_cron_key: str &#124; None=Header(default=None), x_app_key: str &#124; None=Header(default=None))` | [planner_api/calendar_bridge.py:116](../planner_api/calendar_bridge.py) |
| POST | `/v2/calendar/sync` | `sync_calendar(days: int=Query(default=7, ge=1, le=31), x_cron_key: str &#124; None=Header(default=None))` | [planner_api/calendar_bridge.py:69](../planner_api/calendar_bridge.py) |
| GET | `/v2/dashboard/metrics` | `dashboard_metrics(x_app_key: str &#124; None=Header(default=None))` | [planner_api/dashboard.py:34](../planner_api/dashboard.py) |
| GET | `/v2/day` | `get_day(on_date: str &#124; None=Query(default=None, alias='date'), x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:136](../planner_api/day.py) |
| GET | `/v2/day/inbox` | `get_inbox(on_date: str &#124; None=Query(default=None, alias='date'), x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:147](../planner_api/day.py) |
| POST | `/v2/day/push/subscribe` | `day_push_subscribe(body: dict, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:467](../planner_api/day.py) |
| POST | `/v2/day/push/test` | `day_push_test(x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:530](../planner_api/day.py) |
| POST | `/v2/day/push/unsubscribe` | `day_push_unsubscribe(body: dict, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:511](../planner_api/day.py) |
| POST | `/v2/day/tasks` | `add_day_task(body: DayTaskCreate, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:220](../planner_api/day.py) |
| POST | `/v2/day/tasks/batch-delete` | `delete_tasks_batch_endpoint(req: BatchDeleteRequest, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:360](../planner_api/day.py) |
| DELETE | `/v2/day/tasks/{task_id}` | `delete_day_task(task_id: str, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:334](../planner_api/day.py) |
| PATCH | `/v2/day/tasks/{task_id}` | `patch_day_task(task_id: str, body: DayTaskPatch, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:241](../planner_api/day.py) |
| POST | `/v2/day/tasks/{task_id}/split` | `split_task(task_id: UUID, body: TaskSplit, x_app_key: str &#124; None=Header(default=None))` | [planner_api/work_log.py:109](../planner_api/work_log.py) |
| GET | `/v2/day/tasks/{task_ref}/work` | `work_info(task_ref: str, x_app_key: str &#124; None=Header(default=None))` | [planner_api/work_log.py:130](../planner_api/work_log.py) |
| POST | `/v2/day/tasks/{task_ref}/work` | `log_work(task_ref: str, body: WorkEntry, x_app_key: str &#124; None=Header(default=None))` | [planner_api/work_log.py:168](../planner_api/work_log.py) |
| GET | `/v2/finance/goals` | `get_finance_goals(user=Depends(current_user))` | [planner_api/v2.py:607](../planner_api/v2.py) |
| GET | `/v2/finance/goals/progress` | `get_finance_goal_progress(user=Depends(current_user))` | [planner_api/v2.py:613](../planner_api/v2.py) |
| POST | `/v2/finance/recurring/run` | `run_recurring_charges(x_cron_key: str &#124; None=Header(default=None))` | [planner_api/v2.py:637](../planner_api/v2.py) |
| GET | `/v2/finance/summary` | `get_finance_summary(month: str &#124; None=None, user=Depends(current_user))` | [planner_api/v2.py:620](../planner_api/v2.py) |
| GET | `/v2/finance/transactions` | `get_finance_transactions(start: str &#124; None=None, end: str &#124; None=None, category: str &#124; None=None, limit: int=Query(default=200, ge=1, le=1000), user=Depends(current_user))` | [planner_api/v2.py:625](../planner_api/v2.py) |
| GET | `/v2/germany/documents` | `get_germany_documents(user=Depends(current_user))` | [planner_api/v2.py:601](../planner_api/v2.py) |
| POST | `/v2/goals/monthly` | `create_monthly_goal(body: MonthlyGoalCreate, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:184](../planner_api/day.py) |
| DELETE | `/v2/goals/monthly/{goal_id}` | `delete_monthly_goal(goal_id: str, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:208](../planner_api/day.py) |
| PATCH | `/v2/goals/monthly/{goal_id}` | `patch_monthly_goal(goal_id: str, body: MonthlyGoalPatch, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:196](../planner_api/day.py) |
| POST | `/v2/google-calendar/connect` | `connect_google_v2(user=Depends(current_user))` | [planner_api/v2.py:107](../planner_api/v2.py) |
| GET | `/v2/metrics` | `metrics(user=Depends(current_user))` | [planner_api/v2.py:98](../planner_api/v2.py) |
| PATCH | `/v2/milestones/{milestone_id}` | `update_milestone(milestone_id: str, body: dict, user=Depends(current_user))` | [planner_api/v2.py:558](../planner_api/v2.py) |
| GET | `/v2/native/dashboard` | `dashboard(section: Section='overview', project_id: UUID &#124; None=None, offset: int=Query(default=0, ge=0, le=100000), row_id: UUID &#124; None=None, on_date: date &#124; None=None, x_app_key: str &#124; None=Header(default=None))` | [planner_api/native_dashboard.py:113](../planner_api/native_dashboard.py) |
| POST | `/v2/native/reminders` | `native_reminders(body: NativeReminderRequest, x_app_key: str &#124; None=Header(default=None))` | [planner_api/native.py:29](../planner_api/native.py) |
| DELETE | `/v2/project_qna/{qna_id}` | `delete_project_qna(qna_id: str, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:453](../planner_api/day.py) |
| PATCH | `/v2/project_qna/{qna_id}` | `patch_project_qna(qna_id: str, body: ProjectQnaPatch, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:442](../planner_api/day.py) |
| GET | `/v2/projects/{project_id}/files` | `list_project_files(project_id: str, user=Depends(current_user))` | [planner_api/v2.py:347](../planner_api/v2.py) |
| POST | `/v2/projects/{project_id}/files/create-document` | `create_project_document(project_id: str, body: dict, user=Depends(current_user))` | [planner_api/v2.py:390](../planner_api/v2.py) |
| POST | `/v2/projects/{project_id}/files/upload` | `upload_project_file(project_id: str, file: UploadFile=File(...), user=Depends(current_user))` | [planner_api/v2.py:409](../planner_api/v2.py) |
| DELETE | `/v2/projects/{project_id}/files/{file_id}` | `delete_project_file(project_id: str, file_id: str, user=Depends(current_user))` | [planner_api/v2.py:438](../planner_api/v2.py) |
| GET | `/v2/projects/{project_id}/files/{file_id}/download` | `download_project_file(project_id: str, file_id: str, user=Depends(current_user))` | [planner_api/v2.py:453](../planner_api/v2.py) |
| GET | `/v2/projects/{project_id}/milestones` | `get_project_milestones(project_id: str, user=Depends(current_user))` | [planner_api/v2.py:532](../planner_api/v2.py) |
| POST | `/v2/projects/{project_id}/milestones` | `create_project_milestone(project_id: str, body: dict, user=Depends(current_user))` | [planner_api/v2.py:539](../planner_api/v2.py) |
| POST | `/v2/projects/{project_id}/project_qna` | `create_project_qna(project_id: str, body: ProjectQnaCreate, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:432](../planner_api/day.py) |
| GET | `/v2/projects/{project_id}/tasks` | `get_project_tasks(project_id: str, fields: str &#124; None=Query(default=None), milestone_id: str &#124; None=Query(default=None), user=Depends(current_user))` | [planner_api/v2.py:492](../planner_api/v2.py) |
| POST | `/v2/projects/{project_id}/tasks` | `create_project_task(project_id: str, body: dict, user=Depends(current_user))` | [planner_api/v2.py:467](../planner_api/v2.py) |
| GET | `/v2/projects/{project_id}/widgets` | `get_project_widgets(project_id: str, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:372](../planner_api/day.py) |
| POST | `/v2/projects/{project_id}/widgets` | `create_project_widget(project_id: str, body: ProjectWidgetCreate, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:382](../planner_api/day.py) |
| GET | `/v2/projects/{project_id}/{table_name}` | `get_project_table(project_id: str, table_name: str, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:419](../planner_api/day.py) |
| POST | `/v2/push/subscribe` | `push_subscribe(request_body: dict, user=Depends(current_user))` | [planner_api/v2.py:198](../planner_api/v2.py) |
| POST | `/v2/push/unsubscribe` | `push_unsubscribe(request_body: dict, user=Depends(current_user))` | [planner_api/v2.py:234](../planner_api/v2.py) |
| GET | `/v2/push/vapid-key` | `get_vapid_key()` | [planner_api/v2.py:251](../planner_api/v2.py) |
| POST | `/v2/reminders/run` | `run_reminders(x_cron_key: str &#124; None=Header(default=None))` | [planner_api/v2.py:126](../planner_api/v2.py) |
| GET | `/v2/study/logs` | `get_study_logs(user=Depends(current_user))` | [planner_api/v2.py:589](../planner_api/v2.py) |
| GET | `/v2/study/topics` | `get_study_topics(user=Depends(current_user))` | [planner_api/v2.py:583](../planner_api/v2.py) |
| POST | `/v2/telegram/webhook` | `telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str &#124; None=Header(default=None))` | [planner_api/v2.py:258](../planner_api/v2.py) |
| GET | `/v2/week` | `get_week(on_date: str &#124; None=Query(default=None, alias='date'), x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:161](../planner_api/day.py) |
| DELETE | `/v2/widgets/{widget_id}` | `delete_project_widget(widget_id: str, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:409](../planner_api/day.py) |
| PATCH | `/v2/widgets/{widget_id}` | `patch_project_widget(widget_id: str, body: ProjectWidgetPatch, x_app_key: str &#124; None=Header(default=None))` | [planner_api/day.py:398](../planner_api/day.py) |

## MCP tools

Return annotations vary: several tools return JSON strings rather than objects. Read the handler before composing a client parser. All registered core tools resolve the authenticated caller's active workspace.

| Tool | Signature | Behavior from source docstring | Source |
|---|---|---|---|
| `core_add_habit` | `core_add_habit(title: str, cadence: str='daily', days_of_week: list[int] &#124; None=None, start_time: str &#124; None=None, estimated_minutes: int &#124; None=None, recurrence_key: str &#124; None=None, project_id: str &#124; None=None, start_date: str &#124; None=None, end_date: str &#124; None=None) → dict` | Create a habit — something repeated where missing a day costs a streak and nothing else, like gym or sleep. Habits never appear in overdue and are never counted as open work; use core_create_task for anything that stays owed when you miss it. cadence is daily or weekly; a weekly habit needs days_of_week as numbers with 0=Sunday. Occurrences are worked out on read, so no rows are generated and none can go stale. | [planner_core/mcp_tools.py:378](../planner_core/mcp_tools.py) |
| `core_add_milestone` | `core_add_milestone(project_id: str, name: str, target_date: str &#124; None=None, sort_order: int=0, notes: str &#124; None=None) → dict` | Add a milestone to a project with an optional YYYY-MM-DD target date. | [planner_core/mcp_tools.py:149](../planner_core/mcp_tools.py) |
| `core_add_monthly_goal` | `core_add_monthly_goal(project_id: str, month: str, description: str) → dict` | Add or update a monthly goal (upsert). month should be YYYY-MM-DD (typically the 1st of the month). | [planner_core/mcp_tools.py:259](../planner_core/mcp_tools.py) |
| `core_add_plan_item` | `core_add_plan_item(kind: str, label: str, amount: float, currency: str='INR', category: str &#124; None=None, due_date: str &#124; None=None, instalments: int=1, certainty: str='likely', notes: str &#124; None=None) → str` | Add one line to the funding plan. kind is 'cost' (money going out — a test fee, tuition, an application) or 'fund' (money coming in — savings, salary put aside, family help, a loan). | [planner_core/mcp_tools.py:545](../planner_core/mcp_tools.py) |
| `core_add_project_qna` | `core_add_project_qna(project_id: str, question: str, answer: str &#124; None=None, status: str='open', notes: str &#124; None=None) → str` | Add a QnA entry to a project. | [planner_core/mcp_tools.py:350](../planner_core/mcp_tools.py) |
| `core_add_project_widget` | `core_add_project_widget(project_id: str, widget_type: str, title: str &#124; None=None, file_id: str &#124; None=None, config: dict &#124; None=None) → str` | Add a widget (qna, csv, text) to a project dashboard. | [planner_core/mcp_tools.py:326](../planner_core/mcp_tools.py) |
| `core_add_recurring_charge` | `core_add_recurring_charge(description: str, amount: float, cadence: str='monthly', day_of_month: int &#124; None=None, day_of_week: int &#124; None=None, category: str &#124; None=None, currency: str='INR', type: str='expense', merchant: str &#124; None=None, payment_method: str &#124; None=None, start_date: str &#124; None=None, end_date: str &#124; None=None, notes: str &#124; None=None) → str` | Set up a repeating charge — rent, a subscription, an EMI, or recurring income like salary. cadence is weekly, monthly, or yearly. For monthly give day_of_month (1-31; a 31 posts on the last day of shorter months). For weekly give day_of_week (0=Monday to 6=Sunday). Yearly repeats on the anniversary of start_date. These post into the passbook automatically as they fall due. | [planner_core/mcp_tools.py:586](../planner_core/mcp_tools.py) |
| `core_add_weekly_goal` | `core_add_weekly_goal(project_id: str, week_start: str, description: str) → dict` | Add or update a weekly goal for a project. week_start should be YYYY-MM-DD (a Monday). | [planner_core/mcp_tools.py:271](../planner_core/mcp_tools.py) |
| `core_complete_habit_day` | `core_complete_habit_day(habit_id: str, on_date: str) → dict` | Tick one day of a habit, which is what feeds its streak. | [planner_core/mcp_tools.py:444](../planner_core/mcp_tools.py) |
| `core_complete_task` | `core_complete_task(task_id: str, note: str &#124; None=None) → dict` | Mark a task done and record the completion for streaks and metrics. | [planner_core/mcp_tools.py:221](../planner_core/mcp_tools.py) |
| `core_create_project` | `core_create_project(name: str, track: str &#124; None=None, description: str &#124; None=None, target_date: str &#124; None=None) → dict` | Create a project (a Germany-move track, a course, any multi-week goal). Optional track label and YYYY-MM-DD target date. | [planner_core/mcp_tools.py:132](../planner_core/mcp_tools.py) |
| `core_create_task` | `core_create_task(title: str, project_id: str &#124; None=None, milestone_id: str &#124; None=None, due_date: str &#124; None=None, scheduled_date: str &#124; None=None, start_time: str &#124; None=None, priority: str='medium', estimated_minutes: int &#124; None=None, recurrence_key: str &#124; None=None, notes: str &#124; None=None, parent_task_id: str &#124; None=None, depends_on: str &#124; None=None, metadata: dict &#124; None=None) → dict` | Create a task, optionally under a project/milestone, with due/scheduled YYYY-MM-DD dates, an HH:MM start_time for the day timeline, and a recurrence_key for habit streaks. To split a task across several sittings, pass the original task's ID as parent_task_id; each slot keeps its own day and time, and finishing them all finishes the original. metadata holds any extra columns the project tracks — the study plan uses {"Subject": "Linear algebra", "Source": "Strang"} — and the project view renders whatever keys it finds as table columns. | [planner_core/mcp_tools.py:175](../planner_core/mcp_tools.py) |
| `core_create_tasks_batch` | `core_create_tasks_batch(items: list[dict]) → dict` | Create many tasks in one call. Each item takes the same fields as core_create_task: title (required), project_id, milestone_id, due_date, scheduled_date, start_time (HH:MM), priority, estimated_minutes, recurrence_key, notes, parent_task_id, depends_on, metadata. All items are validated before any task is created. | [planner_core/mcp_tools.py:209](../planner_core/mcp_tools.py) |
| `core_delete_habit` | `core_delete_habit(habit_id: str) → dict` | Delete a habit and its per-day changes. Completions already recorded stay, so past streaks survive. | [planner_core/mcp_tools.py:413](../planner_core/mcp_tools.py) |
| `core_delete_monthly_goal` | `core_delete_monthly_goal(goal_id: str) → str` | Delete a monthly goal. | [planner_core/mcp_tools.py:368](../planner_core/mcp_tools.py) |
| `core_delete_plan_item` | `core_delete_plan_item(item_id: str) → str` | Remove a line from the funding plan. Spending already logged against it stays in the passbook and simply stops being attributed to the plan. | [planner_core/mcp_tools.py:574](../planner_core/mcp_tools.py) |
| `core_delete_project_qna` | `core_delete_project_qna(qna_id: str) → str` | Delete a QnA entry. | [planner_core/mcp_tools.py:362](../planner_core/mcp_tools.py) |
| `core_delete_project_widget` | `core_delete_project_widget(widget_id: str) → str` | Delete a project widget. | [planner_core/mcp_tools.py:338](../planner_core/mcp_tools.py) |
| `core_delete_recurring_charge` | `core_delete_recurring_charge(recurring_id: str) → str` | Delete a repeating charge. Transactions it already posted are kept. | [planner_core/mcp_tools.py:623](../planner_core/mcp_tools.py) |
| `core_delete_task` | `core_delete_task(task_id: str) → dict` | Delete one task permanently. | [planner_core/mcp_tools.py:227](../planner_core/mcp_tools.py) |
| `core_delete_tasks_batch` | `core_delete_tasks_batch(task_ids: list[str]) → dict` | Batch delete multiple tasks permanently. | [planner_core/mcp_tools.py:233](../planner_core/mcp_tools.py) |
| `core_delete_transaction` | `core_delete_transaction(transaction_id: str) → str` | Delete a logged transaction. | [planner_core/mcp_tools.py:501](../planner_core/mcp_tools.py) |
| `core_finance_goals` | `core_finance_goals() → str` | Savings goals with real progress: the hand-set baseline plus every transaction logged against each goal. Contributions made in a different currency to the goal are reported separately rather than converted. | [planner_core/mcp_tools.py:527](../planner_core/mcp_tools.py) |
| `core_finance_summary` | `core_finance_summary(month: str &#124; None=None) → str` | Spending summary for a month (YYYY-MM, defaults to the current one): totals and category breakdown per currency, with last month alongside for comparison. Currencies are never added together — there is no exchange rate here. | [planner_core/mcp_tools.py:521](../planner_core/mcp_tools.py) |
| `core_inbox_view` | `core_inbox_view(on_date: str &#124; None=None) → dict` | List all open overdue, missed scheduled and unplanned tasks across the workspace. Optional YYYY-MM-DD date defaults to today. Original dates/times are retained; this does not move calendar blocks. | [planner_core/mcp_tools.py:245](../planner_core/mcp_tools.py) |
| `core_list_habits` | `core_list_habits(include_inactive: bool=False) → dict` | List habits and their rules. Streak counts come from core_metrics. | [planner_core/mcp_tools.py:403](../planner_core/mcp_tools.py) |
| `core_list_project_widgets` | `core_list_project_widgets(project_id: str) → str` | List all widgets on a project dashboard. | [planner_core/mcp_tools.py:344](../planner_core/mcp_tools.py) |
| `core_list_projects` | `core_list_projects() → dict` | List all projects with their milestones and open/done task counts. | [planner_core/mcp_tools.py:169](../planner_core/mcp_tools.py) |
| `core_list_recurring_charges` | `core_list_recurring_charges(include_inactive: bool=False) → str` | List repeating charges (rent, subscriptions, EMIs, salary). | [planner_core/mcp_tools.py:611](../planner_core/mcp_tools.py) |
| `core_list_tasks` | `core_list_tasks(status: str &#124; None=None, project_id: str &#124; None=None) → dict` | List tasks, optionally filtered by status or project, sorted by due date. | [planner_core/mcp_tools.py:239](../planner_core/mcp_tools.py) |
| `core_list_transactions` | `core_list_transactions(start: str &#124; None=None, end: str &#124; None=None, category: str &#124; None=None, type: str &#124; None=None, limit: int=200) → str` | List transactions newest first. Window with start/end as YYYY-MM-DD, and filter by category or by type (expense/income). | [planner_core/mcp_tools.py:507](../planner_core/mcp_tools.py) |
| `core_log_expense` | `core_log_expense(description: str, amount: float, category: str &#124; None=None, currency: str='INR', date: str &#124; None=None, merchant: str &#124; None=None, payment_method: str &#124; None=None, goal_id: str &#124; None=None, plan_item_id: str &#124; None=None, notes: str &#124; None=None) → str` | Log money spent. Amount is a positive number; currency is INR (default, day-to-day spending) or EUR (Germany costs). Date defaults to today, YYYY-MM-DD otherwise. Pick category from: Food, Groceries, Transport, Rent, Utilities, Health, Education, Shopping, Entertainment, Subscriptions, Travel, Savings, Fees, Family, Other — reuse these exact names so monthly summaries stay consistent. Pass goal_id when the spend is a transfer into a savings goal (use core_finance_goals to find the id). Pass plan_item_id when the spend is one of the costs budgeted in the funding plan (use core_plan_overview to find the id) — that is what makes the plan show estimate against actual. | [planner_core/mcp_tools.py:458](../planner_core/mcp_tools.py) |
| `core_log_income` | `core_log_income(description: str, amount: float, category: str &#124; None=None, currency: str='INR', date: str &#124; None=None, notes: str &#124; None=None) → str` | Log money received. Pick category from: Salary, Freelance, Refund, Gift, Interest, Other. | [planner_core/mcp_tools.py:479](../planner_core/mcp_tools.py) |
| `core_metrics` | `core_metrics() → dict` | Full metrics snapshot: per-project completion, upcoming deadlines, streaks, totals. | [planner_core/mcp_tools.py:313](../planner_core/mcp_tools.py) |
| `core_plan_overview` | `core_plan_overview(include_unconfirmed: bool=True, as_of: str &#124; None=None) → str` | The funding plan for the move: every budgeted cost against every source of money, both net of what has already been spent or received, plus a month-by-month cash-flow walk. | [planner_core/mcp_tools.py:533](../planner_core/mcp_tools.py) |
| `core_reopen_habit_day` | `core_reopen_habit_day(habit_id: str, on_date: str) → dict` | Un-tick one day of a habit. | [planner_core/mcp_tools.py:451](../planner_core/mcp_tools.py) |
| `core_reschedule_habit_day` | `core_reschedule_habit_day(habit_id: str, on_date: str, moved_to: str &#124; None=None, start_time: str &#124; None=None, estimated_minutes: int &#124; None=None) → dict` | Move or retime a single day of a habit, leaving the rule and every other day untouched — Tuesday's gym pushed to Wednesday, or today's session shortened. on_date is the day the rule put it on, YYYY-MM-DD. | [planner_core/mcp_tools.py:418](../planner_core/mcp_tools.py) |
| `core_skip_habit_day` | `core_skip_habit_day(habit_id: str, on_date: str) → dict` | Drop one day of a habit from the plan, e.g. no gym on a rest day. The streak still shows the day as missed; this only stops it appearing. | [planner_core/mcp_tools.py:437](../planner_core/mcp_tools.py) |
| `core_sync_calendar` | `core_sync_calendar(days: int=7) → dict` | Mirror scheduled tasks to Google Calendar. Returns the number of events created, updated, and deleted. | [planner_core/mcp_tools.py:277](../planner_core/mcp_tools.py) |
| `core_today` | `core_today() → dict` | Today's view: scheduled tasks, due today, overdue, and completions so far. | [planner_core/mcp_tools.py:253](../planner_core/mcp_tools.py) |
| `core_update_habit` | `core_update_habit(habit_id: str, updates: dict) → dict` | Change a habit's rule for good: title, cadence, days_of_week, start_time, estimated_minutes, project_id, start_date, end_date, is_active. Set is_active false to retire a habit while keeping its history. To change one day only, use core_reschedule_habit_day. | [planner_core/mcp_tools.py:408](../planner_core/mcp_tools.py) |
| `core_update_milestone` | `core_update_milestone(milestone_id: str, updates: dict) → dict` | Update milestone fields: name, status (not_started/in_progress/blocked/done), target_date, sort_order, notes. | [planner_core/mcp_tools.py:163](../planner_core/mcp_tools.py) |
| `core_update_monthly_goal` | `core_update_monthly_goal(goal_id: str, description: str) → dict` | Update the description of an existing monthly goal. | [planner_core/mcp_tools.py:265](../planner_core/mcp_tools.py) |
| `core_update_plan` | `core_update_plan(updates: dict) → str` | Change the funding plan itself. Updatable fields: name, base_currency, eur_rate (how many units of the base currency one euro is worth, used for every conversion in the plan), notes. | [planner_core/mcp_tools.py:580](../planner_core/mcp_tools.py) |
| `core_update_plan_item` | `core_update_plan_item(item_id: str, updates: dict) → str` | Correct one line of the funding plan. Updatable fields: label, category, amount (per instalment), currency, due_date, instalments, certainty, notes, sort_order, kind. | [planner_core/mcp_tools.py:568](../planner_core/mcp_tools.py) |
| `core_update_project` | `core_update_project(project_id: str, updates: dict) → dict` | Update project fields: name, track, description, status (active/paused/done/archived), target_date. | [planner_core/mcp_tools.py:143](../planner_core/mcp_tools.py) |
| `core_update_project_qna` | `core_update_project_qna(qna_id: str, updates: dict) → str` | Update a QnA entry. | [planner_core/mcp_tools.py:356](../planner_core/mcp_tools.py) |
| `core_update_project_widget` | `core_update_project_widget(widget_id: str, updates: dict) → str` | Update a project widget configuration. | [planner_core/mcp_tools.py:332](../planner_core/mcp_tools.py) |
| `core_update_recurring_charge` | `core_update_recurring_charge(recurring_id: str, updates: dict) → str` | Change a repeating charge. Set active to false to stop it without losing its history. Updatable: description, amount, currency, type, cadence, day_of_month, day_of_week, category, merchant, payment_method, start_date, end_date, active, notes. | [planner_core/mcp_tools.py:617](../planner_core/mcp_tools.py) |
| `core_update_task` | `core_update_task(task_id: str, updates: dict) → dict` | Update task fields: title, status (todo/in_progress/blocked/done/skipped), priority, due_date, scheduled_date, start_time (HH:MM), estimated_minutes, project_id, milestone_id, notes, parent_task_id, depends_on, and metadata (extra project columns, replaced wholesale). | [planner_core/mcp_tools.py:215](../planner_core/mcp_tools.py) |
| `core_update_task_date_time_batch` | `core_update_task_date_time_batch(updates: list[dict]) → str` | Batch update scheduled dates and times for multiple tasks. Updates should be a list of dicts, each with 'id' and optionally 'scheduled_date', 'due_date', 'start_time'. | [planner_core/mcp_tools.py:319](../planner_core/mcp_tools.py) |
| `core_update_transaction` | `core_update_transaction(transaction_id: str, updates: dict) → str` | Correct a logged transaction. Updatable fields: date, description, amount, currency, type, category, merchant, payment_method, goal_id, plan_item_id, notes. | [planner_core/mcp_tools.py:495](../planner_core/mcp_tools.py) |

## Pydantic request and model fields

A field without a default is required. `Field(...)` contains source-level bounds and patterns. These declarations do not replace business rules or auth. Some models are internal rather than public requests.

### WorkspaceCreate

Source: [planner_api/app.py:34](../planner_api/app.py)

```python
name: str = Field(min_length=1, max_length=120)
timezone: str = Field(default='UTC', min_length=1, max_length=100)
```

### DayTaskCreate

Source: [planner_api/day.py:48](../planner_api/day.py)

```python
title: str = Field(min_length=1, max_length=300)
date: str | None = None
start_time: str | None = None
estimated_minutes: int | None = Field(default=None, gt=0, le=24 * 60)
notes: str | None = None
parent_task_id: str | None = None
project_id: str | None = None
```

### DayTaskUpdate

Source: [planner_api/day.py:58](../planner_api/day.py)

```python
title: str | None = Field(default=None, min_length=1, max_length=300)
scheduled_date: str | None = None
start_time: str | None = None
estimated_minutes: int | None = Field(default=None, gt=0, le=24 * 60)
done: bool | None = None
notes: str | None = None
```

### BatchDeleteRequest

Source: [planner_api/day.py:66](../planner_api/day.py)

```python
task_ids: list[str]
```

### DayTaskPatch

Source: [planner_api/day.py:70](../planner_api/day.py)

```python
done: bool | None = None
start_time: str | None = None
scheduled_date: str | None = None
estimated_minutes: int | None = Field(default=None, gt=0, le=24 * 60)
title: str | None = None
milestone_id: str | None = None
starred: bool | None = None
```

### MonthlyGoalCreate

Source: [planner_api/day.py:81](../planner_api/day.py)

```python
project_id: str
month: str
description: str = Field(min_length=1)
```

### MonthlyGoalPatch

Source: [planner_api/day.py:87](../planner_api/day.py)

```python
description: str
```

### ProjectQnaCreate

Source: [planner_api/day.py:90](../planner_api/day.py)

```python
question: str = Field(min_length=1)
answer: str | None = None
status: str = 'Drafting'
notes: str | None = None
```

### ProjectQnaPatch

Source: [planner_api/day.py:96](../planner_api/day.py)

```python
question: str | None = None
answer: str | None = None
status: str | None = None
notes: str | None = None
```

### ProjectWidgetCreate

Source: [planner_api/day.py:102](../planner_api/day.py)

```python
widget_type: str = Field(min_length=1)
title: str | None = None
file_id: str | None = None
config: dict[str, Any] | None = None
```

### ProjectWidgetPatch

Source: [planner_api/day.py:108](../planner_api/day.py)

```python
title: str | None = None
file_id: str | None = None
config: dict[str, Any] | None = None
order_index: int | None = None
```

### NativeReminderRequest

Source: [planner_api/native.py:22](../planner_api/native.py)

```python
sent_kinds: list[str] = Field(default_factory=list, max_length=2000)
```

### WorkEntry

Source: [planner_api/work_log.py:82](../planner_api/work_log.py)

```python
request_id: UUID
seconds: int = Field(ge=0, le=86400)
source: str = Field(pattern='^(manual|timer)$')
finish: bool = False
split: bool = False
remainder_date: date | None = None
remainder_time: str | None = Field(default=None, pattern='^([01]\\d|2[0-3]):[0-5]\\d$')
```

### TaskSplit

Source: [planner_api/work_log.py:92](../planner_api/work_log.py)

```python
request_id: UUID
first_seconds: int = Field(gt=0, le=86400)
expected_remaining: int = Field(gt=1, le=86400)
```

## Core service methods

| Service | Method | Behavior from source docstring | Source |
|---|---|---|---|
| `ProjectService` | `create_project(self, name: str, *, track: str &#124; None=None, description: str &#124; None=None, target_date: str &#124; None=None) → dict[str, Any]` |  | [planner_core/services.py:111](../planner_core/services.py) |
| `ProjectService` | `update_project(self, project_id: str, updates: dict[str, Any]) → dict[str, Any]` |  | [planner_core/services.py:128](../planner_core/services.py) |
| `ProjectService` | `add_milestone(self, project_id: str, name: str, *, target_date: str &#124; None=None, start_date: str &#124; None=None, sort_order: int=0, notes: str &#124; None=None) → dict[str, Any]` |  | [planner_core/services.py:139](../planner_core/services.py) |
| `ProjectService` | `update_milestone(self, milestone_id: str, updates: dict[str, Any]) → dict[str, Any]` |  | [planner_core/services.py:167](../planner_core/services.py) |
| `ProjectService` | `project_tree(self) → dict[str, Any]` |  | [planner_core/services.py:178](../planner_core/services.py) |
| `ProjectService` | `add_project_qna(self, project_id: str, question: str, answer: str &#124; None=None, status: str='Drafting', notes: str &#124; None=None) → dict[str, Any]` |  | [planner_core/services.py:208](../planner_core/services.py) |
| `ProjectService` | `update_project_qna(self, qna_id: str, updates: dict[str, Any]) → dict[str, Any]` |  | [planner_core/services.py:221](../planner_core/services.py) |
| `ProjectService` | `delete_project_qna(self, qna_id: str) → dict[str, Any]` |  | [planner_core/services.py:229](../planner_core/services.py) |
| `ProjectService` | `list_project_widgets(self, project_id: str) → dict[str, Any]` |  | [planner_core/services.py:233](../planner_core/services.py) |
| `ProjectService` | `add_project_widget(self, project_id: str, widget_type: str, title: str &#124; None=None, file_id: str &#124; None=None, config: dict[str, Any] &#124; None=None) → dict[str, Any]` |  | [planner_core/services.py:240](../planner_core/services.py) |
| `ProjectService` | `update_project_widget(self, widget_id: str, updates: dict[str, Any]) → dict[str, Any]` |  | [planner_core/services.py:251](../planner_core/services.py) |
| `ProjectService` | `delete_project_widget(self, widget_id: str) → dict[str, Any]` |  | [planner_core/services.py:259](../planner_core/services.py) |
| `GoalService` | `add_monthly_goal(self, project_id: str, month: str, description: str) → dict[str, Any]` | Add or update a monthly goal (upsert by project/month). Month should be YYYY-MM-DD (typically the 1st). | [planner_core/services.py:268](../planner_core/services.py) |
| `GoalService` | `update_monthly_goal(self, goal_id: str, description: str) → dict[str, Any]` |  | [planner_core/services.py:282](../planner_core/services.py) |
| `GoalService` | `delete_monthly_goal(self, goal_id: str) → dict[str, Any]` |  | [planner_core/services.py:286](../planner_core/services.py) |
| `GoalService` | `add_weekly_goal(self, project_id: str, week_start: str, description: str) → dict[str, Any]` | Add or update a weekly goal (upsert by project/week). | [planner_core/services.py:290](../planner_core/services.py) |
| `GoalService` | `week_view(self, week_start: date) → dict[str, Any]` | Return monthly and weekly goals that intersect this week. | [planner_core/services.py:303](../planner_core/services.py) |
| `TaskService` | `create_task(self, title: str, *, project_id: str &#124; None=None, milestone_id: str &#124; None=None, due_date: str &#124; None=None, scheduled_date: str &#124; None=None, start_time: str &#124; None=None, priority: str='medium', estimated_minutes: int &#124; None=None, recurrence_key: str &#124; None=None, notes: str &#124; None=None, parent_task_id: str &#124; None=None, depends_on: str &#124; None=None, metadata: dict[str, Any] &#124; None=None) → dict[str, Any]` |  | [planner_core/services.py:366](../planner_core/services.py) |
| `TaskService` | `create_tasks_batch(self, items: list[dict[str, Any]], **kwargs: Any) → dict[str, Any]` |  | [planner_core/services.py:411](../planner_core/services.py) |
| `TaskService` | `forget_deleted_events(self) → dict[str, Any]` | Let previously deleted calendar events be imported again. | [planner_core/services.py:449](../planner_core/services.py) |
| `TaskService` | `import_ics(self, ics_text: str, *, project_id: str &#124; None=None, window_days: int=30, today: date &#124; None=None, forget_deletions: bool=False) → dict[str, Any]` | Turn the one-off events of a public calendar feed into tasks. | [planner_core/services.py:466](../planner_core/services.py) |
| `TaskService` | `update_task(self, task_id: str, updates: dict[str, Any]) → dict[str, Any]` |  | [planner_core/services.py:590](../planner_core/services.py) |
| `TaskService` | `delete_task(self, task_id: str) → dict[str, Any]` |  | [planner_core/services.py:675](../planner_core/services.py) |
| `TaskService` | `delete_tasks_batch(self, task_ids: list[str]) → dict[str, Any]` |  | [planner_core/services.py:683](../planner_core/services.py) |
| `TaskService` | `update_task_date_time_batch(self, updates: list[dict[str, Any]]) → dict[str, Any]` |  | [planner_core/services.py:710](../planner_core/services.py) |
| `TaskService` | `complete_task(self, task_id: str, *, source: str='mcp', note: str &#124; None=None) → dict[str, Any]` |  | [planner_core/services.py:744](../planner_core/services.py) |
| `TaskService` | `complete_by_title(self, text: str, *, source: str='mcp') → dict[str, Any]` | Fuzzy-complete the best open-task match for free text (Telegram tick-back). | [planner_core/services.py:771](../planner_core/services.py) |
| `TaskService` | `today(self) → dict[str, Any]` |  | [planner_core/services.py:806](../planner_core/services.py) |
| `TaskService` | `today_checklist(self) → dict[str, Any]` | One flat list of today's tasks, each flagged done or not, for a tick-box view. A task belongs to today if it is scheduled today, due today, or was completed today; done tasks sort to the bottom. | [planner_core/services.py:842](../planner_core/services.py) |
| `TaskService` | `reopen_task(self, task_id: str) → dict[str, Any]` | Un-tick a task: back to todo and drop its completion rows for today, so checklists and metrics agree with the visible state. | [planner_core/services.py:901](../planner_core/services.py) |
| `TaskService` | `sync_calendar(self, client: Any, days: int=7) → dict[str, Any]` | Mirror the next `days` of scheduled work onto Google Calendar. | [planner_core/services.py:918](../planner_core/services.py) |
| `TaskService` | `timed_items(self, on_date: date) → list[dict[str, Any]]` | Just the timed, open items on a day — for the reminder cron. | [planner_core/services.py:1051](../planner_core/services.py) |
| `TaskService` | `inbox_view(self, on_date: str &#124; None=None) → dict[str, Any]` | Open loose tasks and missed blocks across the workspace. | [planner_core/services.py:1077](../planner_core/services.py) |
| `TaskService` | `day_view(self, on_date: str &#124; None=None, habit_items: list[dict[str, Any]] &#124; None=None, with_slot_context: bool=True, strict: bool=False) → dict[str, Any]` | Tasks belonging to one date, shaped for a timeline: tasks with a start_time carry their slot, the rest form the unscheduled tray. | [planner_core/services.py:1151](../planner_core/services.py) |
| `TaskService` | `week_view(self, on_date: str &#124; None=None) → dict[str, Any]` | Tasks belonging to a week (Mon-Sun) containing on_date. | [planner_core/services.py:1270](../planner_core/services.py) |
| `TaskService` | `list_tasks(self, *, status: str &#124; None=None, project_id: str &#124; None=None) → dict[str, Any]` |  | [planner_core/services.py:1333](../planner_core/services.py) |
| `HabitService` | `add_habit(self, title: str, *, recurrence_key: str &#124; None=None, cadence: str='daily', days_of_week: list[int] &#124; None=None, start_time: str &#124; None=None, estimated_minutes: int &#124; None=None, project_id: str &#124; None=None, start_date: str &#124; None=None, end_date: str &#124; None=None) → dict[str, Any]` |  | [planner_core/services.py:1378](../planner_core/services.py) |
| `HabitService` | `list_habits(self, *, include_inactive: bool=False) → dict[str, Any]` |  | [planner_core/services.py:1417](../planner_core/services.py) |
| `HabitService` | `update_habit(self, habit_id: str, updates: dict[str, Any]) → dict[str, Any]` |  | [planner_core/services.py:1423](../planner_core/services.py) |
| `HabitService` | `delete_habit(self, habit_id: str) → dict[str, Any]` |  | [planner_core/services.py:1438](../planner_core/services.py) |
| `HabitService` | `occurrences(self, start: date, end: date, *, strict: bool=False) → list[dict[str, Any]]` | Every habit occurrence between two dates, overrides applied and completions marked. One query per table however wide the window. | [planner_core/services.py:1460](../planner_core/services.py) |
| `HabitService` | `complete_occurrence(self, habit_id: str, rule_day: date, *, source: str='api') → dict[str, Any]` |  | [planner_core/services.py:1570](../planner_core/services.py) |
| `HabitService` | `reopen_occurrence(self, habit_id: str, rule_day: date) → dict[str, Any]` |  | [planner_core/services.py:1594](../planner_core/services.py) |
| `HabitService` | `reschedule_occurrence(self, habit_id: str, rule_day: date, *, moved_to: str &#124; None=None, start_time: str &#124; None=None, estimated_minutes: int &#124; None=None) → dict[str, Any]` | Move or retime one day of a habit without touching the rule, so skipping Tuesday's gym to Wednesday leaves every other week alone. | [planner_core/services.py:1612](../planner_core/services.py) |
| `HabitService` | `skip_occurrence(self, habit_id: str, rule_day: date) → dict[str, Any]` |  | [planner_core/services.py:1638](../planner_core/services.py) |
| `HabitService` | `star_occurrence(self, habit_id: str, rule_day: date, starred: bool) → dict[str, Any]` | Mark one day of a habit as a win, or unmark it. | [planner_core/services.py:1643](../planner_core/services.py) |
| `MetricsService` | `snapshot(self) → dict[str, Any]` |  | [planner_core/services.py:1663](../planner_core/services.py) |
| `MetricsService` | `flat_snapshot(self, data: dict[str, Any] &#124; None=None) → dict[str, str]` | Flat {metric: value} map in the shape the Deutschland-Dash Planner_Snapshot sheet consumes (<track>_units_total style keys). | [planner_core/services.py:1723](../planner_core/services.py) |
| `ReminderService` | `due_reminders(self, now: datetime &#124; None=None, *, sent_kinds: set[str] &#124; None=None) → list[dict[str, Any]]` |  | [planner_core/services.py:2144](../planner_core/services.py) |
| `ReminderService` | `record_sent(self, kind: str, channel: str, payload: dict[str, Any]) → None` |  | [planner_core/services.py:2243](../planner_core/services.py) |
| `FinanceService` | `log_transaction(self, description: str, amount: float, *, on_date: str &#124; None=None, category: str &#124; None=None, currency: str='INR', kind: str='expense', merchant: str &#124; None=None, payment_method: str &#124; None=None, goal_id: str &#124; None=None, plan_item_id: str &#124; None=None, notes: str &#124; None=None) → dict[str, Any]` |  | [planner_core/services.py:2388](../planner_core/services.py) |
| `FinanceService` | `update_transaction(self, transaction_id: str, updates: dict[str, Any]) → dict[str, Any]` |  | [planner_core/services.py:2437](../planner_core/services.py) |
| `FinanceService` | `delete_transaction(self, transaction_id: str) → dict[str, Any]` |  | [planner_core/services.py:2467](../planner_core/services.py) |
| `FinanceService` | `list_transactions(self, *, start: str &#124; None=None, end: str &#124; None=None, category: str &#124; None=None, kind: str &#124; None=None, limit: int=200) → dict[str, Any]` | The passbook feed: newest first, optionally windowed by date. | [planner_core/services.py:2471](../planner_core/services.py) |
| `FinanceService` | `monthly_summary(self, month: str &#124; None=None) → dict[str, Any]` | Totals for one month, split by currency then by category, with the previous month alongside so the header can show the direction. | [planner_core/services.py:2501](../planner_core/services.py) |
| `FinanceService` | `goal_progress(self) → dict[str, Any]` | Germany savings goals with their hand-set baseline plus everything logged against them. Contributions in another currency are reported separately rather than converted at a rate we do not have. | [planner_core/services.py:2578](../planner_core/services.py) |
| `FinanceService` | `plan_overview(self, *, include_unconfirmed: bool=True, as_of: str &#124; None=None) → dict[str, Any]` | What the move costs, what pays for it, and the month it goes under. | [planner_core/services.py:2624](../planner_core/services.py) |
| `FinanceService` | `add_plan_item(self, kind: str, label: str, amount: float, *, currency: str='INR', category: str &#124; None=None, due_date: str &#124; None=None, instalments: int=1, certainty: str='likely', notes: str &#124; None=None) → dict[str, Any]` | Add one cost line or one funding line to the plan. | [planner_core/services.py:2878](../planner_core/services.py) |
| `FinanceService` | `update_plan_item(self, item_id: str, updates: dict[str, Any]) → dict[str, Any]` | Correct one line of the plan. | [planner_core/services.py:2948](../planner_core/services.py) |
| `FinanceService` | `delete_plan_item(self, item_id: str) → dict[str, Any]` | Remove a line. Any spending logged against it keeps its place in the passbook and simply stops being attributed to the plan. | [planner_core/services.py:2983](../planner_core/services.py) |
| `FinanceService` | `update_plan(self, updates: dict[str, Any]) → dict[str, Any]` | Rename the plan, or change the rate every euro line is read at. | [planner_core/services.py:2989](../planner_core/services.py) |
| `FinanceService` | `add_recurring(self, description: str, amount: float, *, cadence: str='monthly', day_of_month: int &#124; None=None, day_of_week: int &#124; None=None, category: str &#124; None=None, currency: str='INR', kind: str='expense', merchant: str &#124; None=None, payment_method: str &#124; None=None, start_date: str &#124; None=None, end_date: str &#124; None=None, notes: str &#124; None=None) → dict[str, Any]` |  | [planner_core/services.py:3014](../planner_core/services.py) |
| `FinanceService` | `list_recurring(self, *, include_inactive: bool=False) → dict[str, Any]` |  | [planner_core/services.py:3075](../planner_core/services.py) |
| `FinanceService` | `update_recurring(self, recurring_id: str, updates: dict[str, Any]) → dict[str, Any]` |  | [planner_core/services.py:3082](../planner_core/services.py) |
| `FinanceService` | `delete_recurring(self, recurring_id: str) → dict[str, Any]` |  | [planner_core/services.py:3101](../planner_core/services.py) |
| `FinanceService` | `materialize_recurring(self, on_date: str &#124; None=None) → dict[str, Any]` | Turn every recurring rule that has come due into a real passbook entry. Safe to run repeatedly: rows already generated for a date are skipped, and the unique index on (recurring_id, date) is the backstop. | [planner_core/services.py:3105](../planner_core/services.py) |

## SQL migrations

Lists declarations introduced/replaced in each migration. ALTERs, policies, grants, triggers and data repairs require reading the linked SQL. Number gaps are intentional; untracked migration 0033 is excluded.

| Migration | CREATE TABLE declarations | CREATE FUNCTION declarations |
|---|---|---|
| [supabase/migrations/0001_mvp3_foundation.sql](../supabase/migrations/0001_mvp3_foundation.sql) | `audit_events`, `calendar_connections`, `calendar_event_mappings`, `oauth_states`, `planner_operations`, `planner_previews`, `profiles`, `tool_registry_versions`, `workspaces` | `acquire_workspace_lock`, `activate_workspace`, `consume_planner_preview`, `release_workspace_lock` |
| [supabase/migrations/0002_google_oauth.sql](../supabase/migrations/0002_google_oauth.sql) | — | `consume_google_oauth_state` |
| [supabase/migrations/0003_partial_external_id_index.sql](../supabase/migrations/0003_partial_external_id_index.sql) | — | — |
| [supabase/migrations/0004_mcp_oauth_state.sql](../supabase/migrations/0004_mcp_oauth_state.sql) | `mcp_oauth_records` | — |
| [supabase/migrations/0005_projects_tasks_reminders.sql](../supabase/migrations/0005_projects_tasks_reminders.sql) | `milestones`, `planner_tasks`, `projects`, `reminder_log`, `task_completions` | — |
| [supabase/migrations/0006_service_role_grants.sql](../supabase/migrations/0006_service_role_grants.sql) | — | — |
| [supabase/migrations/0007_task_start_time.sql](../supabase/migrations/0007_task_start_time.sql) | — | — |
| [supabase/migrations/0008_monthly_weekly_goals.sql](../supabase/migrations/0008_monthly_weekly_goals.sql) | `monthly_goals`, `weekly_goals` | — |
| [supabase/migrations/0009_project_files_and_drive.sql](../supabase/migrations/0009_project_files_and_drive.sql) | `project_files` | — |
| [supabase/migrations/0010_excel_tables_migration.sql](../supabase/migrations/0010_excel_tables_migration.sql) | `books`, `college_applications`, `colleges`, `finance_goals`, `finance_logs`, `germany_documents`, `study_logs`, `study_problems`, `study_revisions`, `study_subjects`, `study_topics` | — |
| [supabase/migrations/0011_excel_data_seed.sql](../supabase/migrations/0011_excel_data_seed.sql) | — | — |
| [supabase/migrations/0012_custom_germany_tables.sql](../supabase/migrations/0012_custom_germany_tables.sql) | `applications`, `colleges`, `germany_tests`, `professors`, `research_papers` | — |
| [supabase/migrations/0014_project_qna.sql](../supabase/migrations/0014_project_qna.sql) | `project_qna` | — |
| [supabase/migrations/0015_project_widgets.sql](../supabase/migrations/0015_project_widgets.sql) | `project_widgets` | — |
| [supabase/migrations/0016_task_time_slots.sql](../supabase/migrations/0016_task_time_slots.sql) | — | — |
| [supabase/migrations/0017_push_subscriptions.sql](../supabase/migrations/0017_push_subscriptions.sql) | `push_subscriptions` | — |
| [supabase/migrations/0018_finance_tracker.sql](../supabase/migrations/0018_finance_tracker.sql) | `finance_goals`, `finance_logs`, `finance_recurring` | — |
| [supabase/migrations/0019_task_count_rollup.sql](../supabase/migrations/0019_task_count_rollup.sql) | — | `planner_task_counts` |
| [supabase/migrations/0020_settle_split_tasks.sql](../supabase/migrations/0020_settle_split_tasks.sql) | — | — |
| [supabase/migrations/0021_task_metadata.sql](../supabase/migrations/0021_task_metadata.sql) | — | — |
| [supabase/migrations/0022_habits.sql](../supabase/migrations/0022_habits.sql) | `habit_overrides`, `habits` | — |
| [supabase/migrations/0023_convert_habits.sql](../supabase/migrations/0023_convert_habits.sql) | — | — |
| [supabase/migrations/0024_completion_summary.sql](../supabase/migrations/0024_completion_summary.sql) | — | `planner_completion_summary` |
| [supabase/migrations/0025_overdue_includes_dateless.sql](../supabase/migrations/0025_overdue_includes_dateless.sql) | — | `planner_task_counts` |
| [supabase/migrations/0026_reminder_log_any_kind.sql](../supabase/migrations/0026_reminder_log_any_kind.sql) | — | — |
| [supabase/migrations/0027_milestone_progress.sql](../supabase/migrations/0027_milestone_progress.sql) | — | `planner_milestone_progress` |
| [supabase/migrations/0028_apple_event_tombstones.sql](../supabase/migrations/0028_apple_event_tombstones.sql) | `apple_event_tombstones` | — |
| [supabase/migrations/0030_starred_tasks.sql](../supabase/migrations/0030_starred_tasks.sql) | — | — |
| [supabase/migrations/0031_starred_habit_days.sql](../supabase/migrations/0031_starred_habit_days.sql) | — | — |
| [supabase/migrations/0032_funding_plan.sql](../supabase/migrations/0032_funding_plan.sql) | `finance_plan_items`, `finance_plans` | — |
| [supabase/migrations/0034_preserve_deleted_task_history.sql](../supabase/migrations/0034_preserve_deleted_task_history.sql) | — | `preserve_deleted_task_history` |
| [supabase/migrations/0035_task_work_sessions.sql](../supabase/migrations/0035_task_work_sessions.sql) | `task_work_sessions` | `planner_log_work` |
| [supabase/migrations/0036_atomic_task_split.sql](../supabase/migrations/0036_atomic_task_split.sql) | `task_split_requests` | `planner_split_task` |

## Environment variable usage

Names only; no credentials or environment files are read. Includes deployment/runtime controls and OAuth library switches. Availability here does not imply every optional integration must be configured.

| Name | Referencing source files |
|---|---|
| `APPLE_ICS_URL` | [planner_api/calendar_bridge.py](../planner_api/calendar_bridge.py) |
| `BUILD_ID` | [planner_api/app.py](../planner_api/app.py) |
| `BUILD_SHA` | [planner_api/app.py](../planner_api/app.py) |
| `CRON_SECRET` | [planner_api/calendar_bridge.py](../planner_api/calendar_bridge.py), [planner_api/v2.py](../planner_api/v2.py) |
| `DASHBOARD_ACCESS_KEY` | [planner_api/app.py](../planner_api/app.py), [planner_api/dashboard.py](../planner_api/dashboard.py) |
| `GCP_SERVICE_ACCOUNT_FILE` | [planner_integrations/google_drive.py](../planner_integrations/google_drive.py) |
| `GCP_SERVICE_ACCOUNT_JSON` | [planner_integrations/google_drive.py](../planner_integrations/google_drive.py) |
| `GOOGLE_CLIENT_ID` | [planner_platform/google_oauth.py](../planner_platform/google_oauth.py) |
| `GOOGLE_CLIENT_SECRET` | [planner_platform/google_oauth.py](../planner_platform/google_oauth.py) |
| `GOOGLE_DRIVE_ROOT_FOLDER_ID` | [planner_integrations/google_drive.py](../planner_integrations/google_drive.py) |
| `GOOGLE_OAUTH_REDIRECT_URI` | [planner_platform/google_oauth.py](../planner_platform/google_oauth.py), [scripts/check-env.mjs](../scripts/check-env.mjs) |
| `GOOGLE_WEB_CLIENT_ID` | [planner_platform/google_oauth.py](../planner_platform/google_oauth.py) |
| `GOOGLE_WEB_CLIENT_SECRET` | [planner_platform/google_oauth.py](../planner_platform/google_oauth.py) |
| `MCP_ACCOUNTS` | [planner_api/app.py](../planner_api/app.py), [planner_api/mcp.py](../planner_api/mcp.py) |
| `MCP_API_KEY` | [planner_api/app.py](../planner_api/app.py), [planner_api/mcp.py](../planner_api/mcp.py) |
| `MCP_USER_ID` | [planner_api/app.py](../planner_api/app.py), [planner_api/mcp.py](../planner_api/mcp.py), [planner_api/v2.py](../planner_api/v2.py), [scripts/harden_security.py](../scripts/harden_security.py) |
| `NEXT_PUBLIC_PLANNER_API_URL` | [lib/api.ts](../lib/api.ts) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | [lib/supabase.ts](../lib/supabase.ts) |
| `NEXT_PUBLIC_SUPABASE_URL` | [lib/supabase.ts](../lib/supabase.ts) |
| `NODE_ENV` | [lib/api.ts](../lib/api.ts) |
| `OAUTHLIB_RELAX_TOKEN_SCOPE` | [planner_platform/google_oauth.py](../planner_platform/google_oauth.py) |
| `PLANNER_API_URL` | [planner_api/app.py](../planner_api/app.py), [planner_api/mcp.py](../planner_api/mcp.py) |
| `PLANNER_CREDENTIAL_ENCRYPTION_KEY` | [planner_platform/google_oauth.py](../planner_platform/google_oauth.py) |
| `PLANNER_WEB_ORIGINS` | [planner_api/app.py](../planner_api/app.py) |
| `PWA_ACCESS_KEY` | [planner_api/app.py](../planner_api/app.py), [planner_api/calendar_bridge.py](../planner_api/calendar_bridge.py), [planner_api/dashboard.py](../planner_api/dashboard.py), [planner_api/day.py](../planner_api/day.py), [planner_api/native.py](../planner_api/native.py) |
| `SUPABASE_ANON_KEY` | [adapters/supabase/client.py](../adapters/supabase/client.py) |
| `SUPABASE_JWT_AUDIENCE` | [planner_platform/auth.py](../planner_platform/auth.py) |
| `SUPABASE_JWT_ISSUER` | [planner_platform/auth.py](../planner_platform/auth.py) |
| `SUPABASE_SERVICE_ROLE_KEY` | [adapters/supabase/client.py](../adapters/supabase/client.py), [planner_api/app.py](../planner_api/app.py), [planner_platform/google_oauth.py](../planner_platform/google_oauth.py) |
| `SUPABASE_URL` | [adapters/supabase/client.py](../adapters/supabase/client.py), [planner_platform/auth.py](../planner_platform/auth.py) |
| `TELEGRAM_BOT_TOKEN` | [planner_core/telegram.py](../planner_core/telegram.py) |
| `TELEGRAM_CHAT_ID` | [planner_api/v2.py](../planner_api/v2.py), [planner_core/telegram.py](../planner_core/telegram.py) |
| `TELEGRAM_WEBHOOK_SECRET` | [planner_api/v2.py](../planner_api/v2.py) |
| `VAPID_MAILTO` | [planner_core/push.py](../planner_core/push.py) |
| `VAPID_PRIVATE_KEY` | [planner_core/push.py](../planner_core/push.py) |
| `VAPID_PUBLIC_KEY` | [planner_api/v2.py](../planner_api/v2.py) |
| `VERCEL` | [planner_engine/decision_log.py](../planner_engine/decision_log.py) |
