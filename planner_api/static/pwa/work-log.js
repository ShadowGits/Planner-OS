/* Optional actual-work entry. Only an explicit Save writes a durable request. */
(() => {
  'use strict';
  let config = {}, current = null;
  const el = (tag, props = {}, text = '') => {
    const node = document.createElement(tag);
    Object.assign(node, props);
    if (text) node.textContent = text;
    return node;
  };
  const duration = seconds => {
    const s = Math.max(0, Number(seconds) || 0);
    return `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m${s % 60 ? ` ${s % 60}s` : ''}`;
  };
  function storageKey(id) {
    // Keep connection credentials out of the stored key and request.
    const scope = String(config.getKey?.() || location.origin);
    let hash = 2166136261;
    for (const char of scope) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
    return `planner.work.pending.v1.${(hash >>> 0).toString(16)}.${id}`;
  }
  function readPending(id) {
    try {
      const data = JSON.parse(localStorage.getItem(storageKey(id)) || 'null');
      return data && typeof data.request_id === 'string' && Number.isInteger(data.seconds) ? data : null;
    } catch { return null; }
  }
  const shiftDate = (date, days) => {
    const d = new Date(`${date}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  };
  function logicalNow(tz) {
    let parts;
    try {
      parts = new Intl.DateTimeFormat('en-CA', { timeZone: tz || undefined, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date());
    } catch { return logicalNow(); }
    const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
    const date = `${p.year}-${p.month}-${p.day}`;
    const minute = Number(p.hour) * 60 + Number(p.minute);
    return { date: minute < 240 ? shiftDate(date, -1) : date, minute: minute < 240 ? minute + 1440 : minute };
  }
  function minutes(time) {
    const [h, m] = String(time || '').split(':').map(Number);
    if (!Number.isFinite(h) || !Number.isFinite(m)) return null;
    return h * 60 + m + (h < 4 ? 1440 : 0);
  }
  const timeString = minute => `${String(Math.floor(minute / 60) % 24).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;
  function busySlots(view, date) {
    const ctx = config.getContext?.() || {};
    if (ctx.date !== date) return [];
    return (ctx.items || []).filter(t => String(t.id) !== String(view.task.id) && !t.done && t.status !== 'done' && t.status !== 'skipped' && t.start_time).map(t => {
      const start = minutes(t.start_time);
      return { start, end: start + Math.ceil((t.planned_seconds || (t.estimated_minutes || 30) * 60) / 60) };
    }).filter(t => t.start !== null).sort((a, b) => a.start - b.start);
  }
  function suggest(view, seconds) {
    const ctx = config.getContext?.() || {};
    const now = logicalNow(ctx.tz || view.info?.timezone);
    let start = Math.ceil(now.minute / 5) * 5;
    const needed = Math.ceil(seconds / 60);
    for (const slot of busySlots(view, now.date)) {
      if (start + needed <= slot.start) break;
      if (start < slot.end && start + needed > slot.start) start = Math.ceil(slot.end / 5) * 5;
    }
    if (start + needed > 1680) return { date: shiftDate(now.date, 1), time: '04:00' };
    return { date: shiftDate(now.date, Math.floor(start / 1440)), time: timeString(start) };
  }
  function close(view = current) {
    if (!view || current !== view || (view.saving && window.PlannerFocus?.enabled() !== false)) return;
    current = null;
    document.removeEventListener('keydown', view.keyHandler, true);
    window.removeEventListener('popstate', view.backHandler);
    view.overlay.remove();
    for (const [node, wasInert] of view.inert) node.inert = wasInert;
    if (view.focus?.isConnected) view.focus.focus();
  }
  function field(label, input) {
    const wrap = el('label', { className: 'work-log-field' }, label);
    wrap.append(input); return wrap;
  }
  function entrySeconds(view) {
    if (view.pending) return view.pending.seconds;
    const h = Number(view.hours.value || 0), m = Number(view.mins.value || 0);
    return h * 3600 + m * 60 + view.extraSeconds;
  }
  function update(view) {
    if (!view.info) return;
    const remaining = Math.max(0, view.info.remaining_seconds - entrySeconds(view));
    view.remaining.textContent = `Remaining after this entry: ${duration(remaining)}`;
    const canSplit = remaining > 0 && !view.task.done && view.task.status !== 'done';
    view.split.disabled = !canSplit || !!view.pending;
    if (!view.pending) {
      if (!canSplit) view.split.checked = false;
      else if (!view.splitTouched && view.task.start_time && !view.task.is_habit) view.split.checked = true;
    }
    view.schedule.hidden = !view.split.checked;
    view.warning.textContent = '';
    if (view.split.checked && !view.pending && !view.scheduleTouched) {
      const next = suggest(view, remaining);
      view.date.value = next.date; view.time.value = next.time;
    }
    if (view.split.checked && view.date.value && view.time.value) {
      const start = minutes(view.time.value), end = start + Math.ceil(remaining / 60);
      const slotDate = Number(view.time.value.slice(0, 2)) < 4 ? shiftDate(view.date.value, -1) : view.date.value;
      if (busySlots(view, slotDate).some(slot => start < slot.end && end > slot.start)) view.warning.textContent = 'This time overlaps another unfinished task.';
      else if ((config.getContext?.() || {}).date !== slotDate) view.warning.textContent = 'Availability for this date is not loaded. Check your schedule before saving.';
    }
  }
  function freeze(view) {
    for (const input of view.form.querySelectorAll('input, select')) input.disabled = !!view.pending || view.saving;
    view.split.disabled = !!view.pending || view.saving || !view.info || view.info.remaining_seconds <= entrySeconds(view) || view.task.done || view.task.status === 'done';
    view.save.disabled = view.saving || !view.info && !view.pending;
    view.ignore.disabled = view.saving;
    view.save.textContent = view.saving ? 'Saving…' : view.pending ? 'Retry saved entry' : 'Save time';
  }
  async function save(view) {
    if (window.PlannerFocus?.enabled() === false || view.saving || current !== view) return;
    if (!view.pending) {
      if (!view.form.reportValidity()) return;
      const seconds = entrySeconds(view);
      if (!Number.isInteger(seconds) || seconds < 0 || seconds > 86400) {
        view.error.textContent = 'Enter between 0 and 24 hours.'; return;
      }
      const split = view.split.checked && view.info.remaining_seconds > seconds && !view.task.done && view.task.status !== 'done';
      if (split && (!view.date.value || !view.time.value)) { view.error.textContent = 'Choose a date and time for the remaining work.'; return; }
      view.pending = {
        request_id: crypto.randomUUID(), seconds, source: view.source,
        finish: true, split,
        remainder_date: split ? view.date.value : null,
        remainder_time: split ? view.time.value : null,
      };
      try { localStorage.setItem(storageKey(view.task.id), JSON.stringify(view.pending)); }
      catch { view.pending = null; view.error.textContent = 'This device cannot retain a retry safely. Enable browser storage and try again.'; return; }
    }
    view.saving = true; view.error.textContent = ''; freeze(view);
    try {
      await config.api('POST', `/v2/day/tasks/${encodeURIComponent(view.task.id)}/work`, view.pending);
    } catch (error) {
      view.saving = false;
      if (error.status === 400) {
        try { localStorage.removeItem(storageKey(view.task.id)); } catch {}
        view.pending = null; update(view); freeze(view);
        view.error.textContent = `${error.message || 'This entry was rejected.'} Adjust the entry and save again.`;
      } else {
        freeze(view);
        view.error.textContent = `${error.message || 'Time could not be saved.'} Your entry is kept on this device. Retry saves the same entry.`;
      }
      return;
    }
    try { localStorage.removeItem(storageKey(view.task.id)); } catch { /* Server already confirmed this UUID. */ }
    view.saving = false; close(view);
    if (window.PlannerFocus?.enabled() !== false) config.toast?.('Time saved');
    try { await config.onSaved?.(); } catch { if (window.PlannerFocus?.enabled() !== false) config.toast?.('Time saved. Refresh the day to see the update.'); }
  }
  async function load(view, task) {
    view.task = task; view.info = null; view.pending = readPending(task.id);
    view.error.textContent = ''; view.summary.textContent = 'Loading work history…'; freeze(view);
    try {
      const out = await config.api('GET', `/v2/day/tasks/${encodeURIComponent(task.id)}/work`);
      if (current !== view || String(view.task.id) !== String(task.id)) return;
      const info = out.data;
      view.info = info; view.task = { ...task, ...info.task };
      view.name.textContent = view.task.title || 'Task';
      view.summary.textContent = `Planned: ${duration(info.planned_seconds)} · Worked: ${duration(info.worked_seconds)}`;
      if (info.blocks?.length) {
        view.info = null; view.summary.textContent = 'Choose an individual session to log its time.';
        view.blockWrap.hidden = false; view.block.replaceChildren(el('option', { value: '' }, 'Choose session'));
        for (const block of info.blocks) view.block.append(el('option', { value: block.id }, `${block.title || 'Session'} · ${block.scheduled_date || 'Unscheduled'} ${block.start_time?.slice(0, 5) || ''} · ${block.estimated_minutes || 30}m${block.status === 'done' ? ' · Done' : ''}`));
        view.blocks = info.blocks; freeze(view); return;
      }
      if (view.pending) {
        view.hours.value = Math.floor(view.pending.seconds / 3600);
        view.mins.value = Math.floor(view.pending.seconds % 3600 / 60);
        view.extraSeconds = view.pending.seconds % 60;
        view.source = view.pending.source;
        view.split.checked = view.pending.split;
        view.date.value = view.pending.remainder_date || ''; view.time.value = view.pending.remainder_time || '';
        view.error.textContent = 'A previous save needs confirmation. Retry sends the same saved entry.';
      } else {
        view.split.checked = !!view.task.start_time && !view.task.is_habit && !view.task.done && view.task.status !== 'done' && info.remaining_seconds > entrySeconds(view);
      }
      update(view); freeze(view); view.hours.focus();
    } catch (error) {
      if (current !== view) return;
      view.summary.textContent = 'Work history could not be loaded.';
      view.error.textContent = error.message || 'Please try again when connected.'; freeze(view);
    }
  }
  async function open(task, options = {}) {
    if (window.PlannerFocus?.enabled() === false || !task?.id || typeof config.api !== 'function') return;
    if (current?.saving) return;
    close();
    const view = { task, focus: document.activeElement, inert: [], source: options.source === 'timer' ? 'timer' : 'manual', extraSeconds: Math.max(0, Math.floor(options.seconds || 0)) % 60, scheduleTouched: false };
    current = view;
    view.overlay = el('div', { className: 'work-log-overlay' });
    const dialog = el('section', { className: 'work-log-dialog' });
    dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true'); dialog.setAttribute('aria-labelledby', 'work-log-heading');
    dialog.append(el('h2', { id: 'work-log-heading' }, 'Log time'));
    view.name = el('p', { className: 'work-log-task' }, task.title || 'Task'); dialog.append(view.name);
    view.summary = el('p', { className: 'work-log-summary' }); dialog.append(view.summary);
    view.form = el('form');
    view.block = el('select'); view.blockWrap = field('Session', view.block); view.blockWrap.hidden = true; view.form.append(view.blockWrap);
    const seconds = Math.max(0, Math.floor(options.seconds || 0));
    view.hours = el('input', { type: 'number', min: '0', max: '24', step: '1', value: seconds ? String(Math.floor(seconds / 3600)) : '', inputMode: 'numeric' });
    view.mins = el('input', { type: 'number', min: '0', max: '59', step: '1', value: seconds ? String(Math.floor(seconds % 3600 / 60)) : '', inputMode: 'numeric' });
    const row = el('div', { className: 'work-log-row' }); row.append(field('Hours (optional)', view.hours), field('Minutes (optional)', view.mins)); view.form.append(row);
    view.form.append(el('p', { className: 'work-log-help' }, view.extraSeconds ? `Includes ${view.extraSeconds} seconds from the timer.` : 'Leave empty to record zero time. Ignore closes without saving.'));
    view.remaining = el('p', { className: 'work-log-summary' }); view.form.append(view.remaining);
    view.split = el('input', { type: 'checkbox' }); const splitLabel = el('label', { className: 'work-log-check' }); splitLabel.append(view.split, document.createTextNode('Split & schedule remaining work')); view.form.append(splitLabel);
    view.schedule = el('div', { className: 'work-log-row', hidden: true });
    view.date = el('input', { type: 'date' }); view.time = el('input', { type: 'time' });
    view.schedule.append(field('Remaining work date', view.date), field('Start time', view.time)); view.form.append(view.schedule);
    view.warning = el('p', { className: 'work-log-help' }); view.form.append(view.warning);
    view.error = el('p', { className: 'work-log-error' }); view.error.setAttribute('role', 'alert'); view.form.append(view.error);
    const actions = el('div', { className: 'work-log-actions' });
    view.ignore = el('button', { type: 'button' }, 'Ignore'); view.save = el('button', { type: 'submit', className: 'work-log-save' }, 'Save time'); actions.append(view.ignore, view.save); view.form.append(actions);
    dialog.append(view.form); view.overlay.append(dialog);
    for (const node of document.body.children) if (!['SCRIPT', 'STYLE', 'LINK'].includes(node.tagName)) { view.inert.push([node, node.inert]); node.inert = true; }
    document.body.append(view.overlay);
    view.form.addEventListener('submit', event => { event.preventDefault(); save(view); });
    view.ignore.addEventListener('click', () => close(view));
    view.overlay.addEventListener('click', event => { if (event.target === view.overlay) close(view); });
    for (const input of [view.hours, view.mins]) input.addEventListener('input', () => { update(view); freeze(view); });
    view.split.addEventListener('change', () => { view.splitTouched = true; update(view); });
    for (const input of [view.date, view.time]) input.addEventListener('input', () => { view.scheduleTouched = true; update(view); });
    view.block.addEventListener('change', () => { const block = view.blocks?.find(t => String(t.id) === view.block.value); if (block) load(view, block); });
    view.keyHandler = event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(view); }
      if (event.key === 'Tab') {
        const focusable = [...dialog.querySelectorAll('button,input,select')].filter(node => !node.disabled && !node.closest('[hidden]'));
        const first = focusable[0], last = focusable.at(-1);
        if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
      }
    };
    view.backHandler = () => close(view);
    document.addEventListener('keydown', view.keyHandler, true); window.addEventListener('popstate', view.backHandler);
    view.ignore.focus(); await load(view, task);
  }
  window.PlannerWorkLog = { configure(options) { config = { ...config, ...options }; }, open, close: () => close() };
})();
