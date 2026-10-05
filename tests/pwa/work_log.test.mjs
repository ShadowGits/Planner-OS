import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {JSDOM} from 'jsdom';
const script = readFileSync(new URL('../../planner_api/static/pwa/work-log.js', import.meta.url), 'utf8');
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
const task = {id: 'one', title: '<img src=x onerror=bad()>', start_time: '10:00', scheduled_date: '2026-10-05', estimated_minutes: 120, done: false};
function boot({info = {}, fail = false, items = [], key = 'account-one'} = {}) {
  const dom = new JSDOM('<main><button id="origin">Log time</button></main>', {url: 'https://planner.test/app/', runScripts: 'dangerously'});
  const {window} = dom;
  const NativeDate = window.Date;
  window.Date = class extends NativeDate { constructor(...args) { super(...(args.length ? args : ['2026-10-05T06:00:00Z'])); } static now() { return new NativeDate('2026-10-05T06:00:00Z').getTime(); } };
  const calls = [], saved = [];
  window.eval(script);
  let failures = fail ? 1 : 0;
  window.PlannerWorkLog.configure({getKey: () => key, getContext: () => ({date: '2026-10-05', tz: 'Asia/Kolkata', items}), onSaved: () => saved.push(true), api: async (method, path, body) => {
    calls.push({method, path, body: body && JSON.parse(JSON.stringify(body))});
    if (method === 'POST') { if (failures--) throw new Error('Offline'); return {success: true}; }
    return {data: {task, blocks: [], planned_seconds: 7200, worked_seconds: 600, remaining_seconds: 6600, ...info}};
  }});
  window.document.querySelector('#origin').focus();
  return {dom, window, doc: window.document, calls, saved};
}
const input = (env, field, value) => { const node = env.doc.querySelector(`input[type="${field}"]`); node.value = value; node.dispatchEvent(new env.window.Event('input', {bubbles: true})); };
const save = env => env.doc.querySelector('form').dispatchEvent(new env.window.Event('submit', {cancelable: true}));

test('partial scheduled work uses exact prior totals and cached next free slot in workspace timezone', async () => {
  const env = boot({items: [{id: 'busy', start_time: '11:30', estimated_minutes: 60, done: false}]});
  await env.window.PlannerWorkLog.open(task);
  assert.equal(env.doc.querySelector('[role=dialog] img'), null);
  const nums = env.doc.querySelectorAll('input[type=number]'); nums[1].value = '30'; nums[1].dispatchEvent(new env.window.Event('input'));
  assert.equal(env.doc.querySelector('input[type=checkbox]').checked, true);
  assert.equal(env.doc.querySelector('input[type=date]').value, '2026-10-05');
  assert.equal(env.doc.querySelector('input[type=time]').value, '12:30');
  assert.match(env.doc.querySelector('form').textContent, /Remaining after this entry: 1h 20m/);
  assert.equal(env.calls.length, 1);
  save(env); await settle();
  assert.deepEqual({...env.calls[1].body, request_id: 'UUID'}, {request_id:'UUID', seconds:1800,source:'manual',finish:true,split:true,remainder_date:'2026-10-05',remainder_time:'12:30'});
  assert.equal(env.saved.length, 1); env.dom.window.close();
});

test('Ignore, Escape, Back, and backdrop write no optional empty entry and restore focus/inert', async () => {
  for (const action of ['ignore', 'escape', 'back', 'backdrop']) {
    const env = boot(); await env.window.PlannerWorkLog.open(task);
    assert.equal(env.doc.querySelector('main').inert, true);
    if (action === 'ignore') [...env.doc.querySelectorAll('button')].find(n => n.textContent === 'Ignore').click();
    else if (action === 'escape') env.doc.dispatchEvent(new env.window.KeyboardEvent('keydown', {key:'Escape',bubbles:true}));
    else if (action === 'back') env.window.dispatchEvent(new env.window.PopStateEvent('popstate'));
    else env.doc.querySelector('.work-log-overlay').click();
    assert.equal(env.doc.querySelector('[role=dialog]'), null);
    assert.equal(env.doc.activeElement.id, 'origin');
    assert.equal(env.doc.querySelector('main').inert, undefined);
    assert.equal(env.calls.filter(c => c.method === 'POST').length, 0);
    assert.equal(env.window.localStorage.length, 0); env.dom.window.close();
  }
});

test('failed save persists exact UUID and payload through close/reopen and retries once', async () => {
  const env = boot({fail:true}); await env.window.PlannerWorkLog.open(task, {seconds: 1807, source:'timer'});
  save(env); await settle();
  const original = env.calls.find(c => c.method === 'POST').body;
  assert.equal(original.seconds, 1807); assert.equal(original.source, 'timer');
  assert.match(original.request_id, /^[0-9a-f-]{36}$/);
  assert.equal(env.window.localStorage.length, 1);
  env.window.PlannerWorkLog.close(); await env.window.PlannerWorkLog.open(task);
  assert.match(env.doc.querySelector('form').textContent, /Retry saved entry/);
  assert.equal(env.doc.querySelector('input[type=number]').disabled, true);
  save(env); save(env); await settle();
  assert.deepEqual(env.calls.filter(c => c.method === 'POST').map(c => c.body), [original, original]);
  assert.equal(env.window.localStorage.length, 0); assert.equal(env.saved.length, 1); env.dom.window.close();
});

