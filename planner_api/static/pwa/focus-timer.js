/* Local focus clock. No network requests; wall-clock deadlines survive reloads. */
(() => {
  'use strict';
  const VERSION = 1;
  const stylesheet = new URL('focus-timer.css', document.currentScript?.src || new URL('focus-timer.js', location.href)).href;
  const owner = Math.random().toString(36).slice(2);
  let config = {}, key = null, current = null, consumed = [], blocks = [];
  let pip = null, opening = false, audio = null, timer = null, floatingNotice = '', floatingEpoch = 0;
  const views = new Set();
  const now = () => Date.now();
  const hash = value => {
    let a = 2166136261, b = 5381;
    for (const c of String(value)) { a = Math.imul(a ^ c.charCodeAt(0), 16777619); b = Math.imul(b, 33) ^ c.charCodeAt(0); }
    return `${(a >>> 0).toString(16)}${(b >>> 0).toString(16)}`;
  };
  const notify = message => { if (config.toast) config.toast(message); else console.info(message); };
  function read() {
    try {
      const saved = JSON.parse(localStorage.getItem(key));
      current = null; consumed = [];
      if (saved?.version === VERSION) {
        const c = saved.current;
        if (c && typeof c.task?.id === 'string' && c.task.id && typeof c.task.title === 'string' &&
            ['running', 'paused', 'complete'].includes(c.status) &&
            Number.isFinite(c.duration) && c.duration > 0 &&
            Number.isFinite(c.remaining) && c.remaining >= 0 && c.remaining <= c.duration &&
            Number.isFinite(c.deadline)) current = c;
        consumed = Array.isArray(saved.consumed) ? saved.consumed.filter(token => typeof token === 'string') : [];
      }
    } catch (_) { current = null; consumed = []; }
  }
  function persist() {
    if (!key) return;
    consumed = [...new Set(consumed)].filter(token => Number(token.slice(token.lastIndexOf('@') + 1)) > now() - 14 * 86400000).slice(-1024);
    try { localStorage.setItem(key, JSON.stringify({ version: VERSION, current, consumed })); }
    catch (_) { notify('Focus timer could not save its state on this device.'); }
  }
  function connection() {
    const value = config.getKey?.();
    const next = value ? `planner-focus-v1:${hash(value)}` : null;
    if (next === key) return;
    key = next; current = null; consumed = []; blocks = []; floatingNotice = '';
    if (key) read();
    closeFloating();
  }
  function remaining() { return current ? Math.max(0, current.status === 'running' ? current.deadline - now() : current.remaining) : 0; }
  function suppress(id) { blocks.filter(b => (id == null || b.id === id) && b.start <= now() && now() < b.end).forEach(b => consumed.push(b.occurrence)); }
  function unlockAudio() {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return null;
    audio ||= new Audio();
    return audio.resume();
  }
  function tone(end = false) {
    try {
      const promise = unlockAudio();
      if (!audio) return;
      const play = () => {
        if (audio.state !== 'running') return;
        [0, .16, .32].forEach((offset, i) => {
          const osc = audio.createOscillator(), gain = audio.createGain();
          osc.type = 'sine'; osc.frequency.value = (end ? [660, 880, 990] : [440, 554, 660])[i];
          const at = audio.currentTime + offset;
          gain.gain.setValueAtTime(0, at); gain.gain.linearRampToValueAtTime(.12, at + .02); gain.gain.exponentialRampToValueAtTime(.001, at + .2);
          osc.connect(gain); gain.connect(audio.destination); osc.start(at); osc.stop(at + .22);
        });
      };
      if (promise?.then) promise.then(play).catch(() => {}); else play();
    } catch (_) { /* Browser audio permission may require a later click. */ }
  }
  function begin(task, duration, occurrence = null, automatic = false) {
    if (!key || !task?.id || !Number.isFinite(duration) || duration <= 0) return false;
    suppress(automatic ? task.id : null);
    floatingNotice = '';
    current = { task: { id: String(task.id), title: String(task.title || 'Focus') }, duration, remaining: duration, deadline: now() + duration, status: 'running', occurrence, owner, automatic };
    persist(); render(); tone(); return true;
  }
  function durationFor(task) {
    const seconds = task?.remaining_seconds ?? task?.remainingSeconds;
    if (seconds != null) return Number(seconds) * 1000;
    const planned = task?.planned_seconds ?? Number(task?.estimated_minutes ?? task?.minutes ?? 30) * 60;
    return Math.max(0, Number(planned) - Number(task?.worked_seconds || 0)) * 1000;
  }
  function start(task) {
    connection();
    const duration = durationFor(task);
    if (!task?.id || !Number.isFinite(duration) || duration <= 0) return false;
    if (current && ['running', 'paused'].includes(current.status) && remaining() > 0) {
      if (current.task.id === String(task.id)) { render(); return true; }
      if (!window.confirm(`Switch focus from “${current.task.title}” to “${task.title || 'Focus'}”? The previous task stays unfinished.`)) return false;
    }
    return begin(task, duration);
  }
  function pause() { if (current?.status !== 'running') return; current.remaining = remaining(); current.status = 'paused'; suppress(); persist(); render(); }
  function resume() { if (current?.status !== 'paused' || current.remaining <= 0) return; current.deadline = now() + current.remaining; current.status = 'running'; current.owner = owner; persist(); render(); tone(); }
  function closeFloating() {
    floatingEpoch++; opening = false;
    const win = pip; pip = null;
    for (const view of views) if (view.floating) views.delete(view);
    if (win) { try { win.close(); } catch (_) {} }
  }
  function cancel() { if (current) suppress(); current = null; persist(); closeFloating(); render(); }
  function finish() {
    if (!current) return;
    const finished = { ...current.task, elapsed_seconds: Math.round(Math.max(0, current.duration - remaining()) / 1000), timer_complete: current.status === 'complete' };
    const totalSeconds = Math.round(current.duration / 1000);
    cancel(); try { window.focus(); } catch (_) {}
    config.onFinish?.(finished, { seconds: finished.elapsed_seconds, totalSeconds, source: 'focus' });
  }
  function localParts(time, tz) {
    return Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(time).map(p => [p.type, p.value]));
  }
  function instant(date, minutes, tz) {
    const [year, month, day] = date.split('-').map(Number);
    const target = Date.UTC(year, month - 1, day, 0, minutes);
    let result = target;
    for (let i = 0; i < 4; i++) {
      const p = localParts(result, tz);
      const actual = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
      const adjustment = target - actual;
      if (!adjustment) return result;
      result += adjustment;
    }
    return result;
  }
  function update({ items = [], date, tz = 'UTC' } = {}) {
    connection();
    if (!key || !/^\d{4}-\d{2}-\d{2}$/.test(date || '')) { render(); return; }
    try {
      const p = localParts(now(), tz);
      const today = `${p.year}-${p.month}-${p.day}`;
      // Logical days spill into the early hours of the following calendar day.
      const yesterday = new Date(Date.UTC(+p.year, +p.month - 1, +p.day - 1)).toISOString().slice(0, 10);
      const logicalDay = Number(p.hour) < 4 ? yesterday : today;
      if (date !== logicalDay) { render(); return; }
      blocks = items.flatMap(task => {
        if (task.done || !task.id || /^(draft|local|pending):/.test(task.id)) return [];
        const match = /^(\d{1,2}):(\d{2})/.exec(task.start_time || '');
        if (!match || +match[2] > 59) return [];
        const minutes = +match[1] * 60 + +match[2];
        const duration = Number(task.planned_seconds ?? Number(task.estimated_minutes ?? 30) * 60) * 1000;
        if (minutes >= 1800 || !Number.isFinite(duration) || duration <= 0 || duration > 86400000 || durationFor(task) <= 0) return [];
        const start = instant(date, minutes, tz);
        return [{ id: String(task.id), task, start, end: start + duration, occurrence: `${task.id}@${start}` }];
      });
    } catch (_) { render(); return; }
    tick();
  }
  function tick() {
    if (current?.status === 'running' && remaining() <= 0) {
      current.status = 'complete'; current.remaining = 0;
      const audible = current.owner === owner; persist(); if (audible) tone(true);
    }
    const candidate = blocks.filter(b => b.start <= now() && now() < b.end).sort((a, b) => b.start - a.start || a.id.localeCompare(b.id))[0];
    if (candidate && !consumed.includes(candidate.occurrence)) {
      // Another open tab may have claimed this occurrence since the last event.
      read();
      if (consumed.includes(candidate.occurrence)) { render(); return; }
      // Retire earlier overlaps, so cancel/expiry never resurrects an old block.
      blocks.filter(b => b.start <= candidate.start && b.end > now()).forEach(b => consumed.push(b.occurrence));
      begin(candidate.task, candidate.end - now(), candidate.occurrence, true);
    }
    render();
  }
  function element(doc, tag, cls, text) { const el = doc.createElement(tag); el.className = cls; if (text != null) el.textContent = text; return el; }
  function mount(doc, floating) {
    const panel = element(doc, 'section', `focus-timer${floating ? ' focus-floating' : ' focus-compact focus-minimized'}`);
    panel.setAttribute('aria-label', 'Focus timer');
    const eyebrow = element(doc, 'div', 'focus-eyebrow', 'FOCUS SESSION');
    const title = element(doc, 'h2', 'focus-title');
    const clock = element(doc, 'div', 'focus-clock'); clock.setAttribute('role', 'timer'); clock.setAttribute('aria-live', 'off');
    const dial = element(doc, 'div', 'focus-dial');
    const svg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 200 200'); svg.setAttribute('aria-hidden', 'true');
    const rect = cls => {
      const shape = doc.createElementNS('http://www.w3.org/2000/svg', 'rect');
      for (const [name, value] of Object.entries({ x: 8, y: 8, width: 184, height: 184, rx: 16, pathLength: 100 })) shape.setAttribute(name, value);
      shape.setAttribute('class', cls); svg.append(shape); return shape;
    };
    rect('focus-perimeter'); const fill = rect('focus-fill'); dial.append(svg, clock);
    let minimize = null;
    if (!floating) {
      minimize = element(doc, 'button', 'focus-minimize', 'Expand'); minimize.type = 'button';
      minimize.setAttribute('aria-expanded', 'false');
      minimize.addEventListener('click', () => {
        const small = panel.classList.toggle('focus-minimized'); minimize.textContent = small ? 'Expand' : 'Minimize'; minimize.setAttribute('aria-expanded', String(!small));
      });
    }
    const status = element(doc, 'p', 'focus-status');
    const notice = element(doc, 'p', 'focus-notice'); notice.setAttribute('role', 'status'); notice.hidden = true;
    const actions = element(doc, 'div', 'focus-actions');
    const button = (label, fn, cls = '') => { const b = element(doc, 'button', `focus-button ${cls}`, label); b.type = 'button'; b.addEventListener('click', fn); actions.append(b); return b; };
    const toggle = button('Pause', () => current?.status === 'paused' ? resume() : pause());
    const done = button('Finish', finish, 'focus-primary');
    const stop = button('Cancel', cancel);
    const floatButton = floating ? null : button('Float timer ↗', float);
    if (floating) button('Return to planner', () => pip?.close());
    panel.append(eyebrow, title, dial, status, actions, notice); if (minimize) panel.append(minimize); doc.body.append(panel);
    const view = { panel, title, clock, fill, status, notice, toggle, done, stop, floatButton, floating }; views.add(view); return view;
  }
  function render() {
    const left = remaining(), seconds = Math.ceil(left / 1000);
    for (const view of views) {
      view.panel.hidden = !current;
      if (!current) continue;
      view.title.textContent = current.task.title;
      view.notice.textContent = floatingNotice; view.notice.hidden = !floatingNotice;
      view.clock.textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
      view.fill.style.strokeDasharray = '100';
      view.fill.style.strokeDashoffset = String(100 - Math.max(0, Math.min(100, left / current.duration * 100)));
      view.status.textContent = current.status === 'complete' ? 'Time is up · Finish when you are ready' : current.status === 'paused' ? 'Paused · Take a breath' : 'One thing at a time';
      view.toggle.textContent = current.status === 'paused' ? 'Resume' : 'Pause'; view.toggle.hidden = current.status === 'complete';
      if (view.floatButton) { view.floatButton.textContent = pip ? 'Timer is floating ↗' : 'Float timer ↗'; view.floatButton.disabled = opening; }
    }
  }
  function floatError(message) { floatingNotice = message; notify(message); render(); }
  function float() {
    if (!current) return Promise.resolve(false);
    current.owner = owner; persist();
    if (pip && !pip.closed) { pip.focus?.(); return Promise.resolve(true); }
    if (opening) return Promise.resolve(false);
    if (!window.documentPictureInPicture?.requestWindow) {
      try { unlockAudio()?.catch?.(() => {}); } catch (_) {}
      floatError('Always-on-top floating timers require Chrome or Edge with Document Picture-in-Picture. This browser keeps the timer in the planner.');
      return Promise.resolve(false);
    }
    opening = true;
    const requestEpoch = floatingEpoch;
    let request;
    // Must happen synchronously inside the click, before any audio awaits.
    try { request = window.documentPictureInPicture.requestWindow({ width: 360, height: 420 }); }
    catch (error) { opening = false; floatError('The floating timer could not open. Try Float timer again.'); return Promise.resolve(false); }
    try { unlockAudio()?.catch?.(() => {}); } catch (_) {}
    render();
    return Promise.resolve(request).then(win => {
      if (requestEpoch !== floatingEpoch || !current) { try { win.close(); } catch (_) {} return false; }
      pip = win; opening = false; floatingNotice = '';
      const doc = win.document; doc.title = 'Planner · Focus';
      const link = doc.createElement('link'); link.rel = 'stylesheet'; link.href = stylesheet; doc.head.append(link);
      doc.body.className = 'focus-pip-body'; const view = mount(doc, true);
      win.addEventListener('pagehide', () => { views.delete(view); if (pip === win) pip = null; render(); }, { once: true });
      render(); return true;
    }).catch(() => { if (requestEpoch !== floatingEpoch) return false; opening = false; floatError('The floating timer could not open. Try Float timer again.'); render(); return false; });
  }
  function reset() { current = null; consumed = []; blocks = []; persist(); closeFloating(); render(); }
  window.PlannerFocus = {
    configure(options = {}) { config = { ...config, ...options }; connection(); tick(); }, update, start, pause, resume, cancel, finish, float, reset,
    stopTask(id) { suppress(String(id)); blocks = blocks.filter(b => b.id !== String(id)); if (current?.task.id === String(id)) cancel(); else persist(); },
    snapshot() { return current ? { ...current, task: { ...current.task }, remaining: remaining() } : null; }
  };
  window.addEventListener('storage', event => { if (event.key === key) { current = null; consumed = []; read(); if (!current) closeFloating(); render(); } });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
  function init() { mount(document, false); timer ||= setInterval(tick, 500); render(); }
  if (document.body) init(); else document.addEventListener('DOMContentLoaded', init, { once: true });
})();
