import {test} from 'node:test';
import assert from 'node:assert/strict';
import {boot,task,settle} from './harness.mjs';

test('settings hides all task time logging and work history while task completion still works',async t=>{
  const env=await boot({items:[task({title:'Tracked task',worked_seconds:900})]});t.after(env.close);
  const {window:w,doc}=env;
  doc.querySelector('#view-toggle').click();await settle(w);
  assert.match(doc.querySelector('.todo-meta').textContent,/worked/);
  const toggle=doc.querySelector('#tracking-enabled');toggle.checked=false;toggle.dispatchEvent(new w.Event('change'));
  await settle(w);assert.equal(w.PlannerFocus.enabled(),false);
  assert.doesNotMatch(doc.querySelector('.todo-meta').textContent,/worked/);
  doc.querySelector('.todo-details').click();
  assert.equal(doc.querySelector('#sheet-focus-actions').classList.contains('hidden'),true);
  const before=env.calls.length;
  await w.PlannerWorkLog.open(task()); assert.equal(doc.querySelector('.work-log-overlay'),null);
  assert.equal(env.calls.length,before);
  doc.querySelector('#sheet-close').click();
  doc.querySelector('.todo-row .ring').click();await settle(w);
  assert.equal(doc.querySelector('.todo-row').classList.contains('done'),true);
  assert.equal(w.PlannerFocus.start(task()),false);
  toggle.checked=true;toggle.dispatchEvent(new w.Event('change'));await settle(w);
  doc.querySelector('.todo-details').click();
  assert.equal(doc.querySelector('#sheet-focus-actions').classList.contains('hidden'),false);
});

test('another browser tab turning off tracking closes unsaved work entry and releases the page',async t=>{
  const env=await boot({items:[task()],onRequest:({method,path})=>path.endsWith('/work')?{success:true,data:{task:task(),planned_seconds:1800,worked_seconds:0,remaining_seconds:1800}}:null});t.after(env.close);
  const {window:w,doc}=env;await w.PlannerWorkLog.open(task());
  assert.ok(doc.querySelector('.work-log-overlay'));
  w.localStorage.setItem('planner-time-tracking-enabled','false');
  w.dispatchEvent(new w.StorageEvent('storage',{key:'planner-time-tracking-enabled',newValue:'false'}));await settle(w);
  assert.equal(doc.querySelector('.work-log-overlay'),null);assert.equal(doc.querySelector('main').inert,undefined);
  assert.equal(env.calls.some(c=>c.path.endsWith('/work')&&c.method==='POST'),false);
});
