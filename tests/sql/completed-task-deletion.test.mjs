import { PGlite } from '@electric-sql/pglite';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';

test('completed task deletion preserves history and valid source references', async () => {
const db = new PGlite();
const uid='11111111-1111-4111-8111-111111111111';
const wid='22222222-2222-4222-8222-222222222222';
const ids=Array.from({length:6},(_,i)=>`00000000-0000-4000-8000-00000000000${i+1}`);
await db.exec(`CREATE TABLE public.planner_tasks(id uuid PRIMARY KEY,user_id uuid NOT NULL,workspace_id uuid NOT NULL); CREATE TABLE public.task_completions(id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,user_id uuid NOT NULL,workspace_id uuid NOT NULL,task_id uuid REFERENCES public.planner_tasks(id) ON DELETE SET NULL, recurrence_key text,completed_on date NOT NULL DEFAULT CURRENT_DATE, CHECK(task_id IS NOT NULL OR recurrence_key IS NOT NULL));`);
for(const id of ids){await db.query('insert into public.planner_tasks values($1,$2,$3)',[id,uid,wid]); await db.query('insert into public.task_completions(user_id,workspace_id,task_id) values($1,$2,$3)',[uid,wid,id]);}
await assert.rejects(db.query('delete from public.planner_tasks where id=$1',[ids[0]]),error=>error.code==='23514');

const migration=fs.readFileSync(new URL('../../supabase/migrations/0034_preserve_deleted_task_history.sql', import.meta.url),'utf8');
await db.exec(migration);
await db.exec(migration);
await db.query('delete from public.planner_tasks where id=$1',[ids[0]]);
await db.query('delete from public.planner_tasks where id=ANY($1::uuid[])',[ids.slice(1,5)]);
const history=(await db.query('select task_id,recurrence_key,deleted_task_id,completed_on from public.task_completions order by id')).rows;
assert.equal(history.length,6);
assert.deepEqual(history.slice(0,5).map(r=>r.deleted_task_id),ids.slice(0,5));
assert.ok(history.slice(0,5).every(r=>r.task_id===null&&r.recurrence_key===null&&r.completed_on));
assert.equal(history[5].task_id,ids[5]);assert.equal(history[5].deleted_task_id,null);
assert.equal((await db.query('select count(*)::int as n from public.planner_tasks')).rows[0].n,1);
await assert.rejects(db.query('insert into public.task_completions(user_id,workspace_id) values($1,$2)',[uid,wid]),error=>error.code==='23514');

await db.close();

});
