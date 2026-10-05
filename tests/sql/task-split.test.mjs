import { PGlite } from '@electric-sql/pglite';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import { randomUUID } from 'node:crypto';

const user = randomUUID(), workspace = randomUUID();
async function setup() {
  const db = new PGlite();
  await db.exec(`CREATE ROLE authenticated; CREATE ROLE service_role; CREATE SCHEMA auth;
    CREATE FUNCTION auth.role() RETURNS text LANGUAGE sql AS $$ SELECT 'service_role'::text $$;
    CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$ SELECT NULL::uuid $$;
    CREATE TABLE workspaces(id uuid PRIMARY KEY,user_id uuid,timezone text,UNIQUE(user_id,id));
    CREATE TABLE planner_tasks(id uuid PRIMARY KEY,user_id uuid,workspace_id uuid,title text,status text,
      estimated_minutes integer CHECK(estimated_minutes>0),scheduled_date date,start_time time,
      parent_task_id uuid REFERENCES planner_tasks(id),project_id uuid,milestone_id uuid,priority text,
      due_date date,notes text,metadata jsonb,starred boolean,completed_at timestamptz,recurrence_key text,
      depends_on uuid REFERENCES planner_tasks(id) ON DELETE SET NULL,created_at timestamptz DEFAULT now(),updated_at timestamptz DEFAULT now());
    CREATE TABLE habits(id uuid PRIMARY KEY,user_id uuid,workspace_id uuid,title text,recurrence_key text,estimated_minutes integer,start_time time);
    CREATE TABLE habit_overrides(user_id uuid,workspace_id uuid,habit_id uuid,on_date date,moved_to date,start_time time,estimated_minutes integer,skipped boolean,UNIQUE(habit_id,on_date));
    CREATE TABLE task_completions(id uuid DEFAULT gen_random_uuid(),user_id uuid,workspace_id uuid,
      task_id uuid REFERENCES planner_tasks(id),recurrence_key text,completed_on date,source text CHECK(source IN ('dashboard','mcp','api','telegram')));`);
  await db.query('INSERT INTO workspaces VALUES($1,$2,$3)', [workspace,user,'Asia/Kolkata']);
  for (const file of ['0035_task_work_sessions.sql','0036_atomic_task_split.sql']) {
    const migration = fs.readFileSync(new URL(`../../supabase/migrations/${file}`,import.meta.url),'utf8');
    await db.exec(migration); await db.exec(migration);
  }
  return db;
}
async function addTask(db,minutes=180,status='todo') {
  const id=randomUUID(),dependency=randomUUID();
  await db.query(`INSERT INTO planner_tasks(id,user_id,workspace_id,title,status,estimated_minutes)
    VALUES($1,$2,$3,'Prerequisite','done',1)`,[dependency,user,workspace]);
  await db.query(`INSERT INTO planner_tasks(id,user_id,workspace_id,title,status,estimated_minutes,
    scheduled_date,start_time,project_id,milestone_id,priority,due_date,notes,metadata,starred,depends_on)
    VALUES($1,$2,$3,'Study algebra',$4,$5,'2026-10-05','09:00',$6,$7,'high','2026-10-10',
      'Keep my notes','{"Subject":"Algebra","custom":{"value":7}}',true,$8)`,
    [id,user,workspace,status,minutes,randomUUID(),randomUUID(),dependency]);
  return id;
}
async function split(db,id,first,remaining,{request=randomUUID(),uid=user,wid=workspace}={}) {
  return (await db.query('SELECT planner_split_task($1,$2,$3,$4,$5,$6) AS result',
    [uid,wid,request,id,first,remaining])).rows[0].result;
}
async function log(db,id,seconds) {
  return (await db.query('SELECT planner_log_work($1,$2,$3,$4,$5,$6,false,false,null,null) AS result',
    [user,workspace,randomUUID(),id,seconds,'manual'])).rows[0].result;
}
async function row(db,id) {return (await db.query('SELECT * FROM planner_tasks WHERE id=$1',[id])).rows[0];}
async function children(db,id) {return (await db.query('SELECT * FROM planner_tasks WHERE parent_task_id=$1',[id])).rows;}
function budget(task) {return task.metadata._work_budget.seconds;}
function preserves(task,original) {
  for (const key of ['title','project_id','milestone_id','priority','notes','due_date','recurrence_key','user_id','workspace_id']) {
    assert.deepEqual(task[key],original[key],key);
  }
  assert.deepEqual(task.depends_on,original.depends_on);
  assert.equal(task.metadata.Subject,'Algebra'); assert.deepEqual(task.metadata.custom,{value:7});
}

