import {test} from "node:test";
import assert from "node:assert/strict";
import {boot,settle} from "./harness.mjs";

const endpoint="https://web.push.apple.com/test-device";
function pushBrowser({subscribed=true}={}) {
  return w=>{
    let sub=subscribed?{toJSON:()=>({endpoint,keys:{p256dh:"key",auth:"auth"}})}:null;
    const reg={update:async()=>{},pushManager:{
      getSubscription:async()=>sub,
      subscribe:async()=>sub={toJSON:()=>({endpoint,keys:{p256dh:"key",auth:"auth"}})},
    }};
    Object.defineProperty(w.navigator,"serviceWorker",{value:{ready:Promise.resolve(reg),register:async()=>reg,addEventListener(){}}});
    w.PushManager=function(){};
    w.Notification={permission:"granted",requestPermission:async()=>"granted"};
  };
}

test("failed server registration does not show notifications as enabled",async t=>{
  const a=await boot({beforeScripts:pushBrowser(),onRequest:({path})=>path.endsWith("/subscribe")?{success:false,message:"Registration failed"}:null});
  t.after(a.close);await settle(a.window);
  const bell=a.doc.getElementById("notif-btn");
  assert.equal(bell.classList.contains("on"),false);
  assert.match(bell.title,/Reconnect/);
});

test("same-browser installations get distinct stable device identifiers",async t=>{
  const a=await boot({beforeScripts:pushBrowser()});t.after(a.close);
  const b=await boot({beforeScripts:pushBrowser()});t.after(b.close);
  await settle(a.window);await settle(b.window);
  const label=a.calls.find(c=>c.path.endsWith("/subscribe")).body.device_label;
  const other=b.calls.find(c=>c.path.endsWith("/subscribe")).body.device_label;
  assert.notEqual(label,other);
  assert.ok(label.includes(a.window.localStorage.getItem("day-planner-push-device")));
  assert.equal(a.doc.getElementById("notif-btn").classList.contains("on"),true);
});

test("failed delivery test is visible and tests only the current device",async t=>{
  const a=await boot({beforeScripts:pushBrowser({subscribed:false}),onRequest:({path})=>{
    if(path.endsWith("vapid-key"))return {success:true,data:{public_key:"AQID"}};
    if(path.endsWith("/push/test"))return {success:true,data:{sent:0,failed:1}};
    return null;
  }});t.after(a.close);
  a.doc.getElementById("notif-btn").click();await settle(a.window);
  const request=a.calls.find(c=>c.path.endsWith("/push/test"));
  assert.deepEqual(request.body,{endpoint});
  assert.match(a.doc.getElementById("toast").textContent,/could not be sent/);
  assert.equal(a.doc.getElementById("notif-btn").classList.contains("on"),false);
});
