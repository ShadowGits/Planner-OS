import { PGlite } from '@electric-sql/pglite';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import {randomUUID} from 'node:crypto';
const uid=randomUUID(),wid=randomUUID();
async function setup(){
 const db=new PGlite();
 await db.exec(`CREATE ROLE authenticated; CREATE ROLE service_role; CREATE SCHEMA auth;
 CREATE FUNCTION auth.role() RETURNS text LANGUAGE sql AS $$ SELECT 'service_role'::text $$;
 CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$ SELECT NULL::uuid $$;
 CREATE TABLE workspaces(id uuid PRIMARY KEY,user_id uuid,timezone text,UNIQUE(user_id,id));
 CREATE TABLE planner_tasks(id uuid PRIMARY KEY,user_id uuid,workspace_id uuid,title text,status text,estimated_minutes integer CHECK(estimated_minutes>0),scheduled_date date,start_time time,parent_task_id uuid REFERENCES planner_tasks(id),project_id uuid,milestone_id uuid,priority text,due_date date,notes text,metadata jsonb,starred boolean,completed_at timestamptz);
 CREATE TABLE habits(id uuid PRIMARY KEY,user_id uuid,workspace_id uuid,title text,recurrence_key text,estimated_minutes integer,start_time time);
 CREATE TABLE habit_overrides(user_id uuid,workspace_id uuid,habit_id uuid,on_date date,moved_to date,start_time time,estimated_minutes integer,skipped boolean,UNIQUE(habit_id,on_date));
 CREATE TABLE task_completions(id uuid DEFAULT gen_random_uuid(),user_id uuid,workspace_id uuid,task_id uuid REFERENCES planner_tasks(id),recurrence_key text,completed_on date,source text CHECK(source IN ('dashboard','mcp','api','telegram')));`);
 await db.query('INSERT INTO workspaces VALUES($1,$2,$3)',[wid,uid,'Asia/Kolkata']);
 const migration=fs.readFileSync(new URL('../../supabase/migrations/0035_task_work_sessions.sql',import.meta.url),'utf8');
 await db.exec(migration);await db.exec(migration);
 return db;
}
async function task(db,minutes=180,status='todo',parent=null){const id=randomUUID();await db.query(`INSERT INTO planner_tasks(id,user_id,workspace_id,title,status,estimated_minutes,parent_task_id,scheduled_date,start_time,metadata,project_id,milestone_id,priority,notes,starred) VALUES($1,$2,$3,'Study',$4,$5,$6,'2026-10-02','09:00','{"keep":"yes"}',$7,$8,'high','Keep notes',true)`,[id,uid,wid,status,minutes,parent,randomUUID(),randomUUID()]);return id;}
async function log(db,id,seconds,{request=randomUUID(),split=false,finish=true,user=uid,workspace=wid}={}){
 return (await db.query('SELECT planner_log_work($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) AS result',[user,workspace,request,id,seconds,'timer',finish,split,split?'2026-10-02':null,split?'18:00':null])).rows[0].result;
}
async function row(db,id){return (await db.query('select * from planner_tasks where id=$1',[id])).rows[0];}
test('partial work, atomic split, metadata, exact seconds and retry safety',async()=>{
 const db=await setup();try{
 const id=await task(db);const original=await row(db,id);const req=randomUUID();
 const a=await log(db,id,5400,{split:true,request:req});assert.equal(a.remaining_seconds,5400);
 const children=(await db.query('select * from planner_tasks where parent_task_id=$1 order by status',[id])).rows;
 assert.equal(children.length,2);assert.equal((await row(db,id)).status,'in_progress');
 assert.deepEqual(children.map(r=>r.estimated_minutes),[90,90]);
 for(const c of children){for(const k of ['project_id','milestone_id','notes','priority'])assert.equal(c[k],original[k]);assert.equal(c.metadata.keep,'yes');}
 const done=children.find(c=>c.status==='done'),rest=children.find(c=>c.status==='todo');assert.equal(rest.start_time,'18:00:00');
 assert.equal((await db.query('select task_ref from task_work_sessions')).rows[0].task_ref,done.id);
 assert.deepEqual(await log(db,id,5400,{split:true,request:req}),a);
 assert.equal((await db.query('select count(*)::int n from task_work_sessions')).rows[0].n,1);
 await assert.rejects(log(db,id,10,{request:req}),/WORK_INVALID/);
 await log(db,rest.id,5400);assert.equal((await row(db,id)).status,'done');
 const short=await task(db,1);const b=await log(db,short,17,{split:true});assert.equal(b.remaining_seconds,43);
 assert.equal((await row(db,b.remainder_id)).metadata._work_budget.seconds,43);
 const c=await log(db,b.remainder_id,43);assert.equal(c.remaining_seconds,0);assert.equal(c.done,true);
 }finally{await db.close();}
});
test('paused finish logs partial without completion; manual done stays done; zero and rollback',async()=>{
 const db=await setup();try{
 const id=await task(db);const a=await log(db,id,1801);assert.equal(a.remaining_seconds,8999);assert.equal(a.done,false);assert.equal((await row(db,id)).status,'todo');
 const done=await task(db,60,'done');const b=await log(db,done,600);assert.equal(b.done,true);assert.equal((await row(db,done)).status,'done');
 const zero=await task(db);const c=await log(db,zero,0,{split:true});assert.equal(c.remainder_id,zero);assert.equal((await row(db,zero)).estimated_minutes,180);
 const foreign=randomUUID();await assert.rejects(log(db,id,10,{user:foreign}),/WORK_NOT_FOUND/);
 const req=randomUUID();await assert.rejects(log(db,id,86400,{split:true,request:req}),/no remaining/);
 assert.equal((await db.query('select count(*)::int n from task_work_sessions where id=$1',[req])).rows[0].n,0);
 await db.exec(`CREATE FUNCTION fail_split() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.parent_task_id IS NOT NULL THEN RAISE EXCEPTION 'simulated insert failure'; END IF; RETURN NEW; END $$;CREATE TRIGGER fail_split BEFORE INSERT ON planner_tasks FOR EACH ROW EXECUTE FUNCTION fail_split();`);
 const failed=randomUUID();await assert.rejects(log(db,id,10,{split:true,request:failed}),/simulated/);
 assert.equal((await db.query('select count(*)::int n from task_work_sessions where id=$1',[failed])).rows[0].n,0);assert.equal((await row(db,id)).status,'todo');
 }finally{await db.close();}
});
test('habit splitting moves only the occurrence and preserves original work budget',async()=>{
 const db=await setup();try{
 const id=randomUUID();await db.query(`INSERT INTO habits VALUES($1,$2,$3,'Reading','read',180,'09:00')`,[id,uid,wid]);
 const ref=`habit:${id}:2026-10-02`;const a=await log(db,ref,5400,{split:true});assert.equal(a.remaining_seconds,5400);
 assert.equal((await db.query('select estimated_minutes from habits')).rows[0].estimated_minutes,180);
 assert.equal((await db.query('select estimated_minutes from habit_overrides')).rows[0].estimated_minutes,90);
 const b=await log(db,ref,1800,{split:true});assert.equal(b.remaining_seconds,3600);
 assert.equal((await db.query('select estimated_minutes from habit_overrides')).rows[0].estimated_minutes,60);
 const c=await log(db,ref,3600);assert.equal(c.done,true);assert.equal((await db.query('select count(*)::int n from task_completions')).rows[0].n,1);
 }finally{await db.close();}
});
