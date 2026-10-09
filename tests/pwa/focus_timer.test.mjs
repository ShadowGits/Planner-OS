import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';
const source = readFileSync(new URL('../../planner_api/static/pwa/focus-timer.js', import.meta.url), 'utf8');
function boot(t, { time = Date.parse('2026-10-05T10:15:00Z'), saved = null, key = 'test-account' } = {}) {
  const dom = new JSDOM('<!doctype html><body></body>', { url: 'https://planner.test/pwa/', runScripts: 'outside-only' });
  t.after(() => dom.window.close());
  const w = dom.window; let clock = time, tick;
  w.Date.now = () => clock; w.confirm = () => true; w.focus = () => {};
  w.setInterval = fn => { tick = fn; return 1; };
  w.fetch = () => { throw new Error('Timer must never call the API'); };
  if (saved) for (const [k, v] of saved) w.localStorage.setItem(k, v);
  w.eval(source);
  const messages = [], finished = [];
  w.PlannerFocus.configure({ getKey: () => key, toast: message => messages.push(message), onFinish: (...args) => finished.push(args) });
  return { w, focus: w.PlannerFocus, messages, finished, advance(ms) { clock += ms; tick(); }, save: () => Object.entries(w.localStorage) };
}
const task = (extra = {}) => ({ id: 'a', title: 'Read <script>unsafe</script>', start_time: '10:00', estimated_minutes: 30, done: false, ...extra });

test('manual clock uses wall time, pauses accurately and survives reload', t => {
  const a = boot(t); a.focus.start(task({ planned_seconds: 1800, worked_seconds: 300 }));
  a.advance(61234); assert.equal(a.focus.snapshot().remaining, 1438766);
  a.focus.pause(); a.advance(300000); assert.equal(a.focus.snapshot().remaining, 1438766);
  const b = boot(t, { saved: a.save() }); assert.equal(b.focus.snapshot().status, 'paused');
  b.focus.resume(); b.advance(1000); assert.equal(b.focus.snapshot().remaining, 1437766);
  assert.equal(b.w.document.querySelector('.focus-title').textContent, task().title);
  assert.equal(b.w.document.querySelector('.focus-title script'), null);
});

test('running reload restores deadline and expiry only shows completion', t => {
  const a = boot(t); a.focus.start(task()); a.advance(60000);
  const b = boot(t, { saved: a.save(), time: Date.parse('2026-10-05T10:20:00Z') });
  assert.equal(b.focus.snapshot().remaining, 1500000);
  b.advance(1600000); assert.equal(b.focus.snapshot().status, 'complete'); assert.equal(b.finished.length, 0);
  b.focus.finish(); assert.equal(b.finished.length, 1); assert.equal(b.finished[0][1].seconds, 1800); assert.equal(b.focus.snapshot(), null);
});

test('schedule selects latest ongoing overlap and persists cancellation', t => {
  const a = boot(t);
  const items = [task({ id: 'old', start_time: '10:00', estimated_minutes: 60 }), task({ id: 'new', start_time: '10:10' })];
  a.focus.update({ items, date: '2026-10-05', tz: 'UTC' });
  assert.equal(a.focus.snapshot().task.id, 'new'); assert.equal(a.focus.snapshot().remaining, 1500000);
  a.focus.cancel(); a.advance(500); assert.equal(a.focus.snapshot(), null);
  const b = boot(t, { saved: a.save() }); b.focus.update({ items, date: '2026-10-05', tz: 'UTC' }); assert.equal(b.focus.snapshot(), null);
});

test('auto starts future schedules, skips expired and other dates', t => {
  const a = boot(t); a.focus.update({ items: [task({ start_time: '10:16' })], date: '2026-10-05', tz: 'UTC' });
  assert.equal(a.focus.snapshot(), null); a.advance(60000); assert.equal(a.focus.snapshot().remaining, 1800000);
  const b = boot(t); b.focus.update({ items: [task({ start_time: '09:00' })], date: '2026-10-05', tz: 'UTC' }); assert.equal(b.focus.snapshot(), null);
  b.focus.update({ items: [task()], date: '2026-10-04', tz: 'UTC' }); assert.equal(b.focus.snapshot(), null);
});

test('timezone and logical spillover use the scheduled day', t => {
  const a = boot(t, { time: Date.parse('2026-10-05T19:40:00Z') });
  a.focus.update({ items: [task({ start_time: '25:00' })], date: '2026-10-05', tz: 'Asia/Kolkata' });
  assert.equal(a.focus.snapshot().remaining, 1200000);
});