test('root split is retry safe, preserves task details, and repeated child splitting stays flat',async()=>{
  const db=await setup();try {
    const id=await addTask(db);const original=await row(db,id);const request=randomUUID();
    const result=await split(db,id,5400,10800,{request});
    assert.equal(result.parent_id,id);assert.equal(result.worked_id,null);
    assert.equal((await row(db,id)).status,'in_progress');
    let slots=await children(db,id);assert.equal(slots.length,2);
    assert.equal(slots.reduce((sum,t)=>sum+budget(t),0),10800);
    for(const slot of slots){preserves(slot,original);assert.equal(slot.starred,true);}
    assert.equal((await row(db,result.first_id)).start_time,'09:00:00');
    assert.equal((await row(db,result.second_id)).start_time,null);
    assert.deepEqual(await split(db,id,5400,10800,{request}),result);
    assert.equal((await children(db,id)).length,2);
    await assert.rejects(split(db,id,5400,10800),/already split/);
    await assert.rejects(split(db,id,5300,10800,{request}),/already used/);
    const again=await split(db,result.second_id,2700,5400);
    assert.equal(again.first_id,result.second_id);assert.equal(again.parent_id,id);
    slots=await children(db,id);assert.equal(slots.length,3);
    assert.equal(slots.reduce((sum,t)=>sum+budget(t),0),10800);
    assert.equal((await children(db,result.second_id)).length,0);
    assert.equal((await db.query('SELECT count(*)::int n FROM task_work_sessions')).rows[0].n,0);
  }finally{await db.close();}
});

test('logging partial hours then splitting partitions only remaining work, including exact seconds',async()=>{
  const db=await setup();try {
    const id=await addTask(db);const original=await row(db,id);
    const actual=await log(db,id,3601);assert.equal(actual.remaining_seconds,7199);
    const result=await split(db,id,3600,7199);
    assert.equal(result.worked_seconds,3601);assert.equal(result.first_seconds,3600);assert.equal(result.second_seconds,3599);
    const slots=await children(db,id);assert.equal(slots.length,3);
    assert.equal(slots.reduce((sum,t)=>sum+budget(t),0),10800);
    const done=await row(db,result.worked_id);assert.equal(done.status,'done');assert.equal(budget(done),3601);
    const first=await row(db,result.first_id);
    assert.equal(first.start_time,'10:01:00');assert.deepEqual(first.scheduled_date,original.scheduled_date);
    assert.equal(done.start_time,'09:00:00');
    assert.equal((await db.query('SELECT task_ref,seconds FROM task_work_sessions')).rows[0].task_ref,result.worked_id);
    assert.equal((await db.query('SELECT task_id FROM task_completions')).rows[0].task_id,result.worked_id);
    for(const slot of slots)preserves(slot,original);
    await log(db,result.first_id,17);
    const again=await split(db,result.first_id,1700,3583);
    assert.equal(again.worked_id,result.first_id);assert.equal(again.parent_id,id);
    assert.equal((await row(db,result.first_id)).status,'done');
    assert.equal((await children(db,id)).length,5);
    assert.equal((await children(db,id)).reduce((sum,t)=>sum+budget(t),0),10800);
    assert.equal((await children(db,result.first_id)).length,0);
    const totals=(await db.query('SELECT sum(seconds)::int n FROM task_work_sessions')).rows[0];assert.equal(totals.n,3618);
  }finally{await db.close();}
});

