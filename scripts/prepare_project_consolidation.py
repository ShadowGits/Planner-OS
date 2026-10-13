"""Generate a backed-up, tenant-scoped atomic data transaction; never applies it."""
from __future__ import annotations
import argparse,json,uuid
from pathlib import Path
from consolidate_planning_projects import Store,configuration,classify,GERMANY_SOURCES

def sql_uuid(value):
    return 'NULL' if value is None else "'"+str(uuid.UUID(str(value)))+"'::uuid"

def build_sql(tenant,projects,tasks,milestones,germany,assignments,milestone_assignments):
    user=tenant['user_id'].removeprefix('eq.');workspace=tenant['workspace_id'].removeprefix('eq.')
    task_values=',\n'.join(f"({sql_uuid(t['id'])}, {sql_uuid(t.get('project_id'))}, '{'germany' if assignments[t['id']]==germany else 'life'}')" for t in tasks)
    mile_values=',\n'.join(f"({sql_uuid(m['id'])}, {sql_uuid(m.get('project_id'))}, '{'germany' if milestone_assignments[m['id']]==germany else 'life'}')" for m in milestones)
    return f'''-- Planner OS: Germany / Life other than Germany consolidation.
-- Data-only, one transaction. No deletion, archival, habit edits or schema changes.
-- Run the entire file together in Supabase SQL editor. Failure rolls everything back.
-- Prepared task count: {len(tasks)}; milestone count: {len(milestones)}.
BEGIN;
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
CREATE TEMP TABLE planner_task_move_plan(id uuid PRIMARY KEY, expected_project uuid, target text NOT NULL) ON COMMIT DROP;
CREATE TEMP TABLE planner_milestone_move_plan(id uuid PRIMARY KEY, expected_project uuid, target text NOT NULL) ON COMMIT DROP;
INSERT INTO planner_task_move_plan VALUES
{task_values};
INSERT INTO planner_milestone_move_plan VALUES
{mile_values};
DO $planner_consolidate$
DECLARE
  owner_id uuid := {sql_uuid(user)};
  target_workspace uuid := {sql_uuid(workspace)};
  germany_id uuid := {sql_uuid(germany)};
  life_id uuid;
  changed_tasks integer;
  changed_milestones integer;
  history_before bigint;
  work_before bigint;
BEGIN
  IF NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.id=germany_id AND p.user_id=owner_id AND p.workspace_id=target_workspace AND lower(p.name)='germany') THEN
    RAISE EXCEPTION 'Germany project is missing or belongs to another workspace';
  END IF;
  PERFORM 1 FROM public.projects p WHERE p.user_id=owner_id AND p.workspace_id=target_workspace FOR UPDATE;
  PERFORM 1 FROM public.planner_tasks t JOIN planner_task_move_plan m ON m.id=t.id WHERE t.user_id=owner_id AND t.workspace_id=target_workspace FOR UPDATE OF t;
  PERFORM 1 FROM public.milestones t JOIN planner_milestone_move_plan m ON m.id=t.id WHERE t.user_id=owner_id AND t.workspace_id=target_workspace FOR UPDATE OF t;
  IF (SELECT count(*) FROM public.planner_tasks t JOIN planner_task_move_plan m ON m.id=t.id WHERE t.user_id=owner_id AND t.workspace_id=target_workspace) <> {len(tasks)} OR
     (SELECT count(*) FROM public.milestones t JOIN planner_milestone_move_plan m ON m.id=t.id WHERE t.user_id=owner_id AND t.workspace_id=target_workspace) <> {len(milestones)} THEN
    RAISE EXCEPTION 'Rows changed since preparation. Nothing moved; prepare a fresh transaction.';
  END IF;
  IF EXISTS(SELECT 1 FROM public.planner_tasks t JOIN planner_task_move_plan m ON m.id=t.id WHERE t.project_id IS DISTINCT FROM m.expected_project) OR
     EXISTS(SELECT 1 FROM public.milestones t JOIN planner_milestone_move_plan m ON m.id=t.id WHERE t.project_id IS DISTINCT FROM m.expected_project) THEN
    RAISE EXCEPTION 'Project ownership changed since preparation. Nothing moved; prepare a fresh transaction.';
  END IF;
  IF (SELECT count(*) FROM public.projects p WHERE p.user_id=owner_id AND p.workspace_id=target_workspace AND lower(p.name)='life other than germany') > 1 THEN
    RAISE EXCEPTION 'More than one Life other than Germany project exists; nothing moved';
  END IF;
  SELECT p.id INTO life_id FROM public.projects p WHERE p.user_id=owner_id AND p.workspace_id=target_workspace AND lower(p.name)='life other than germany';
  IF life_id IS NULL THEN
    INSERT INTO public.projects(user_id,workspace_id,name,status,description)
    VALUES(owner_id,target_workspace,'Life other than Germany','active','Everyday life, personal errands, health, hobbies and miscellaneous tasks.') RETURNING id INTO life_id;
  END IF;
  SELECT count(*) INTO history_before FROM public.task_completions WHERE user_id=owner_id AND workspace_id=target_workspace;
  SELECT count(*) INTO work_before FROM public.task_work_sessions WHERE user_id=owner_id AND workspace_id=target_workspace;
  UPDATE public.milestones t SET project_id=CASE m.target WHEN 'germany' THEN germany_id ELSE life_id END
    FROM planner_milestone_move_plan m WHERE t.id=m.id AND t.user_id=owner_id AND t.workspace_id=target_workspace;
  GET DIAGNOSTICS changed_milestones = ROW_COUNT;
  UPDATE public.planner_tasks t SET project_id=CASE m.target WHEN 'germany' THEN germany_id ELSE life_id END
    FROM planner_task_move_plan m WHERE t.id=m.id AND t.user_id=owner_id AND t.workspace_id=target_workspace;
  GET DIAGNOSTICS changed_tasks = ROW_COUNT;
  IF changed_tasks <> {len(tasks)} OR changed_milestones <> {len(milestones)} THEN
    RAISE EXCEPTION 'Move count mismatch; all changes rolled back';
  END IF;
  IF EXISTS(SELECT 1 FROM public.planner_tasks t JOIN planner_task_move_plan m ON m.id=t.id WHERE t.project_id <> CASE m.target WHEN 'germany' THEN germany_id ELSE life_id END) OR
     EXISTS(SELECT 1 FROM public.milestones t JOIN planner_milestone_move_plan m ON m.id=t.id WHERE t.project_id <> CASE m.target WHEN 'germany' THEN germany_id ELSE life_id END) THEN
    RAISE EXCEPTION 'Move verification failed; all changes rolled back';
  END IF;
  IF (SELECT count(*) FROM public.task_completions WHERE user_id=owner_id AND workspace_id=target_workspace) < history_before OR
     (SELECT count(*) FROM public.task_work_sessions WHERE user_id=owner_id AND workspace_id=target_workspace) < work_before THEN
    RAISE EXCEPTION 'History verification failed; all changes rolled back';
  END IF;
  RAISE NOTICE 'Moved % tasks and % milestones; IDs, schedules, notes and saved histories retained.',changed_tasks,changed_milestones;
END
$planner_consolidate$;
SELECT p.name,count(t.id) AS task_count FROM public.projects p LEFT JOIN public.planner_tasks t ON t.project_id=p.id
 WHERE p.user_id={sql_uuid(user)} AND p.workspace_id={sql_uuid(workspace)} AND lower(p.name) IN ('germany','life other than germany')
 GROUP BY p.id,p.name ORDER BY p.name;
COMMIT;
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cloud-project',default='planner-os-502107');parser.add_argument('--output',type=Path,default=Path('backups/consolidate_germany_and_life.sql'));args=parser.parse_args()
    store=Store(configuration(args.cloud_project));projects=store.rows('projects');tasks=store.rows('planner_tasks');milestones=store.rows('milestones')
    germany=next(p['id'] for p in projects if p['name'].casefold()=='germany');life=next((p['id'] for p in projects if p['name'].casefold()=='life other than germany'),str(uuid.uuid4()))
    assignments=classify(tasks,projects,milestones,germany,life);names={p['id']:p['name'].casefold() for p in projects}
    milestone_assignments={m['id']:germany if names.get(m.get('project_id')) in GERMANY_SOURCES else life for m in milestones}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    backup=args.output.with_suffix('.backup.json');args.output.write_text(build_sql(store.tenant,projects,tasks,milestones,germany,assignments,milestone_assignments));args.output.chmod(0o600)
    backup.write_text(json.dumps({'projects':projects,'tasks':tasks,'milestones':milestones,'assignments':assignments,'milestone_assignments':milestone_assignments},indent=2));backup.chmod(0o600)
    print(json.dumps({'sql':str(args.output.resolve()),'backup':str(backup.resolve()),'tasks':len(tasks),'milestones':len(milestones),'applied':False}),flush=True)
if __name__=='__main__':main()