test('float opens real PiP synchronously and both views remain synchronized', async t => {
  const a = boot(t); const pip = new JSDOM('<!doctype html><body></body>', { url: 'https://planner.test/pwa/' }); t.after(() => pip.window.close());
  let requested = false; a.w.documentPictureInPicture = { requestWindow(options) { requested = true; assert.equal(options.width, 360); return Promise.resolve(pip.window); } };
  a.focus.start(task()); const result = a.focus.float(); assert.equal(requested, true); assert.equal(await result, true);
  a.advance(10000); assert.equal(pip.window.document.querySelector('.focus-clock').textContent, '29:50');
  pip.window.document.querySelector('.focus-button').click(); assert.equal(a.focus.snapshot().status, 'paused');
  assert.equal(a.w.document.querySelector('.focus-button').textContent, 'Resume');
});

test('unsupported browser honestly keeps timer in planner', async t => {
  const a = boot(t); a.focus.start(task()); assert.equal(await a.focus.float(), false);
  assert.match(a.messages[0], /Always-on-top.*Chrome or Edge/); assert.equal(a.focus.snapshot().status, 'running');
});

test('shared storage prevents duplicate automatic claim and synchronizes pause', t => {
  const a = boot(t); const items = [task()]; a.focus.update({ items, date: '2026-10-05', tz: 'UTC' });
  const b = boot(t, { saved: a.save() }); b.focus.update({ items, date: '2026-10-05', tz: 'UTC' });
  assert.equal(b.focus.snapshot().owner, a.focus.snapshot().owner);
  a.focus.pause(); const [key, value] = a.save()[0]; b.w.localStorage.setItem(key, value); b.w.dispatchEvent(new b.w.StorageEvent('storage', { key, newValue: value }));
  assert.equal(b.focus.snapshot().status, 'paused');
});

test('pause suppresses metadata edits and stopTask prevents an automatic restart', t => {
  const a = boot(t); a.focus.update({ items: [task()], date: '2026-10-05', tz: 'UTC' }); a.focus.pause();
  a.focus.update({ items: [task({ title: 'Renamed', estimated_minutes: 50 })], date: '2026-10-05', tz: 'UTC' });
  assert.equal(a.focus.snapshot().status, 'paused');
  a.focus.stopTask('a'); a.focus.update({ items: [task()], date: '2026-10-05', tz: 'UTC' }); assert.equal(a.focus.snapshot(), null);
});

test('account changes isolate timers and keys never contain the connection secret', t => {
  const a = boot(t, { key: 'private-token-123' }); a.focus.start(task());
  assert.equal(a.save()[0][0].includes('private-token-123'), false);
  a.focus.configure({ getKey: () => 'different-account' }); assert.equal(a.focus.snapshot(), null);
  a.focus.configure({ getKey: () => 'private-token-123' }); assert.equal(a.focus.snapshot().task.id, 'a');
  a.focus.configure({ getKey: () => null }); assert.equal(a.focus.start(task()), false); assert.equal(a.focus.snapshot(), null);
});

test('scheduled slot keeps its planned end after partial work', t => {
  const a = boot(t); a.focus.update({ items: [task({ planned_seconds: 1800, worked_seconds: 1200 })], date: '2026-10-05', tz: 'UTC' });
  assert.equal(a.focus.snapshot().remaining, 900000);
});

test('manual focus suppresses ongoing schedules while future blocks still start', t => {
  const a = boot(t); const items = [task(), task({ id: 'later', start_time: '10:17' })];
  a.focus.update({ items, date: '2026-10-05', tz: 'UTC' });
  a.focus.start(task({ id: 'inbox', start_time: null })); a.advance(500);
  assert.equal(a.focus.snapshot().task.id, 'inbox');
  a.focus.pause(); a.advance(60000); assert.equal(a.focus.snapshot().status, 'paused');
  a.advance(60000); assert.equal(a.focus.snapshot().task.id, 'later');
});

test('logical previous day is unavailable at the four oclock cutoff', t => {
  const a = boot(t, { time: Date.parse('2026-10-06T04:10:00Z') });
  a.focus.update({ items: [task({ start_time: '28:00' })], date: '2026-10-05', tz: 'UTC' }); assert.equal(a.focus.snapshot(), null);
});

test('malformed saved clocks are ignored safely', t => {
  const a = boot(t); a.focus.start(task()); const [key, value] = a.save()[0];
  const saved = JSON.parse(value); saved.current.duration = 'NaN'; saved.consumed = [null, 42];
  const b = boot(t, { saved: [[key, JSON.stringify(saved)]] }); assert.equal(b.focus.snapshot(), null);
  assert.equal(b.focus.start(task()), true);
});

