import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const source=readFileSync(new URL('../../planner_api/static/pwa/sw.js',import.meta.url),'utf8');
function worker({offline=false}={}) {
 const handlers={}; const matches=[]; const puts=[]; const opened=[];
 runInNewContext(source,{
  URL,
  self:{registration:{scope:'https://planner.test/app/'},addEventListener:(name,fn)=>handlers[name]=fn,
   clients:{matchAll:async()=>[],openWindow:async url=>opened.push(url)},skipWaiting(){}},
  fetch:async()=>{if(offline)throw new Error('offline');return {ok:true,clone:()=>({shell:true})};},
  caches:{open:async()=>({put:async(key)=>puts.push(key)}),match:async key=>{matches.push(key);return {cached:true};}},
 });
 return {handlers,matches,puts,opened};
}

test('the worker ignores authenticated pages, APIs and external requests',()=>{
 const {handlers}=worker();
 for(const url of ['https://planner.test/v2/day','https://planner.test/oauth/callback','https://other.test/app/app.js','https://planner.test/app/private.json']) {
  let intercepted=false;
  handlers.fetch({request:{method:'GET',url},respondWith:()=>intercepted=true});
  assert.equal(intercepted,false,url);
 }
});

test('versioned shell requests fall back to the installed offline cache',async()=>{
 const {handlers,matches}=worker({offline:true});
 let response;
 handlers.fetch({request:{method:'GET',url:'https://planner.test/app/app.js?v=11'},respondWith:p=>response=p});
 assert.deepEqual(await response,{cached:true});
 assert.deepEqual(matches,['https://planner.test/app/app.js']);
});

test('notification links stay within the app origin and scope',async()=>{
 for(const [url,expected] of [['https://evil.test/','https://planner.test/app/'],['/oauth/authorize','https://planner.test/app/'],['/app/?task=123','https://planner.test/app/?task=123']]) {
  const {handlers,opened}=worker();let done;
  handlers.notificationclick({notification:{close(){},data:{url}},waitUntil:p=>done=p});
  await done;
  assert.deepEqual(opened,[expected]);
 }
});
