/* Structured-style day planner over the /v2/day API.
   A flowing list (not a scaled calendar): tasks stack as rows on a dotted
   spine, free gaps collapse into a "+ Add Task" row. All state lives in
   Postgres; this file only renders and reports. */

(() => {
  "use strict";

  const SNAP_MIN = 5;
  const GAP_MIN = 30;
  const PX_PER_MIN = 1.8; // proportional: an hour is a real, scrollable hour
  const MIN_ROW_PX = 52;
  const KEY_STORE = "day-planner-key";

  const $ = (id) => document.getElementById(id);

  const state = {
    selected: getLogicalToday(),
    items: [],
    tz: null,
    editing: null, // task id when the sheet is in edit mode
  };

  let dragging = false; // a row is currently lifted for reschedule
  let lastInteraction = 0; // ms of the last touch, to pause auto-refresh
  window.addEventListener("pointerdown", () => (lastInteraction = Date.now()), true);

  /* ---------- date helpers ---------- */

  function startOfDay(d) {
    const x = new Date(d);
    x.setHours(0, 0, 0, 0);
    return x;
  }

  function getLogicalToday() {
    const d = new Date();
    if (d.getHours() < 4) d.setDate(d.getDate() - 1);
    return startOfDay(d);
  }

  function iso(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function sameDay(a, b) {
    return iso(a) === iso(b);
  }

  function timeToMin(t) {
    if (!t) return null;
    const [h, m] = String(t).split(":").map(Number);
    return h * 60 + m;
  }

  function minToTime(min) {
    const h = String(Math.floor(min / 60)).padStart(2, "0");
    const m = String(min % 60).padStart(2, "0");
    return `${h}:${m}`;
  }

  function fmtClock(min) {
    const d = new Date();
    d.setHours(Math.floor(min / 60), Math.round(min % 60), 0, 0);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  function fmtDur(min) {
    const h = Math.floor(min / 60);
    const m = min % 60;
    if (h && m) return `${h}h ${m}m`;
    if (h) return `${h}h`;
    return `${m}m`;
  }

  /* ---------- icons + colors ---------- */

  const EMOJI_RULES = [
    [/german|deutsch|\ba1\b|\ba2\b|duolingo|babbel/i, "🇩🇪"],
    [/gym|workout|lift|train|exercise|brahmri|yoga/i, "🏋️"],
    [/run|jog|walk/i, "🏃"],
    [/math|calc|algebra|geometry|applied/i, "📐"],
    [/read|book/i, "📖"],
    [/study|learn|course|revise/i, "📚"],
    [/call|phone|hr\b/i, "📞"],
    [/mail|email|reply/i, "✉️"],
    [/visa|embassy|passport|apostille|aps/i, "🛂"],
    [/college|uni|apply|application|sop|lor|shortlist/i, "🎓"],
    [/plan|schedule|organi[sz]e/i, "🗓️"],
    [/doc|form|paper|print|transcript|cv/i, "📄"],
    [/bank|money|finance|pay|invest|tax|fund|blocked account/i, "💰"],
    [/food|cook|meal|lunch|dinner|breakfast/i, "🍳"],
    [/clean|laundry|tidy/i, "🧹"],
    [/meet|sync|standup|interview/i, "👥"],
    [/code|build|deploy|bug|dev/i, "💻"],
    [/write|journal|blog|note/i, "✍️"],
    [/piano|music|guitar/i, "🎹"],
    [/ielts|toefl|test|exam|mock/i, "📝"],
    [/wind down|skin|sleep|rest|nap|night/i, "🌙"],
  ];

  const PASTELS = [
    "#ffe3e0", "#fff0d4", "#e6f3d8", "#d9f0f3", "#e3e8ff",
    "#f5e1f3", "#e0f4ea", "#fde8d2", "#e9e4fb", "#dcf0ff",
  ];
  const PASTELS_DARK = [
    "#4b2f2d", "#4b3e26", "#33452c", "#2b4348", "#2f3555",
    "#472f47", "#2c4639", "#4a3a27", "#383152", "#28404f",
  ];
  const RINGS = [
    "#c0504d", "#e08b3a", "#4f86d0", "#8e5bd0", "#3fae86",
    "#d6588f", "#5b9bb0", "#c98a2b", "#7267d8", "#4aa3c7",
  ];
  const GAP_LINES = [
    "Create away!", "A canvas for ideas.", "Time to make magic.",
    "Your move.", "Fill it wisely.", "Room to breathe.",
  ];

  function hash(str) {
    let h = 0;
    for (const c of str) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return h;
  }

  function emojiFor(title) {
    for (const [re, e] of EMOJI_RULES) if (re.test(title)) return e;
    return "📌";
  }

  function pastelFor(title) {
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    return (dark ? PASTELS_DARK : PASTELS)[hash(title) % PASTELS.length];
  }

  function ringFor(title) {
    return RINGS[hash(title) % RINGS.length];
  }

  /* ---------- overlap layout ---------- */

  function computeOverlapLayout(timed) {
    const layout = new Map();
    if (!timed.length) return layout;

    const ivs = timed.map((t) => ({
      id: t.id,
      start: timeToMin(t.start_time),
      end: timeToMin(t.start_time) + (t.estimated_minutes || 30),
    }));

    const colEnds = [];
    for (const iv of ivs) {
      let placed = false;
      for (let c = 0; c < colEnds.length; c++) {
        if (iv.start >= colEnds[c]) {
          colEnds[c] = iv.end;
          layout.set(iv.id, { col: c, totalCols: 0 });
          placed = true;
          break;
        }
      }
      if (!placed) {
        layout.set(iv.id, { col: colEnds.length, totalCols: 0 });
        colEnds.push(iv.end);
      }
    }

    for (const iv of ivs) {
      const e = layout.get(iv.id);
      let max = e.col + 1;
      for (const other of ivs) {
        if (other.id !== iv.id && iv.start < other.end && other.start < iv.end) {
          max = Math.max(max, layout.get(other.id).col + 1);
        }
      }
      e.totalCols = max;
    }

    let changed = true;
    while (changed) {
      changed = false;
      for (const iv of ivs) {
        for (const other of ivs) {
          if (other.id !== iv.id && iv.start < other.end && other.start < iv.end) {
            const m = Math.max(layout.get(iv.id).totalCols, layout.get(other.id).totalCols);
            if (layout.get(iv.id).totalCols < m) { layout.get(iv.id).totalCols = m; changed = true; }
            if (layout.get(other.id).totalCols < m) { layout.get(other.id).totalCols = m; changed = true; }
          }
        }
      }
    }

    return layout;
  }

  /* ---------- api ---------- */

  function key() {
    return localStorage.getItem(KEY_STORE) || "";
  }

  async function api(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: {
        "X-App-Key": key(),
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401) {
      showGate(true);
      throw new Error("unauthorized");
    }
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.message || `Request failed (${res.status})`);
    }
    const payload = await res.json();
    // Some endpoints report trouble in the body with a 200 — a Drive failure,
    // for one. Treating that as success let the screen claim a save that never
    // happened, so take the envelope at its word.
    if (payload && payload.success === false) {
      throw new Error(payload.message || "Request failed");
    }
    return payload;
  }

  // A tiny per-day cache so swiping through the week is instant. Each entry
  // holds that day's tasks; we still re-fetch in the background on show so the
  // screen is never stale (see goToDate).
  const dayCache = new Map(); // iso date -> { items, tz, at }
  const PREFETCH_FRESH_MS = 3600000;

  async function fetchDay(ds) {
    const out = await api("GET", `/v2/day?date=${ds}`);
    const entry = { items: out.data.items, tz: out.data.timezone, at: Date.now() };
    dayCache.set(ds, entry);
    return entry;
  }

  function applyDay(entry) {
    state.items = entry.items;
    state.tz = entry.tz;
    render();
  }

  async function loadDay(opts = {}) {
    const prevY = window.scrollY;
    const ds = iso(state.selected);
    const entry = await fetchDay(ds);
    if (iso(state.selected) !== ds) return; // user moved on while fetching
    applyDay(entry);
    // keep the reader where they were on a background refresh; jump to the
    // top when they deliberately switched to another day.
    window.scrollTo(0, opts.keepScroll ? prevY : 0);
    schedulePrefetch(state.selected);
  }

  // Warm the 3 days on each side of the selected day, on idle, so a swipe
  // paints from cache with no wait.
  let prefetchTimer = null;
  function schedulePrefetch(center) {
    clearTimeout(prefetchTimer);
    prefetchTimer = setTimeout(() => {
      for (let off = -3; off <= 3; off++) {
        if (!off) continue;
        const d = new Date(center);
        d.setDate(d.getDate() + off);
        const ds = iso(d);
        const c = dayCache.get(ds);
        if (c && Date.now() - c.at < PREFETCH_FRESH_MS) continue;
        fetchDay(ds).catch(() => {});
      }
    }, 350);
  }

  /* ---------- key gate ---------- */

  function showGate(rejected) {
    $("key-gate").classList.remove("hidden");
    $("key-error").classList.toggle("hidden", !rejected);
    $("key-input").focus();
  }

  $("key-save").addEventListener("click", async () => {
    localStorage.setItem(KEY_STORE, $("key-input").value.trim());
    $("key-gate").classList.add("hidden");
    try {
      await loadDay();
    } catch (e) {
      /* 401 reopens the gate */
    }
  });
  $("key-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("key-save").click();
  });

  /* ---------- header + week strip ---------- */

  function renderHeader() {
    const today = getLogicalToday();
    const diff = Math.round((state.selected - today) / 86400000);
    const names = { "-1": "Yesterday", 0: "Today", 1: "Tomorrow" };
    const label =
      names[diff] ?? state.selected.toLocaleDateString([], { weekday: "long" });
    $("day-title").innerHTML = `${label} <span class="chev">›</span>`;

    const done = state.items.filter((t) => t.done).length;
    const total = state.items.length;
    $("day-count").textContent = total ? `${done}/${total} done` : "";
  }

  function renderWeek() {
    const strip = $("week-strip");
    strip.innerHTML = "";
    const monday = new Date(state.selected);
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
    for (let i = 0; i < 7; i++) {
      const d = new Date(monday);
      d.setDate(monday.getDate() + i);
      const pill = document.createElement("button");
      pill.className = "day-pill";
      if (sameDay(d, getLogicalToday())) pill.classList.add("today");
      if (sameDay(d, state.selected)) pill.classList.add("selected");
      pill.innerHTML = `<span class="dow">${d.toLocaleDateString([], { weekday: "narrow" })}</span>
        <span class="num">${d.getDate()}</span><span class="dot"></span>`;
      pill.addEventListener("click", () => goToDate(d));
      strip.appendChild(pill);
    }
  }

  $("week-prev").addEventListener("click", () => shiftDays(-7));
  $("week-next").addEventListener("click", () => shiftDays(7));

  function shiftDays(n) {
    const d = new Date(state.selected);
    d.setDate(d.getDate() + n);
    goToDate(d);
  }

  // switch day: repaint the header + week strip and jump to the top at once,
  // so the change feels instant. If we already have the day cached, paint it
  // immediately and refresh it quietly in the background; otherwise fetch.
  function goToDate(d) {
    state.selected = startOfDay(d);
    renderHeader();
    renderWeek();
    window.scrollTo(0, 0);
    const ds = iso(state.selected);
    const cached = dayCache.get(ds);
    if (cached) {
      applyDay(cached);
      fetchDay(ds)
        .then((fresh) => {
          if (iso(state.selected) === ds) applyDay(fresh);
        })
        .catch(() => {});
      schedulePrefetch(state.selected);
    } else {
      // Nothing cached for this day: clear the old day off the screen first.
      // Leaving it there means a slow or failed fetch shows yesterday's tasks
      // under today's heading, which reads as the app being stuck.
      state.items = [];
      render();
      loadDay().catch(showError);
    }
  }

  /* ---------- timeline (proportional) ---------- */

  function render() {
    renderHeader();
    renderWeek();

    const timed = state.items
      .filter((t) => t.start_time)
      .sort((a, b) => timeToMin(a.start_time) - timeToMin(b.start_time));
    const inbox = state.items.filter((t) => !t.start_time);
    const overlapLayout = computeOverlapLayout(timed);

    renderInbox(inbox);

    const list = $("list");
    list.innerHTML = "";
    $("empty").classList.toggle("hidden", state.items.length > 0);
    if (!timed.length && !inbox.length) {
      list.style.height = "0px";
      return;
    }

    const mins = timed.map((t) => timeToMin(t.start_time));
    const ends = timed.map((t, i) => mins[i] + (t.estimated_minutes || 30));
    let startH = timed.length ? Math.min(0, ...mins.map((m) => Math.floor(m / 60))) : 0;
    let endH = timed.length ? Math.max(26, ...ends.map((m) => Math.ceil(m / 60) + 1)) : 26;
    const top0 = startH * 60;
    list.style.height = `${(endH - startH) * 60 * PX_PER_MIN + 24}px`;

    const spine = document.createElement("div");
    spine.className = "spine";
    list.appendChild(spine);

    for (let h = startH; h <= endH; h++) {
      const lbl = document.createElement("div");
      lbl.className = "hourlabel";
      lbl.style.top = `${(h * 60 - top0) * PX_PER_MIN}px`;
      lbl.textContent = fmtClock(h * 60);
      list.appendChild(lbl);
    }

    if (sameDay(state.selected, getLogicalToday())) {
      const now = new Date();
      let m = now.getHours() * 60 + now.getMinutes();
      if (now.getHours() < 4) m += 24 * 60;
      if (m >= top0 && m <= endH * 60) {
        const nl = document.createElement("div");
        nl.className = "now-line";
        nl.style.top = `${(m - top0) * PX_PER_MIN}px`;
        list.appendChild(nl);
      }
    }

    // The gap starts where everything so far has finished, not where this row
    // finishes. A long task overlapped by a short one ends after it, so using
    // this row's end offered a slot in the middle of the longer task.
    let busyUntil = -Infinity;
    for (let i = 0; i < timed.length; i++) {
      list.appendChild(taskRow(timed[i], top0, overlapLayout.get(timed[i].id)));
      busyUntil = Math.max(busyUntil, ends[i]);
      const nextStart = i + 1 < timed.length ? mins[i + 1] : null;
      if (nextStart !== null && nextStart - busyUntil >= GAP_MIN) {
        list.appendChild(gapRow(busyUntil, nextStart, top0));
      }
    }
  }

  function taskRow(task, top0, layout) {
    const start = timeToMin(task.start_time);
    const dur = task.estimated_minutes || 30;
    const row = document.createElement("div");
    const isOverlap = layout && layout.totalCols > 1;
    row.className = "row" + (task.done ? " done" : "") + (isOverlap ? " overlap" : "");
    row.style.top = `${(start - top0) * PX_PER_MIN}px`;
    row.style.height = `${Math.max(MIN_ROW_PX, dur * PX_PER_MIN)}px`;
    row.style.setProperty("--ring", ringFor(task.title));
    row.style.setProperty("--task-bg", pastelFor(task.title));

    const recur = task.recurrence_key ? " ↻" : "";
    const timeLabel = `${fmtClock(start)} – ${fmtClock(start + dur)} (${fmtDur(dur)})${recur}` + (task.parent_task_id ? " 🔗 (Part)" : "");

    if (isOverlap) {
      // Side by side, each in its own column of the shared time span. The
      // duration-height pill and outside text stay the same as a normal task;
      // only the horizontal room changes while the tasks clash.
      // Columns live to the right of the hour labels and the spine, and stop
      // short of the right padding, so they never sit under the clock gutter.
      const LEFT = 60, RIGHT = 12;
      const share = `((100% - ${LEFT + RIGHT}px) / ${layout.totalCols})`;
      row.style.left = `calc(${LEFT}px + ${layout.col} * ${share} + 3px)`;
      row.style.width = `calc(${share} - 6px)`;
      row.style.zIndex = layout.col + 1;
      if (layout.totalCols > 2) row.classList.add("tight");
      // a hairline between neighbours, so the last column has none
      if (layout.col < layout.totalCols - 1) row.classList.add("divided");
      row.innerHTML = `
        <div class="ov-item">
          <div class="ov-rail">
            <div class="ov-time-shape" style="background:${pastelFor(task.title)}">
              <div class="ov-icon">${emojiFor(task.title)}</div>
            </div>
          </div>
          <div class="ov-body">
            <div class="ov-time">${layout.totalCols > 2 ? fmtClock(start) : `${fmtClock(start)} · ${fmtDur(dur)}`}${recur}</div>
            <div class="ov-title">${escapeHtml(task.title)}</div>
          </div>
          <button class="ring${task.done ? " checked" : ""}" aria-label="Toggle done"></button>
        </div>`;
    } else {
      row.innerHTML = `
      <div class="rail" style="position: relative; width: 100%; height: 100%; display: flex; justify-content: center; z-index: 1;">
        <div class="time-shape" style="width: 42px; height: 100%; min-height: 42px; border-radius: 21px; background: ${pastelFor(task.title)}; display: flex; align-items: center; justify-content: center; box-shadow: 0 0 0 4px var(--bg);">
          <div class="icon" style="font-size: 20px; line-height: 1;">${emojiFor(task.title)}</div>
        </div>
      </div>
      <div class="body" style="padding-left: 4px; display: flex; flex-direction: column; justify-content: center; height: 100%; position: relative;">
        <div class="meta" style="color: var(--ink-2); font-size: 12.5px; margin-bottom: 2px; font-weight: 500;">${timeLabel}</div>
        <div class="title">${escapeHtml(task.title)}</div>
      </div>
      <button class="ring${task.done ? " checked" : ""}" aria-label="Toggle done"></button>`;
    }

    if (task.pending) row.classList.add("pending");

    row.querySelector(".ring").addEventListener("click", (e) => {
      e.stopPropagation();
      // Still being created: it has no real id yet, so anything sent about it
      // would be about a task the server has never heard of.
      if (task.pending) return;
      toggleDone(task, row);
    });
    row.addEventListener("click", (e) => {
      if (e.target.closest(".ring")) return;
      if (task.pending) return;
      if (row._suppressClick) {
        row._suppressClick = false;
        return;
      }
      openEdit(task);
    });
    attachDrag(row, task, top0);
    return row;
  }

  function gapRow(fromMin, toMin, top0) {
    const free = toMin - fromMin;
    const note = GAP_LINES[Math.floor(fromMin / 37) % GAP_LINES.length];
    const el = document.createElement("div");
    el.className = "gap";
    el.style.top = `${(fromMin - top0) * PX_PER_MIN}px`;
    el.style.height = `${free * PX_PER_MIN}px`;
    el.innerHTML = `
      <div class="rail"></div>
      <div class="gap-body">
        <div class="gap-note">🕐 Use <b>${fmtDur(free)}</b> wisely. ${note}</div>
        <button class="gap-add">＋ Add Task</button>
      </div>`;
    // Round up, never down: rounding to the nearest could start the task a
    // few minutes before the free window actually opens.
    const slot = Math.ceil(fromMin / SNAP_MIN) * SNAP_MIN;
    el.querySelector(".gap-add").addEventListener("click", () => openSheet(slot));
    return el;
  }

  /* Press and hold anywhere on a task (~230ms), then drag up/down to a new
     time (5-min snap). Rows scroll natively (touch-action:pan-y) until the
     hold fires; from then on a global non-passive touchmove blocker (see
     boot) stops the page scrolling while `dragging` is true, so the finger
     moves the event instead of the page. A quick move before the hold is a
     normal scroll and is left to the browser. */
  function attachDrag(row, task, top0) {
    // A task still being created cannot be moved; the server has no id for it.
    if (task.pending) return;
    let holdTimer = null;
    let lifted = false;
    let originY = 0;
    let originTop = 0;
    let pointerId = null;
    let badge = null;
    let newStart = null;

    function cancelHold() {
      if (holdTimer) {
        clearTimeout(holdTimer);
        holdTimer = null;
      }
    }

    row.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".ring")) return;
      if (e.pointerType === "mouse" && e.button !== 0) return;
      // Apple Pencil emits hover events with no contact; ignore them.
      if (e.pointerType === "pen" && e.buttons === 0) return;
      pointerId = e.pointerId;
      originY = e.clientY;
      originTop = parseFloat(row.style.top);
      lifted = false;
      cancelHold();
      holdTimer = setTimeout(() => {
        holdTimer = null;
        lifted = true;
        dragging = true; // the global touchmove blocker now stops scrolling
        row.classList.add("lifted");
        try {
          row.setPointerCapture(pointerId);
        } catch (_) {}
        if (navigator.vibrate) navigator.vibrate(14);
        badge = document.createElement("div");
        badge.className = "drag-badge";
        row.appendChild(badge);
        updateBadge(originTop);
      }, 230);
    });

    row.addEventListener("pointermove", (e) => {
      if (e.pointerId !== pointerId) return;
      if (!lifted) {
        // moved before the hold fired → it's a scroll; let the browser have it
        if (Math.abs(e.clientY - originY) > 10) cancelHold();
        return;
      }
      e.preventDefault();
      const top = Math.max(0, originTop + (e.clientY - originY));
      row.style.top = `${top}px`;
      updateBadge(top);
    });

    function updateBadge(top) {
      const raw = top / PX_PER_MIN + top0;
      newStart = Math.max(Math.round(raw / SNAP_MIN) * SNAP_MIN, 0);
      if (badge) badge.textContent = fmtClock(newStart);
    }

    async function finish(save) {
      cancelHold();
      if (pointerId !== null) {
        try {
          row.releasePointerCapture(pointerId);
        } catch (_) {}
        pointerId = null;
      }
      if (!lifted) return; // a tap or scroll → the click handler opens edit
      lifted = false;
      dragging = false;
      row.classList.remove("lifted");
      row._suppressClick = true;
      if (badge) {
        badge.remove();
        badge = null;
      }
      const cur = task.start_time ? task.start_time.slice(0, 5) : null;
      if (save && newStart !== null && minToTime(newStart) !== cur) {
        // Move it where it was dropped straight away and tell the server
        // afterwards. Waiting for the round trip first left the row sitting at
        // its old time for as long as the server took to answer, which on a
        // cold start is seconds.
        const wasTime = task.start_time;
        const wasDate = task.scheduled_date;
        task.start_time = minToTime(newStart);
        task.scheduled_date = iso(state.selected);
        render();
        try {
          await api("PATCH", `/v2/day/tasks/${task.id}`, {
            scheduled_date: iso(state.selected),
            start_time: minToTime(newStart)
          });
        } catch (e) {
          // Put it back where it came from; the move never happened.
          task.start_time = wasTime;
          task.scheduled_date = wasDate;
          render();
          showError(e);
        }
      } else {
        render();
      }
    }

    row.addEventListener("pointerup", () => finish(true));
    row.addEventListener("pointercancel", () => finish(false));
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  async function toggleDone(task, row) {
    const next = !task.done;
    task.done = next;
    row.classList.toggle("done", next);
    const ring = row.querySelector(".ring");
    if (ring) ring.classList.toggle("checked", next);
    // Two layouts, two class names: a normal row has .icon, a row sharing
    // its time with another has .ov-icon. A missing element must not throw —
    // the catch below reads any failure as the save failing and puts the tick
    // back, so a null here silently undid a tick that was never even sent.
    const icon = row.querySelector(".icon, .ov-icon");
    if (icon) icon.textContent = next ? "" : emojiFor(task.title);
    if (navigator.vibrate) navigator.vibrate(10);
    renderHeader();
    try {
      await api("PATCH", `/v2/day/tasks/${task.id}`, { done: next });
    } catch (e) {
      task.done = !next;
      showError(e);
      loadDay({ keepScroll: true }).catch(() => {});
    }
  }

  /* ---------- inbox tray ---------- */

  function renderInbox(items) {
    const box = $("inbox");
    box.classList.toggle("hidden", items.length === 0);
    const list = $("inbox-list");
    list.innerHTML = "";
    for (const task of items) {
      const card = document.createElement("div");
      card.className = "inbox-card";
      if (task.done) card.style.opacity = "0.55";
      card.innerHTML = `
        <div class="icon" style="background:${pastelFor(task.title)}">${task.done ? "✓" : emojiFor(task.title)}</div>
        <div class="t"${task.done ? ' style="text-decoration:line-through"' : ""}>${escapeHtml(task.title)}</div>`;
      if (!task.done) {
        const clock = document.createElement("button");
        clock.className = "clock";
        clock.textContent = "Schedule";
        clock.addEventListener("click", () => scheduleNext(task));
        card.appendChild(clock);
        card.querySelector(".icon").addEventListener("click", () =>
          api("PATCH", `/v2/day/tasks/${task.id}`, { done: true }).then(() => loadDay({ keepScroll: true })).catch(showError)
        );
        card.querySelector(".t").addEventListener("click", () => openEdit(task));
      }
      list.appendChild(card);
    }
  }

  async function scheduleNext(task) {
    const blocks = state.items
      .filter((t) => t.start_time)
      .map((t) => ({
        start: timeToMin(t.start_time),
        end: timeToMin(t.start_time) + (t.estimated_minutes || 30),
      }))
      .sort((a, b) => a.start - b.start);
    const now = new Date();
    let m = now.getHours() * 60 + now.getMinutes();
    if (now.getHours() < 4) m += 24 * 60;
    let candidate = sameDay(state.selected, getLogicalToday())
      ? Math.ceil(m / 30) * 30
      : 9 * 60;
    const need = task.estimated_minutes || 30;
    for (const slot of blocks) {
      if (candidate + need <= slot.start) break;
      if (candidate < slot.end) candidate = slot.end;
    }
    candidate = Math.min(candidate, 27 * 60);
    // Instead of auto-saving, open the modal with the calculated candidate time prefilled
    $("new-id").value = task.id;
    $("new-title").value = task.title;
    $("new-date").value = task.scheduled_date || iso(state.selected);
    $("new-time").value = minToTime(candidate);
    $("new-est").value = task.estimated_minutes || "";
    $("sheet").classList.remove("hidden");
    $("sheet-backdrop").classList.remove("hidden");
    $("new-time").focus();
  }

  /* ---------- add / edit sheet ---------- */

  let sheetMinutes = 30;

  function openSheet(prefillMin) {
    state.editing = null;
    $("sheet-title").textContent = "New task";
    $("sheet-save").textContent = "Add to day";
    $("sheet-delete").classList.add("hidden");
    $("sheet-split").classList.add("hidden");
    $("new-title").value = "";
    $("new-title").disabled = false;
    $("new-date").value = iso(state.selected);
    $("new-time").value = prefillMin != null ? minToTime(prefillMin) : "";
    setDuration(30);
    openSheetEl();
    $("new-title").focus();
  }

  function openEdit(task) {
    state.editing = task.id;
    $("sheet-title").textContent = "Edit task";
    $("sheet-save").textContent = "Save";
    $("sheet-delete").classList.remove("hidden");
    $("sheet-split").classList.remove("hidden");
    $("new-title").value = task.title;
    $("new-title").disabled = false;
    $("new-date").value = task.scheduled_date || iso(state.selected);
    $("new-time").value = task.start_time ? task.start_time.slice(0, 5) : "";
    setDuration(task.estimated_minutes || 30);
    openSheetEl();
  }

  function openSheetEl() {
    $("sheet").classList.remove("hidden");
    $("sheet-backdrop").classList.remove("hidden");
  }

  function setDuration(min) {
    sheetMinutes = min;
    let matched = false;
    for (const b of $("dur-chips").children) {
      const on = Number(b.dataset.min) === min;
      b.classList.toggle("on", on);
      if (on) matched = true;
    }
    // if custom duration, leave the nearest chip highlighted off; save still uses sheetMinutes
    if (!matched) for (const b of $("dur-chips").children) b.classList.remove("on");
  }

  $("fab").addEventListener("click", () => openSheet(null));
  $("sheet-backdrop").addEventListener("click", closeSheet);


  // Split the block in half: half stays where it is, half goes to the Inbox
  // for you to place. The total time is unchanged — an hour split twice is
  // still an hour, not two.
  $("sheet-split").addEventListener("click", async () => {
    if (!state.editing) return;
    const task = state.items.find(t => t.id === state.editing);
    if (!task) return;

    // A habit is a rule, not a row, so there is nothing to split into slots.
    if (task.is_habit) { toast("Habits can't be split"); return; }

    const date = task.scheduled_date || iso(state.selected);
    const total = task.estimated_minutes || 30;
    const keep = Math.round(total / 2);
    const moved = total - keep;
    if (moved < 1) { toast("Too short to split"); return; }

    try {
      if (task.parent_task_id) {
        // Already a slot: shrink it and put a sibling alongside.
        await api("PATCH", "/v2/day/tasks/" + task.id, { estimated_minutes: keep });
        await api("POST", "/v2/day/tasks", {
          title: task.title,
          project_id: task.project_id || null,
          date: date,
          estimated_minutes: moved,
          parent_task_id: task.parent_task_id
        });
      } else {
        // First split. The task itself stops appearing on the timeline once it
        // has slots, so one slot has to inherit its time or the block would
        // simply vanish from the day.
        await api("POST", "/v2/day/tasks", {
          title: task.title,
          project_id: task.project_id || null,
          date: date,
          start_time: task.start_time || null,
          estimated_minutes: keep,
          parent_task_id: task.id
        });
        await api("POST", "/v2/day/tasks", {
          title: task.title,
          project_id: task.project_id || null,
          date: date,
          estimated_minutes: moved,
          parent_task_id: task.id
        });
      }
      closeSheet();
      await loadDay({ keepScroll: true });
    } catch(e) {
      showError(e);
    }
  });

  function closeSheet() {
    $("sheet").classList.add("hidden");
    $("sheet-backdrop").classList.add("hidden");
    state.editing = null;
  }

  $("dur-chips").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    setDuration(Number(btn.dataset.min));
    $("custom-dur").value = "";
  });
  
  $("custom-dur").addEventListener("input", (e) => {
    const val = parseInt(e.target.value);
    if (!isNaN(val) && val > 0) {
       setDuration(val);
    }
  });

  $("sheet-save").addEventListener("click", async (e) => {
    if (e.target.disabled) return;
    const title = $("new-title").value.trim();
    if (!title) return;
    e.target.disabled = true;
    const time = $("new-time").value || null;
    const dateVal = $("new-date").value || iso(state.selected);
    const editing = state.editing;
    const staysHere = dateVal === iso(state.selected);

    // Paint the change and close the sheet before asking the server. Waiting
    // for the save and then reloading the whole day meant two round trips
    // before anything moved, which on a cold start is several seconds.
    closeSheet();

    if (editing) {
      const item = state.items.find((t) => t.id === editing);
      const before = item ? { ...item } : null;
      if (item) {
        item.title = title;
        item.scheduled_date = dateVal;
        item.start_time = time;
        item.estimated_minutes = sheetMinutes;
      }
      render();
      toast("Saved ✓");
      try {
        await api("PATCH", `/v2/day/tasks/${editing}`, {
          title,
          scheduled_date: dateVal,
          start_time: time,
          estimated_minutes: sheetMinutes,
        });
        // Moved to another day: it belongs on that screen now, not this one.
        if (!staysHere) await loadDay({ keepScroll: true });
      } catch (err) {
        if (item && before) Object.assign(item, before);
        render();
        showError(err);
      } finally {
        $("sheet-save").disabled = false;
      }
      return;
    }

    // A new task has no id until the server gives it one. Show it straight
    // away under a temporary id, and mark it pending so it cannot be ticked or
    // dragged before it exists.
    const draft = {
      id: `pending:${Date.now()}`,
      title,
      status: "todo",
      done: false,
      start_time: time,
      estimated_minutes: sheetMinutes,
      priority: "medium",
      due_date: null,
      scheduled_date: dateVal,
      notes: null,
      project_id: null,
      parent_task_id: null,
      pending: true,
    };
    if (staysHere) {
      state.items.push(draft);
      render();
    }
    toast("Added ✓");
    try {
      const created = await api("POST", "/v2/day/tasks", {
        title,
        date: dateVal,
        start_time: time,
        estimated_minutes: sheetMinutes,
      });
      const row = created && created.data && created.data.task;
      const at = state.items.indexOf(draft);
      if (staysHere && at !== -1) {
        if (row) {
          state.items[at] = { ...draft, ...row, done: ["done", "skipped"].includes(row.status), pending: false };
        } else {
          state.items.splice(at, 1);
        }
        render();
        if (!row) await loadDay({ keepScroll: true });
      }
    } catch (err) {
      const at = state.items.indexOf(draft);
      if (at !== -1) state.items.splice(at, 1);
      render();
      showError(err);
    } finally {
      $("sheet-save").disabled = false;
    }
  });

  $("sheet-delete").addEventListener("click", async () => {
    if (!state.editing) return;
    const id = state.editing;
    closeSheet();
    // Take it off the screen now and tell the server after; put it back in
    // its old place if the delete does not go through.
    const at = state.items.findIndex((t) => t.id === id);
    const removed = at !== -1 ? state.items.splice(at, 1)[0] : null;
    render();
    toast("Deleted");
    try {
      await api("DELETE", `/v2/day/tasks/${id}`);
    } catch (e) {
      if (removed) {
        state.items.splice(at, 0, removed);
        render();
      }
      showError(e);
    } finally {
      $("sheet-save").disabled = false;
    }
  });

  /* ---------- toast / errors ---------- */

  let toastTimer = null;

  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 2000);
  }

  function showError(e) {
    if (String(e.message) !== "unauthorized") toast(e.message || "Something failed");
  }

  /* ---------- boot ---------- */

  if ("serviceWorker" in navigator) {
    let reloadedForUpdate = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (reloadedForUpdate) return;
      reloadedForUpdate = true;
      location.reload();
    });
    navigator.serviceWorker.register("sw.js").then((reg) => reg.update()).catch(() => {});
  }

  // While a task is lifted for reschedule, block the page from scrolling.
  // This must be a NON-passive listener or iOS ignores preventDefault — it is
  // what lets a hold-then-drag move the event instead of scrolling the page.
  document.addEventListener(
    "touchmove",
    (e) => {
      if (dragging) e.preventDefault();
    },
    { passive: false }
  );

  // Swipe left/right anywhere on the day to step to the next/previous date.
  (function enableDateSwipe() {
    const surface = document.querySelector("main");
    let sx = 0, sy = 0, tracking = false;
    surface.addEventListener("touchstart", (e) => {
      if (e.touches.length !== 1 || dragging) {
        tracking = false;
        return;
      }
      sx = e.touches[0].clientX;
      sy = e.touches[0].clientY;
      tracking = true;
    }, { passive: true });
    surface.addEventListener("touchend", (e) => {
      if (!tracking) return;
      tracking = false;
      const t = e.changedTouches[0];
      const dx = t.clientX - sx;
      const dy = t.clientY - sy;
      // clearly horizontal and long enough → change the day
      if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.6) {
        shiftDays(dx < 0 ? 1 : -1); // swipe left = next day
      }
    }, { passive: true });
  })();

  setInterval(() => {
    if (dragging) return; // never repaint mid-drag
    if (Date.now() - lastInteraction < 4000) return; // let a gesture settle
    if (!document.hidden && key() && $("sheet").classList.contains("hidden")) {
      loadDay({ keepScroll: true }).catch(() => {});
    }
  }, 3600000);

  setInterval(() => {
    if (sameDay(state.selected, getLogicalToday())) {
      const nl = document.querySelector(".now-line");
      if (nl) {
        const timed = state.items.filter((t) => t.start_time);
        const mins = timed.map((t) => timeToMin(t.start_time));
        const startH = timed.length ? Math.min(0, ...mins.map((m) => Math.floor(m / 60))) : 0;
        const top0 = startH * 60;
        const now = new Date();
        let m = now.getHours() * 60 + now.getMinutes();
        if (now.getHours() < 4) m += 24 * 60;
        nl.style.top = `${(m - top0) * PX_PER_MIN}px`;
      }
    }
  }, 60000);

  // Coming back to the app should show the new day if you left it open
  // overnight, but must not undo a day you deliberately chose. This fires on
  // every foreground — resuming, dismissing the keyboard, a glance at another
  // app — so it only jumps when the date has genuinely rolled over since the
  // last time the app was on screen.
  let lastSeenToday = iso(getLogicalToday());

  document.addEventListener("visibilitychange", () => {
    if (document.hidden || !key()) return;
    const today = getLogicalToday();
    const rolledOver = iso(today) !== lastSeenToday;
    lastSeenToday = iso(today);
    if (rolledOver && !sameDay(state.selected, today)) {
      goToDate(today);
      return;
    }
    loadDay({ keepScroll: true }).catch(showError);
  });

  if (!key()) {
    showGate(false);
  } else {
    loadDay().catch(showError);
  }
})();
