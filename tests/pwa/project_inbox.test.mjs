import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {boot,settle,task,today} from './harness.mjs';
const projects=[{id:'germany',name:'Germany',status:'active'},{id:'life',name:'Life other than Germany',status:'active'}];
const envelope=data=>({success:true,data});
function fixture(items,inbox=items){return ({method,path})=>{
 if(method==='GET'&&path.startsWith('/v2/day/planning-context'))return envelope({projects,items,timezone:'Asia/Kolkata',date:today()});
 if(method==='GET'&&path.startsWith('/v2/day/inbox'))return envelope({items:inbox,timezone:'Asia/Kolkata',date:today()});
};}
const draft=(id,project_id,title)=>task({id,project_id,title,start_time:null,scheduled_date:null});

test('project selector filters suggestions locally and list viewport fits at most six rows',async t=>{
 const items=[...Array.from({length:9},(_,i)=>draft(`g${i}`,'germany',`Study ${i}`)),draft('life-task','life','Buy groceries')];
 const page=await boot({onRequest:fixture(items)});t.after(page.close);
 page.doc.getElementById('fab').click();
 assert.equal(page.doc.querySelectorAll('.task-suggestion').length,9);
 const before=page.calls.length,input=page.doc.getElementById('new-title');
 input.value='Study 2';input.dispatchEvent(new page.window.Event('input'));
 assert.equal(page.doc.querySelectorAll('.task-suggestion').length,1);assert.equal(page.calls.length,before);
 page.doc.querySelectorAll('#sheet-projects button')[1].click();
 input.value='';input.dispatchEvent(new page.window.Event('input'));
 assert.match(page.doc.querySelector('.task-suggestion').textContent,/groceries/);assert.equal(page.calls.length,before);
 const css=readFileSync(new URL('../../planner_api/static/pwa/project-inbox.css',import.meta.url),'utf8');
 assert.match(css,/max-height:264px;overflow-y:auto/);assert.match(css,/height:44px/);
});

test('choosing an existing unscheduled task outside the selected day saves its identity with PATCH and preserves metadata',async t=>{
 const item=draft('existing','germany','Study German');item.notes='Keep original notes';item.milestone_id='language-goal';
 const page=await boot({onRequest:fixture([item])});t.after(page.close);
 page.doc.getElementById('fab').click();page.doc.getElementById('new-time').value='15:30';
 page.doc.querySelector('.task-suggestion').click();
 assert.equal(page.doc.getElementById('sheet-title').textContent,'Edit task');
 assert.equal(page.doc.getElementById('new-time').value,'15:30');
 page.doc.getElementById('sheet-save').click();await settle(page.window);
 const write=page.calls.find(c=>c.method==='PATCH');assert.equal(write.path,'/v2/day/tasks/existing');
 assert.equal('project_id' in write.body,false);assert.equal(write.body.start_time,'15:30');
 assert.equal(page.calls.filter(c=>c.method==='POST').length,0);
 const saved=page.window.PlannerProjects.find('existing');assert.equal(saved.notes,'Keep original notes');assert.equal(saved.milestone_id,'language-goal');
});

