import {test} from "node:test";
import assert from "node:assert/strict";
import {boot,settle,task,rowFor} from "./harness.mjs";

test("day list includes scheduled and unscheduled tasks, retains wins, and toggles without a fetch",async t=>{
 const page=await boot({items:[task({id:"a",title:"Read",starred:true}),task({id:"b",title:"Write",start_time:null}),task({id:"c",title:"Done",done:true})]});t.after(page.close);
 const before=page.calls.length;
 page.doc.getElementById("view-toggle").click();
 const rows=[...page.doc.querySelectorAll(".todo-row")];
 assert.equal(rows.length,3);assert.deepEqual(rows.map(r=>r._task.title),["Read","Write","Done"]);
 assert.equal(page.doc.getElementById("view-toggle").getAttribute("aria-label"),"Show timeline");
 assert.equal(page.doc.getElementById("view-toggle").getAttribute("aria-pressed"),"true");
 assert.match(page.doc.getElementById("wins").textContent,/Read/);
 assert.match(rows[1].textContent,/Unscheduled/);
 assert.equal(page.calls.length,before);
 assert.equal(page.window.localStorage.getItem("day-planner-todo-view"),"true");
 page.doc.getElementById("view-toggle").click();
 assert.ok(page.doc.querySelector(".spine"));assert.equal(page.calls.length,before);
});

test("list checkbox saves immediately with no full-day reload and editing is retained",async t=>{
 const page=await boot({items:[task({id:"a",title:"Read"})]});t.after(page.close);
 page.doc.getElementById("view-toggle").click();const row=page.doc.querySelector(".todo-row");
 const before=page.calls.filter(c=>c.method==="GET").length;
 row.querySelector(".ring").click();await settle(page.window);
 assert.ok(row.classList.contains("done"));assert.deepEqual(page.calls.find(c=>c.method==="PATCH").body,{done:true});
 assert.equal(page.calls.filter(c=>c.method==="GET").length,before);
 row.querySelector(".todo-details").click();assert.equal(page.doc.getElementById("new-title").value,"Read");
});

test("general split is a single retry-safe request and retains its request ID on lost response",async t=>{
 let fail=true;
 const page=await boot({items:[task({id:"a",title:"Read",estimated_minutes:120,planned_seconds:7200,worked_seconds:1800})],
 onRequest:({method,path})=>method==="POST"&&path.endsWith("/split")&&fail?{__status:503,detail:{message:"Retry"}}:null});t.after(page.close);
 rowFor(page.doc,"Read").click();page.doc.getElementById("sheet-split").click();await settle(page.window);
 fail=false;page.doc.getElementById("sheet-split").click();await settle(page.window);
 const requests=page.calls.filter(c=>c.method==="POST");assert.equal(requests.length,2);
 assert.equal(requests[0].path,"/v2/day/tasks/a/split");assert.deepEqual(requests[0].body,requests[1].body);
 assert.equal(requests[0].body.expected_remaining,5400);assert.equal(requests[0].body.first_seconds,2700);
 assert.ok(![...Array(page.window.localStorage.length)].map((_,i)=>page.window.localStorage.key(i)).some(k=>k.includes("test-key")));
});


test("list timer controls use local state and explicit Finish opens an optional entry",async t=>{
 const item=task({id:"timer-one",title:"Focus now",start_time:null});
 const page=await boot({items:[item],onRequest:({method,path})=>method==="GET"&&path.endsWith("/work")?{success:true,data:{task:item,blocks:[],sessions:[],planned_seconds:1800,worked_seconds:0,remaining_seconds:1800,timezone:"Asia/Kolkata"}}:null});t.after(page.close);
 page.doc.getElementById("view-toggle").click();const before=page.calls.length;
 page.doc.querySelector(".todo-row .task-focus").click();
 assert.equal(page.window.PlannerFocus.snapshot().task.id,"timer-one");assert.equal(page.calls.length,before);
 const buttons=[...page.doc.querySelectorAll(".focus-timer button")];buttons.find(b=>b.textContent==="Expand").click();buttons.find(b=>b.textContent==="Pause").click();
 assert.equal(page.window.PlannerFocus.snapshot().status,"paused");assert.equal(page.calls.length,before);
 buttons.find(b=>b.textContent==="Finish").click();await settle(page.window);
 assert.ok(page.doc.querySelector(".work-log-dialog"));
 [...page.doc.querySelectorAll(".work-log-dialog button")].find(b=>b.textContent==="Ignore").click();
 assert.equal(page.calls.filter(c=>c.method==="POST").length,0);
});


test("Top Win jumps to unscheduled task in calendar view and done tasks hide timer",async t=>{
 const page=await boot({items:[task({id:"todo",title:"Send form",start_time:null,starred:true})]});t.after(page.close);
 const card=page.doc.querySelector(".inbox-card");let revealed=false;card.scrollIntoView=()=>{revealed=true};
 page.doc.querySelector(".win-chip").click();assert.equal(revealed,true);
 page.doc.getElementById("view-toggle").click();const row=page.doc.querySelector(".todo-row");row.querySelector(".ring").click();await settle(page.window);
 assert.equal(row.querySelector(".task-focus").hidden,true);
});