test('full hours finish without split and completed tasks can log without reopening', async () => {
  for (const completed of [false, true]) {
    const env = boot({info:{task:{...task,done:completed,status:completed?'done':'todo'},planned_seconds:7200,worked_seconds:0,remaining_seconds:7200}});
    await env.window.PlannerWorkLog.open(task);
    const hours = env.doc.querySelector('input[type=number]'); hours.value = '2'; hours.dispatchEvent(new env.window.Event('input'));
    assert.equal(env.doc.querySelector('input[type=checkbox]').checked, false);
    assert.equal(env.doc.querySelector('input[type=checkbox]').disabled, true);
    save(env); await settle();
    assert.equal(env.calls[1].body.seconds, 7200); assert.equal(env.calls[1].body.split, false);
    assert.equal(env.calls[1].body.finish, true); env.dom.window.close();
  }
});

test('empty fields allow an explicit zero save but never fabricate planned time', async () => {
  const env = boot({info:{task:{...task,start_time:null}}}); await env.window.PlannerWorkLog.open(task);
  save(env); await settle(); assert.equal(env.calls[1].body.seconds, 0); assert.equal(env.calls[1].body.split, false); env.dom.window.close();
});

test('04:00 logical cutoff uses workspace date rather than selected date or device date', async () => {
  const env = boot();
  const NativeDate = env.window.Date;
  env.window.Date = class extends NativeDate { constructor(...args) { super(...(args.length ? args : ['2026-10-04T20:00:00Z'])); } };
  await env.window.PlannerWorkLog.open(task, {seconds:1800});
  assert.equal(env.doc.querySelector('input[type=date]').value, '2026-10-05');
  assert.equal(env.doc.querySelector('input[type=time]').value, '01:30'); env.dom.window.close();
});

test('split root requires choosing a block and fetches exact block totals', async () => {
  const env = boot({info:{blocks:[{...task,id:'child',title:'First session'}]}});
  env.window.PlannerWorkLog.configure({api:async (method,path,body) => {
    env.calls.push({method,path,body});
    return {data:{task:{...task,id:path.includes('child')?'child':'one'},blocks:path.includes('child')?[]:[{...task,id:'child',title:'First session'}],planned_seconds:3600,worked_seconds:300,remaining_seconds:3300}};
  }});
  await env.window.PlannerWorkLog.open(task);
  assert.equal(env.doc.querySelector('[type=submit]').disabled, true);
  const select = env.doc.querySelector('select'); select.value='child'; select.dispatchEvent(new env.window.Event('change')); await settle();
  assert.equal(env.doc.querySelector('[type=submit]').disabled, false);
  save(env); await settle(); assert.match(env.calls.at(-1).path,/child\/work$/); env.dom.window.close();
});


test('explicit 400 rolls back pending request and allows correcting the entry', async () => {
  const env = boot(); let reject = true;
  env.window.PlannerWorkLog.configure({api: async (method, path, body) => {
    env.calls.push({method,path,body:body && JSON.parse(JSON.stringify(body))});
    if (method === 'POST') { if (reject) { reject=false; const error=new Error('Choose a different remainder');error.status=400;throw error; } return {success:true}; }
    return {data:{task,blocks:[],planned_seconds:7200,worked_seconds:0,remaining_seconds:7200}};
  }});
  await env.window.PlannerWorkLog.open(task,{seconds:1800});save(env);await settle();
  assert.equal(env.window.localStorage.length,0);
  assert.equal(env.doc.querySelector('input[type=number]').disabled,false);
  const minutes=env.doc.querySelectorAll('input[type=number]')[1];minutes.value='40';minutes.dispatchEvent(new env.window.Event('input'));
  save(env);await settle();
  const posts=env.calls.filter(c=>c.method==='POST');
  assert.equal(posts[1].body.seconds,2400);assert.notEqual(posts[0].body.request_id,posts[1].body.request_id);env.dom.window.close();
});

test('next calendar day spillover tasks occupy their logical day free slots', async () => {
  const env=boot({items:[{id:'spill',start_time:'01:30',scheduled_date:'2026-10-05',estimated_minutes:30,done:false}]});
  env.window.PlannerWorkLog.configure({getContext:()=>({date:'2026-10-04',tz:'Asia/Kolkata',items:[{id:'spill',start_time:'01:30',scheduled_date:'2026-10-05',estimated_minutes:30,done:false}]})});
  const NativeDate=env.window.Date;env.window.Date=class extends NativeDate {constructor(...args){super(...(args.length?args:['2026-10-04T20:00:00Z']));}};
  await env.window.PlannerWorkLog.open(task,{seconds:1800});
  assert.equal(env.doc.querySelector('input[type=date]').value,'2026-10-05');
  assert.equal(env.doc.querySelector('input[type=time]').value,'02:00');
  assert.equal([...env.doc.querySelectorAll('.work-log-help')].at(-1).textContent.includes('not loaded'),false);env.dom.window.close();
});