test('Float unlocks audio without replaying the start tone', async t => {
  const a = boot(t); const pip = new JSDOM('<!doctype html><body></body>'); t.after(() => pip.window.close());
  let oscillators = 0;
  a.w.AudioContext = class {
    state = 'running'; currentTime = 0;
    resume() { return Promise.resolve(); }
    createOscillator() { oscillators++; return { frequency: {}, connect() {}, start() {}, stop() {} }; }
    createGain() { return { gain: { setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} }; }
  };
  a.w.documentPictureInPicture = { requestWindow: () => Promise.resolve(pip.window) };
  a.focus.start(task()); await Promise.resolve(); assert.equal(oscillators, 3);
  await a.focus.float(); assert.equal(oscillators, 3);
});

test('square dial perimeter shrinks and compact footer expands accessibly', t => {
  const a = boot(t); a.focus.start(task());
  const dial = a.w.document.querySelector('.focus-dial'); const progress = dial.querySelector('.focus-fill');
  assert.equal(progress.tagName, 'rect'); assert.equal(progress.getAttribute('pathLength'), '100');
  assert.equal(progress.style.strokeDashoffset, '0'); a.advance(900000); assert.equal(progress.style.strokeDashoffset, '50');
  const toggle = a.w.document.querySelector('.focus-minimize'); assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  toggle.click(); assert.equal(toggle.getAttribute('aria-expanded'), 'true'); assert.equal(toggle.textContent, 'Minimize');
});

test('rendered Float button invokes PiP from a DOM click', async t => {
  const a = boot(t); const pip = new JSDOM('<!doctype html><body></body>'); t.after(() => pip.window.close());
  let requested = false; a.w.documentPictureInPicture = { requestWindow() { requested = true; return Promise.resolve(pip.window); } };
  a.focus.start(task()); const button = [...a.w.document.querySelectorAll('.focus-button')].find(b => b.textContent.startsWith('Float timer'));
  button.click(); assert.equal(requested, true); await new Promise(resolve => setImmediate(resolve)); assert.equal(button.textContent, 'Timer is floating ↗');
});

test('rendered Float button reports unsupported browser from a DOM click', t => {
  const a = boot(t); a.focus.start(task());
  [...a.w.document.querySelectorAll('.focus-button')].find(b => b.textContent.startsWith('Float timer')).click();
  assert.equal(a.messages.length, 1); assert.match(a.messages[0], /Always-on-top/);
  const notice = a.w.document.querySelector('.focus-notice'); assert.equal(notice.hidden, false); assert.match(notice.textContent, /Chrome or Edge/);
});

test('same-task Play preserves running and paused elapsed time', t => {
  const a = boot(t); a.focus.start(task()); a.advance(60000); const deadline = a.focus.snapshot().deadline;
  a.focus.start(task()); assert.equal(a.focus.snapshot().deadline, deadline); assert.equal(a.focus.snapshot().remaining, 1740000);
  a.focus.pause(); a.advance(60000); a.focus.start(task()); assert.equal(a.focus.snapshot().status, 'paused'); assert.equal(a.focus.snapshot().remaining, 1740000);
});

test('declining focus switch preserves the current session', t => {
  const a = boot(t); a.focus.start(task()); a.advance(60000); a.w.confirm = () => false;
  assert.equal(a.focus.start(task({ id: 'different' })), false); assert.equal(a.focus.snapshot().task.id, 'a'); assert.equal(a.focus.snapshot().remaining, 1740000);
  a.focus.pause(); assert.equal(a.focus.start(task({ id: 'different' })), false); assert.equal(a.focus.snapshot().status, 'paused');
});

test('cancel, reset and stopTask close existing floating windows', async t => {
  for (const stop of [focus => focus.cancel(), focus => focus.reset(), focus => focus.stopTask('a')]) {
    const a = boot(t); const pip = new JSDOM('<!doctype html><body></body>'); t.after(() => pip.window.close());
    let closed = 0; pip.window.close = () => { closed++; };
    a.w.documentPictureInPicture = { requestWindow: () => Promise.resolve(pip.window) }; a.focus.start(task()); await a.focus.float();
    stop(a.focus); assert.equal(closed, 1); assert.equal(a.focus.snapshot(), null);
  }
});

test('cancel while PiP is opening closes the eventual window without mounting', async t => {
  const a = boot(t); const pip = new JSDOM('<!doctype html><body></body>'); t.after(() => pip.window.close());
  let resolve, closed = 0; pip.window.close = () => { closed++; };
  a.w.documentPictureInPicture = { requestWindow: () => new Promise(done => { resolve = done; }) };
  a.focus.start(task()); const opening = a.focus.float(); a.focus.cancel(); resolve(pip.window);
  assert.equal(await opening, false); assert.equal(closed, 1); assert.equal(pip.window.document.querySelector('.focus-timer'), null);
});