test('remaining work starts after the completed block across midnight',async()=>{
  const db=await setup();try {
    const id=await addTask(db);
    await db.query("UPDATE planner_tasks SET start_time='23:30' WHERE id=$1",[id]);
    const original=await row(db,id);await log(db,id,3601);
    const result=await split(db,id,3600,7199);
    const first=await row(db,result.first_id),done=await row(db,result.worked_id);
    assert.equal(first.start_time,'00:31:00');
    assert.equal(first.scheduled_date.toISOString().slice(0,10),'2026-10-06');
    assert.equal(done.start_time,'23:30:00');assert.deepEqual(done.scheduled_date,original.scheduled_date);
    preserves(first,original);preserves(done,original);
    assert.equal((await children(db,id)).reduce((sum,t)=>sum+budget(t),0),10800);
  }finally{await db.close();}
});

test('stale budgets, completed tasks, invalid portions and foreign tenants cannot split',async()=>{
  const db=await setup();try {
    const id=await addTask(db);await log(db,id,600);
    await assert.rejects(split(db,id,5400,10800),/remaining work changed/);
    await assert.rejects(split(db,id,0,10200),/Both sessions/);
    await assert.rejects(split(db,id,10200,10200),/Both sessions/);
    await assert.rejects(split(db,id,5100,10200,{uid:randomUUID()}),/SPLIT_NOT_FOUND/);
    const otherUser=randomUUID(),otherWorkspace=randomUUID();
    await db.query('INSERT INTO workspaces VALUES($1,$2,$3)',[otherWorkspace,otherUser,'Asia/Kolkata']);
    await assert.rejects(split(db,id,5100,10200,{uid:otherUser,wid:otherWorkspace}),/SPLIT_NOT_FOUND/);
    const done=await addTask(db,60,'done');await assert.rejects(split(db,done,1800,3600),/unfinished task/);
    assert.equal((await children(db,id)).length,0);
    assert.equal((await db.query('SELECT count(*)::int n FROM task_split_requests')).rows[0].n,0);
  }finally{await db.close();}
});

test('failure creating the second open session rolls back tasks, actual history and retry record',async()=>{
  const db=await setup();try {
    const id=await addTask(db);await log(db,id,3600);const original=await row(db,id);const request=randomUUID();
    await db.exec(`CREATE FUNCTION fail_second_slot() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF NEW.parent_task_id IS NOT NULL AND NEW.status='todo' AND NEW.start_time IS NULL THEN
        RAISE EXCEPTION 'simulated second slot insert failure'; END IF; RETURN NEW; END $$;
      CREATE TRIGGER fail_second_slot BEFORE INSERT ON planner_tasks FOR EACH ROW EXECUTE FUNCTION fail_second_slot();`);
    await assert.rejects(split(db,id,3600,7200,{request}),/simulated second slot/);
    assert.deepEqual(await row(db,id),original);assert.equal((await children(db,id)).length,0);
    assert.equal((await db.query('SELECT task_ref,seconds FROM task_work_sessions')).rows[0].task_ref,id);
    assert.equal((await db.query('SELECT count(*)::int n FROM task_completions')).rows[0].n,0);
    assert.equal((await db.query('SELECT count(*)::int n FROM task_split_requests WHERE id=$1',[request])).rows[0].n,0);
    await db.exec('DROP TRIGGER fail_second_slot ON planner_tasks;');
    const retry=await split(db,id,3600,7200,{request});assert.equal((await children(db,id)).length,3);
    assert.deepEqual(await split(db,id,3600,7200,{request}),retry);
  }finally{await db.close();}
});
