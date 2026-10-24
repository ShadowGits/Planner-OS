import {test} from 'node:test';
import assert from 'node:assert/strict';
import {boot,task,settle} from './harness.mjs';
const input=(env,kind,value)=>{const n=env.doc.getElementById('task-time-'+kind);n.value=value;n.dispatchEvent(new env.window.Event('input',{bubbles:true}));return n;};
const press=(env,kind,key)=>env.doc.getElementById('task-time-'+kind).dispatchEvent(new env.window.KeyboardEvent('keydown',{key,bubbles:true,cancelable:true}));
const open=env=>{env.doc.getElementById('fab').click();env.doc.getElementById('new-title').value='Exact start';};

test('tap dropdowns to create a 24-hour task with no AM/PM conversion',async t=>{
 const env=await boot();t.after(env.close);open(env);
 env.doc.querySelector('[aria-label="Choose hour"]').click();
 const list=env.doc.getElementById('task-time-hour-options');assert.equal(list.children.length,24);
 [...list.children].find(n=>n.textContent==='14').click();
 env.doc.querySelector('[aria-label="Choose minute"]').click();
 const mins=env.doc.getElementById('task-time-minute-options');assert.equal(mins.children.length,12);
 [...mins.children].find(n=>n.textContent==='30').click();
 assert.equal(env.doc.getElementById('new-time').value,'14:30');
 env.doc.getElementById('sheet-save').click();await settle(env.window);
 assert.equal(env.calls.find(c=>c.method==='POST'&&c.path==='/v2/day/tasks').body.start_time,'14:30');
});

test('typing exact minutes supports midnight, noon and the last minute of the day',async t=>{
 const env=await boot();t.after(env.close);
 for(const [hour,minute,expected] of [['0','0','00:00'],['12','00','12:00'],['14','17','14:17'],['23','59','23:59']]){
  open(env);input(env,'hour',hour);input(env,'minute',minute);
  assert.equal(env.window.PlannerTimeEntry.validate(),true);assert.equal(env.doc.getElementById('new-time').value,expected);
 }
});

test('partial and invalid drafts block Save instead of accidentally moving the task into Inbox',async t=>{
 const env=await boot({items:[task({title:'Keep scheduled',start_time:'14:17'})]});t.after(env.close);
 env.doc.querySelector('.row .title').click();
 assert.equal(env.doc.getElementById('task-time-minute').value,'17');
 const before=env.calls.length;
 for(const [hour,minute] of [['','17'],['24','00'],['14','60'],['14',''],['-1','00']]){
  input(env,'hour',hour);input(env,'minute',minute);env.doc.getElementById('sheet-save').click();
  assert.equal(env.doc.getElementById('sheet').classList.contains('hidden'),false);
  assert.equal(env.calls.length,before);assert.match(env.doc.getElementById('task-time-help').textContent,/00–23/);
 }
});

test('Clear time explicitly unschedules and opening another editor does not retain a stale draft',async t=>{
 const env=await boot({items:[task({title:'Scheduled',start_time:'09:07'})]});t.after(env.close);
 env.doc.querySelector('.row .title').click();
 assert.equal(env.doc.getElementById('task-time-hour').value,'09');assert.equal(env.doc.getElementById('task-time-minute').value,'07');
 env.doc.querySelector('.time-entry-clear').click();env.doc.getElementById('sheet-save').click();await settle(env.window);
 assert.equal(env.calls.find(c=>c.method==='PATCH').body.start_time,null);
 open(env);assert.equal(env.doc.getElementById('task-time-hour').value,'');assert.equal(env.doc.getElementById('task-time-minute').value,'');
});

test('keyboard selection supports arrows and Enter; Escape closes only the dropdown, then the editor',async t=>{
 const env=await boot();t.after(env.close);open(env);
 const hour=env.doc.getElementById('task-time-hour');hour.focus();press(env,'hour','ArrowDown');
 assert.equal(hour.getAttribute('aria-expanded'),'true');press(env,'hour','ArrowDown');press(env,'hour','Enter');
 assert.equal(hour.value,'01');assert.equal(env.doc.getElementById('new-time').value,'01:00');
 press(env,'hour','ArrowDown');press(env,'hour','Escape');assert.equal(hour.getAttribute('aria-expanded'),'false');
 assert.equal(env.doc.getElementById('sheet').classList.contains('hidden'),false);
 press(env,'hour','Escape');assert.equal(env.doc.getElementById('sheet').classList.contains('hidden'),true);
});

test('existing exact minute is available in the dropdown and direct canonical restore stays supported',async t=>{
 const env=await boot();t.after(env.close);open(env);
 env.window.PlannerTimeEntry.set('14:17');env.doc.querySelector('[aria-label="Choose minute"]').click();
 assert.ok([...env.doc.getElementById('task-time-minute-options').children].some(n=>n.textContent==='17'));
 env.doc.getElementById('new-time').value='23:59';assert.equal(env.window.PlannerTimeEntry.validate(),true);
 assert.equal(env.doc.getElementById('task-time-hour').value,'23');assert.equal(env.doc.getElementById('task-time-minute').value,'59');
});