test('Finish closes PiP, focuses planner and excludes paused time', async t => {
  const a = boot(t); const pip = new JSDOM('<!doctype html><body></body>'); t.after(() => pip.window.close());
  let closed = false, focused = false; pip.window.close = () => { closed = true; }; a.w.focus = () => { focused = true; };
  a.w.documentPictureInPicture = { requestWindow: () => Promise.resolve(pip.window) };
  a.focus.start(task()); await a.focus.float(); a.advance(60000); a.focus.pause(); a.advance(300000); a.focus.finish();
  assert.equal(closed, true); assert.equal(focused, true); assert.equal(a.finished[0][1].seconds, 60);
});

test('browsing future dates preserves today’s loaded automatic schedule', t => {
  const a = boot(t); a.focus.update({ items: [task({ start_time: '10:16' })], date: '2026-10-05', tz: 'UTC' });
  a.focus.update({ items: [], date: '2026-10-06', tz: 'UTC' }); a.advance(60000);
  assert.equal(a.focus.snapshot().task.id, 'a');
});

test('early-hours future calendar view preserves the previous logical day', t => {
  const a = boot(t, { time: Date.parse('2026-10-06T01:10:00Z') });
  a.focus.update({ items: [task({ start_time: '25:11' })], date: '2026-10-05', tz: 'UTC' });
  a.focus.update({ items: [], date: '2026-10-06', tz: 'UTC' }); a.advance(60000);
  assert.equal(a.focus.snapshot().task.id, 'a');
});

test('Float transfers restored session audio ownership without a start tone', async t => {
  const a = boot(t); a.focus.start(task()); const previous = a.focus.snapshot().owner;
  const b = boot(t, { saved: a.save() }); let tones = 0;
  b.w.AudioContext = class {
    state = 'running'; currentTime = 0;
    resume() { return Promise.resolve(); }
    createOscillator() { tones++; return { frequency: {}, connect() {}, start() {}, stop() {} }; }
    createGain() { return { gain: { setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} }; }
  };
  await b.focus.float(); assert.notEqual(b.focus.snapshot().owner, previous); assert.equal(tones, 0);
  b.advance(1800000); await Promise.resolve(); assert.equal(tones, 3);
});

test('master off cancels the active clock and blocks manual, scheduled, resume and finish actions across reload', t => {
  const a=boot(t); a.focus.start(task()); a.advance(60000); a.focus.pause();
  assert.equal(a.focus.setEnabled(false),true);
  assert.equal(a.focus.snapshot(),null);
  assert.equal(a.w.document.querySelector('.focus-timer').hidden,true);
  assert.equal(a.w.document.body.classList.contains('time-tracking-off'),true);
  a.focus.resume(); a.focus.finish(); assert.equal(a.finished.length,0);
  assert.equal(a.focus.start(task()),false);
  a.focus.update({items:[task(),task({id:'future',start_time:'10:30'})],date:'2026-10-05',tz:'UTC'});
  a.advance(20*60000); assert.equal(a.focus.snapshot(),null);
  const b=boot(t,{saved:a.save()});
  assert.equal(b.focus.enabled(),false); assert.equal(b.focus.start(task()),false);
  assert.equal(b.focus.setEnabled(true),true);
  assert.equal(b.focus.snapshot(),null);
  assert.equal(b.focus.start(task()),true);
});

test('master off from another tab dismisses tracking and cannot restore a stale timer', t => {
  const a=boot(t); a.focus.start(task()); const state=a.save().find(([k])=>k.startsWith('planner-focus-v1:'));
  a.w.localStorage.setItem('planner-time-tracking-enabled','false');
  a.w.dispatchEvent(new a.w.StorageEvent('storage',{key:'planner-time-tracking-enabled',newValue:'false'}));
  a.w.localStorage.setItem(...state);
  a.w.dispatchEvent(new a.w.StorageEvent('storage',{key:state[0],newValue:state[1]}));
  a.advance(60000); assert.equal(a.focus.snapshot(),null);
  assert.equal(a.w.document.querySelector('.focus-timer').hidden,true);
});

test('switching off closes a floating window that resolves after cancellation', async t => {
  const a=boot(t); a.focus.start(task()); let resolve,closed=0;
  a.w.documentPictureInPicture={requestWindow:()=>new Promise(r=>{resolve=r})};
  const opening=a.focus.float(); a.focus.setEnabled(false);
  resolve({close(){closed++}});
  assert.equal(await opening,false); assert.equal(closed,1);
  assert.equal(a.focus.snapshot(),null);
});

test('re-enabling tracking leaves the current scheduled occurrence stopped but permits future blocks', t => {
  const a=boot(t); a.focus.update({items:[task(),task({id:'future',start_time:'10:30'})],date:'2026-10-05',tz:'UTC'});
  assert.equal(a.focus.snapshot().task.id,'a');
  a.focus.setEnabled(false); a.focus.setEnabled(true); a.advance(1000);
  assert.equal(a.focus.snapshot(),null);
  a.advance(15*60000); assert.equal(a.focus.snapshot().task.id,'future');
});