test('suggestions support keyboard navigation and changing project detaches the previous milestone locally',async t=>{
 const first={...draft('first','germany','Read A'),milestone_id:'old-link'},second=draft('second','germany','Read B');
 const page=await boot({onRequest:fixture([first,second])});t.after(page.close);
 page.doc.getElementById('fab').click();const input=page.doc.getElementById('new-title');
 input.dispatchEvent(new page.window.KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
 assert.equal(page.doc.activeElement,page.doc.querySelector('.task-suggestion'));
 page.doc.activeElement.dispatchEvent(new page.window.KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
 assert.match(page.doc.activeElement.textContent,/Read B/);
 page.doc.activeElement.dispatchEvent(new page.window.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert.equal(page.doc.activeElement,input);
 input.dispatchEvent(new page.window.Event('input'));page.doc.querySelector('.task-suggestion').click();
 page.doc.querySelectorAll('#sheet-projects button')[1].click();page.doc.getElementById('sheet-save').click();await settle(page.window);
 assert.equal(page.calls.find(c=>c.method==='PATCH').body.project_id,'life');
 assert.equal(page.window.PlannerProjects.find('first').milestone_id,null);
});

test('full Inbox includes workspace backlog, overdue and future unscheduled tasks and filters by project',async t=>{
 const future={...draft('future','germany','Future maths'),scheduled_date:'2099-01-01'};
 const overdue=task({id:'late',project_id:'germany',title:'Missed internship',overdue:true,scheduled_date:'2000-01-01'});
 const life=draft('misc','life','Buy groceries');
 const page=await boot({onRequest:fixture([future,life],[overdue,life])});t.after(page.close);
 page.doc.getElementById('inbox-view-toggle').click();
 assert.equal(page.doc.getElementById('project-inbox').classList.contains('hidden'),false);
 assert.equal(page.doc.querySelectorAll('.project-inbox-row').length,2);
 assert.match(page.doc.querySelector('.inbox-overdue').textContent,/Overdue/);
 const before=page.calls.length;page.doc.querySelectorAll('#inbox-projects button')[1].click();
 assert.equal(page.doc.querySelectorAll('.project-inbox-row').length,1);assert.match(page.doc.querySelector('.project-inbox-row').textContent,/groceries/);assert.equal(page.calls.length,before);
 page.doc.querySelector('.project-inbox-row .ring').click();await settle(page.window);
 assert.equal(page.calls.find(c=>c.method==='PATCH').path,'/v2/day/tasks/misc');assert.equal(page.doc.querySelectorAll('.project-inbox-row').length,0);
});

test('a failed save of an external suggestion restores the backlog and removes its optimistic day entry',async t=>{
 const handler=fixture([draft('outside','germany','Study outside')]);
 const page=await boot({onRequest:request=>request.method==='PATCH'?{__status:400,detail:{message:'Failed'}}:handler(request)});t.after(page.close);
 page.doc.getElementById('fab').click();page.doc.querySelector('.task-suggestion').click();page.doc.getElementById('new-time').value='15:00';
 page.doc.getElementById('sheet-save').click();await settle(page.window);
 assert.equal(page.doc.querySelectorAll('#list .row').length,0);
 assert.equal(page.window.PlannerProjects.find('outside').start_time,null);
});

function memoryStorage(){const values=new Map();return {values,getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value)};}
async function pureStore(t,options){const page=await boot();t.after(page.close);return page.window.PlannerProjects.createStore(options);}

test('scoped persisted context paints stale tasks before a pending refresh and never stores raw app keys',async t=>{
 const storage=memoryStorage(),item=draft('cached','germany','Cached task');
 let pending=false,calls=0;
 const options={getKey:()=> 'connection-secret',fingerprint:async()=> 'digest',storage,api:async(_,path)=>{calls++;if(pending)return new Promise(()=>{});return envelope(path.includes('planning-context')?{projects,items:[item]}:{items:[item]});}};
 const first=await pureStore(t,options);await first.refresh(today());
 assert.equal([...storage.values.keys()].some(k=>k.includes('connection-secret')),false);
 pending=true;const second=await pureStore(t,options);const refresh=second.refresh(today(),{force:true});await new Promise(r=>setTimeout(r,0));
 assert.equal(second.suggestions('germany','Cached')[0].id,'cached');assert.equal(calls,4);void refresh;
});

test('a slow refresh does not resurrect a task completed while the request was running',async t=>{
 let slow=false,resolveContext,resolveInbox;
 const item=draft('race','germany','Finish me');
 const store=await pureStore(t,{getKey:()=> 'key',fingerprint:async()=> 'race',storage:memoryStorage(),api:async(_,path)=>{
  if(slow)return new Promise(resolve=>{if(path.includes('planning-context'))resolveContext=resolve;else resolveInbox=resolve;});
  return envelope(path.includes('planning-context')?{projects,items:[item]}:{items:[item]});
 }});
 await store.refresh(today());slow=true;const fresh=store.refresh(today(),{force:true});await new Promise(r=>setTimeout(r,0));
 const mutation=store.begin('race',{done:true});store.finish(mutation,true);
 resolveContext(envelope({projects,items:[item]}));resolveInbox(envelope({items:[item]}));await fresh;
 assert.equal(store.suggestions('germany').length,0);assert.equal(store.backlog('germany').length,0);
});

test('account changes discard the previous cache and ignore its late response',async t=>{
 let key='first',slow=false,resolveContext,resolveInbox;
 const storage=memoryStorage(),item=draft('private','germany','First account');
 const store=await pureStore(t,{getKey:()=>key,fingerprint:async k=>k+'-digest',storage,api:async(_,path)=>{
 if(slow)return new Promise(resolve=>{if(path.includes('planning-context'))resolveContext=resolve;else resolveInbox=resolve;});
 return envelope(path.includes('planning-context')?{projects,items:[item]}:{items:[item]});
 }});
 await store.refresh(today());slow=true;const stale=store.refresh(today(),{force:true});await new Promise(r=>setTimeout(r,0));
 key='second';await store.scope();assert.equal(store.suggestions('germany').length,0);
 resolveContext(envelope({projects,items:[item]}));resolveInbox(envelope({items:[item]}));await stale;
 assert.equal(store.snapshot().items.length,0);assert.equal(store.snapshot().inbox.length,0);
});

test('background project refresh preserves a typed task draft and selected project',async t=>{
 const page=await boot({onRequest:fixture([draft('one','germany','Existing')])});t.after(page.close);
 page.doc.getElementById('fab').click();page.doc.querySelectorAll('#sheet-projects button')[1].click();
 page.doc.getElementById('new-title').value='My unsaved idea';page.doc.getElementById('new-time').value='16:15';
 await page.window.PlannerProjects.refresh({force:true});
 assert.equal(page.doc.getElementById('new-title').value,'My unsaved idea');assert.equal(page.doc.getElementById('new-time').value,'16:15');
 assert.equal(page.doc.querySelector('#sheet-projects button[aria-pressed="true"]').textContent,'Life other than Germany');
});

test('opening Inbox and editors repeatedly reuses fresh context and normal creation inserts the returned task without refetch',async t=>{
 const handler=fixture([]);
 const page=await boot({onRequest:request=>request.method==='POST'&&request.path==='/v2/day/tasks'?envelope({task:draft('created','life',request.body.title)}):handler(request)});t.after(page.close);
 const reads=()=>page.calls.filter(c=>c.method==='GET'&&/planning-context|\/inbox/.test(c.path)).length;
 assert.equal(reads(),2);
 page.doc.getElementById('inbox-view-toggle').click();await settle(page.window);
 page.doc.getElementById('inbox-view-toggle').click();page.doc.getElementById('fab').click();await settle(page.window);
 assert.equal(reads(),2);
 page.doc.querySelectorAll('#sheet-projects button')[1].click();page.doc.getElementById('new-title').value='New life task';
 page.doc.getElementById('sheet-save').click();await settle(page.window);
 assert.equal(reads(),2);assert.equal(page.window.PlannerProjects.find('created').title,'New life task');
 assert.equal(page.calls.find(c=>c.method==='POST').body.project_id,'life');
 await page.window.PlannerProjects.refresh({force:true});assert.equal(reads(),4);
});

test('fresh persisted context avoids GETs until its ten-minute TTL or selected date expires',async t=>{
 const storage=memoryStorage();let calls=0;
 const options={getKey:()=> 'cache-key',fingerprint:async()=> 'ttl',storage,api:async(_,path)=>{calls++;return envelope(path.includes('planning-context')?{projects,items:[]}:{items:[]});}};
 const first=await pureStore(t,options);await first.refresh(today());assert.equal(calls,2);
 const second=await pureStore(t,options);await second.refresh(today());assert.equal(calls,2);
 const cacheKey=[...storage.values.keys()][0],saved=JSON.parse(storage.values.get(cacheKey));saved.refreshedAt=Date.now()-600001;storage.setItem(cacheKey,JSON.stringify(saved));
 const third=await pureStore(t,options);await third.refresh(today());assert.equal(calls,4);
 await third.refresh('2099-01-01');assert.equal(calls,6);
});

test('old Study project references resolve to Germany without detaching the existing milestone',async t=>{
 const item=task({id:'old-day',project_id:'old-study',title:'Study cached',milestone_id:'keep-link'});
 const context={projects,items:[],project_aliases:{'old-study':'germany'}};
 const page=await boot({items:[item],onRequest:({path})=>path.includes('planning-context')?envelope(context):path.includes('/inbox')?envelope({items:[]}):null});t.after(page.close);
 page.doc.querySelector('#list .row').click();
 assert.equal(page.doc.querySelector('#sheet-projects [aria-pressed="true"]').textContent,'Germany');
 page.doc.getElementById('sheet-save').click();await settle(page.window);
 assert.equal(page.calls.find(c=>c.method==='PATCH').body.project_id,'germany');
 assert.equal(page.window.PlannerProjects.find('old-day').milestone_id,'keep-link');
});

test('an unknown stale task project is omitted from PATCH unless the user explicitly selects its replacement',async t=>{
 const item=task({id:'unknown-day',project_id:'unresolved-old-project',title:'Cached task',milestone_id:'keep-link'});
 const page=await boot({items:[item],onRequest:fixture([])});t.after(page.close);
 page.doc.querySelector('#list .row').click();page.doc.getElementById('sheet-save').click();await settle(page.window);
 assert.equal('project_id' in page.calls.find(c=>c.method==='PATCH').body,false);
 page.doc.querySelector('#list .row').click();page.doc.querySelectorAll('#sheet-projects button')[1].click();page.doc.getElementById('sheet-save').click();await settle(page.window);
 assert.equal(page.calls.filter(c=>c.method==='PATCH')[1].body.project_id,'life');
});
