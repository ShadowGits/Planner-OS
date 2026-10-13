import {PGlite} from '@electric-sql/pglite';
import assert from 'node:assert/strict';
import test from 'node:test';
import {randomUUID} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../',import.meta.url));
function fixture(){
 const user=randomUUID(),workspace=randomUUID(),germany=randomUUID(),study=randomUUID(),misc=randomUUID(),milestone=randomUUID();
 const projects=[{id:germany,name:'Germany'},{id:study,name:'Study'},{id:misc,name:'Personal'}];
 const tasks=[{id:randomUUID(),project_id:study,title:'Maths',milestone_id:milestone,status:'done',notes:'Keep notes',scheduled_date:'2027-01-01',start_time:'09:00',estimated_minutes:45},{id:randomUUID(),project_id:misc,title:'Buy groceries',status:'todo',notes:'Personal',scheduled_date:null,start_time:null,estimated_minutes:15}];
 const milestones=[{id:milestone,project_id:study,name:'Certification',status:'in_progress'}];
 return {tenant:{user_id:'eq.'+user,workspace_id:'eq.'+workspace},projects,tasks,milestones,germany,assignments:Object.fromEntries(tasks.map((t,i)=>[t.id,i===0?germany:'life'])),milestone_assignments:{[milestone]:germany},user,workspace};
}
function query(f){return execFileSync(root+'.venv/bin/python',['-c',"import sys,json;sys.path.insert(0,'scripts');from prepare_project_consolidation import build_sql;d=json.load(sys.stdin);print(build_sql(d['tenant'],d['projects'],d['tasks'],d['milestones'],d['germany'],d['assignments'],d['milestone_assignments']))"],{cwd:root,input:JSON.stringify(f),encoding:'utf8'});}
async function setup(f){
 const db=new PGlite();
 await db.exec(`CREATE TABLE projects(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),user_id uuid,workspace_id uuid,name text,status text,description text);
 CREATE TABLE milestones(id uuid PRIMARY KEY,user_id uuid,workspace_id uuid,project_id uuid REFERENCES projects(id),name text,status text);
 CREATE TABLE planner_tasks(id uuid PRIMARY KEY,user_id uuid,workspace_id uuid,project_id uuid REFERENCES projects(id),milestone_id uuid REFERENCES milestones(id),title text,status text,notes text,scheduled_date date,start_time time,estimated_minutes int);
 CREATE TABLE task_completions(id uuid PRIMARY KEY,user_id uuid,workspace_id uuid,task_id uuid REFERENCES planner_tasks(id));
 CREATE TABLE task_work_sessions(id uuid PRIMARY KEY,user_id uuid,workspace_id uuid,task_ref text,seconds int);`);
 for(const p of f.projects)await db.query("INSERT INTO projects(id,user_id,workspace_id,name,status)VALUES($1,$2,$3,$4,'active')",[p.id,f.user,f.workspace,p.name]);
 for(const m of f.milestones)await db.query('INSERT INTO milestones VALUES($1,$2,$3,$4,$5,$6)',[m.id,f.user,f.workspace,m.project_id,m.name,m.status]);
 for(const t of f.tasks)await db.query('INSERT INTO planner_tasks VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)',[t.id,f.user,f.workspace,t.project_id,t.milestone_id??null,t.title,t.status,t.notes,t.scheduled_date,t.start_time,t.estimated_minutes]);
 await db.query('INSERT INTO task_completions VALUES($1,$2,$3,$4)',[randomUUID(),f.user,f.workspace,f.tasks[0].id]);
 await db.query('INSERT INTO task_work_sessions VALUES($1,$2,$3,$4,60)',[randomUUID(),f.user,f.workspace,f.tasks[0].id]);
 return db;
}
test('atomic project merge retains IDs, fields, milestones and history',async()=>{
 const f=fixture(),db=await setup(f);try{
  const before=(await db.query('SELECT * FROM planner_tasks ORDER BY id')).rows;
  await db.exec(query(f));
  const life=(await db.query("SELECT id FROM projects WHERE name='Life other than Germany'")).rows[0].id;
  const after=(await db.query('SELECT * FROM planner_tasks ORDER BY id')).rows;
  for(let i=0;i<before.length;i++){
   assert.equal(after[i].project_id,after[i].id===f.tasks[0].id?f.germany:life);
   assert.deepEqual({...after[i],project_id:null},{...before[i],project_id:null});
  }
  assert.equal((await db.query('SELECT project_id FROM milestones')).rows[0].project_id,f.germany);
  assert.equal((await db.query('SELECT count(*)::int n FROM task_completions')).rows[0].n,1);
  assert.equal((await db.query('SELECT count(*)::int n FROM task_work_sessions')).rows[0].n,1);
  assert.equal((await db.query("SELECT count(*)::int n FROM projects WHERE status='archived'")).rows[0].n,0);
 }finally{await db.close();}
});
test('late task-write failure rolls back moved milestones and newly created Life project',async()=>{
 const f=fixture(),db=await setup(f);try{
  await db.exec(`CREATE FUNCTION reject_move() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.title='Buy groceries' AND NEW.project_id IS DISTINCT FROM OLD.project_id THEN RAISE EXCEPTION 'forced write failure'; END IF; RETURN NEW; END$$; CREATE TRIGGER reject_move BEFORE UPDATE ON planner_tasks FOR EACH ROW EXECUTE FUNCTION reject_move();`);
  await assert.rejects(db.exec(query(f)),/forced write failure/);await db.exec('ROLLBACK');
  assert.equal((await db.query("SELECT count(*)::int n FROM projects WHERE name='Life other than Germany'")).rows[0].n,0);
  assert.equal((await db.query('SELECT project_id FROM milestones')).rows[0].project_id,f.milestones[0].project_id);
  for(const task of f.tasks)assert.equal((await db.query('SELECT project_id FROM planner_tasks WHERE id=$1',[task.id])).rows[0].project_id,task.project_id);
 }finally{await db.close();}
});
test('changed project ownership refuses the full merge',async()=>{
 const f=fixture(),db=await setup(f);try{
  await db.query('UPDATE planner_tasks SET project_id=$1 WHERE id=$2',[f.germany,f.tasks[1].id]);
  await assert.rejects(db.exec(query(f)),/ownership changed/);await db.exec('ROLLBACK');
  assert.equal((await db.query('SELECT project_id FROM milestones')).rows[0].project_id,f.milestones[0].project_id);
 }finally{await db.close();}
});
