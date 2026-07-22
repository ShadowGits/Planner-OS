/* Structured-style day planner over the /v2/day API.
   A flowing list (not a scaled calendar): tasks stack as rows on a dotted
   spine, free gaps collapse into a "+ Add Task" row. All state lives in
   Postgres; this file only renders and reports. */

(() => {
  "use strict";

  const SNAP_MIN = 5;
  const GAP_MIN = 15;
  const PX_PER_MIN = 1.8; // proportional: an hour is a real, scrollable hour
  const MIN_ROW_PX = 52;
  const KEY_STORE = "day-planner-key";

  const $ = (id) => document.getElementById(id);

  const state = {
    selected: startOfDay(new Date()),
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
    return res.json();
  }

  // A tiny per-day cache so swiping through the week is instant. Each entry
  // holds that day's tasks; we still re-fetch in the background on show so the
  // screen is never stale (see goToDate).
  const dayCache = new Map(); // iso date -> { items, tz, at }
  const PREFETCH_FRESH_MS = 30000;

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
    const today = startOfDay(new Date());
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
      if (sameDay(d, new Date())) pill.classList.add("today");
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
    let startH = timed.length ? Math.min(7, ...mins.map((m) => Math.floor(m / 60))) : 7;
    let endH = timed.length ? Math.max(22, ...ends.map((m) => Math.ceil(m / 60) + 1)) : 22;
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

    if (sameDay(state.selected, new Date())) {
      const now = new Date();
      const m = now.getHours() * 60 + now.getMinutes();
      if (m >= top0 && m <= endH * 60) {
        const nl = document.createElement("div");
        nl.className = "now-line";
        nl.style.top = `${(m - top0) * PX_PER_MIN}px`;
        list.appendChild(nl);
      }
    }

    for (let i = 0; i < timed.length; i++) {
      list.appendChild(taskRow(timed[i], top0));
      const nextStart = i + 1 < timed.length ? mins[i + 1] : null;
      if (nextStart !== null && nextStart - ends[i] >= GAP_MIN) {
        list.appendChild(gapRow(ends[i], nextStart, top0));
      }
    }
  }

  function taskRow(task, top0) {
    const start = timeToMin(task.start_time);
    const dur = task.estimated_minutes || 30;
    const row = document.createElement("div");
    row.className = "row" + (task.done ? " done" : "");
    row.style.top = `${(start - top0) * PX_PER_MIN}px`;
    row.style.height = `${Math.max(MIN_ROW_PX, dur * PX_PER_MIN)}px`;
    row.style.setProperty("--ring", ringFor(task.title));

    const recur = task.recurrence_key ? " ↻" : "";
    row.innerHTML = `
      <div class="rail"><div class="icon" style="background:${pastelFor(task.title)}">${emojiFor(task.title)}</div></div>
      <div class="body">
        <div class="meta">${fmtClock(start)} – ${fmtClock(start + dur)} (${fmtDur(dur)})${recur}</div>
        <div class="title">${escapeHtml(task.title)}</div>
      </div>
      <button class="ring${task.done ? " checked" : ""}" aria-label="Toggle done"></button>`;

    row.querySelector(".ring").addEventListener("click", (e) => {
      e.stopPropagation();
      toggleDone(task, row);
    });
    row.addEventListener("click", (e) => {
      if (e.target.closest(".ring")) return;
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
    const slot = Math.round(fromMin / SNAP_MIN) * SNAP_MIN;
    el.querySelector(".gap-add").addEventListener("click", () => openSheet(slot));
    return el;
  }

  /* Reschedule by grabbing the icon (the .rail handle). Only the handle is
     touch-action:none, so dragging it can never be mistaken for a scroll,
     while the rest of the row scrolls natively. No long-press needed:
     move the handle a few px and the row lifts and follows the finger. */
  function attachDrag(row, task, top0) {
    const handle = row.querySelector(".rail");
    let lifted = false;
    let originY = 0;
    let originTop = 0;
    let pointerId = null;
    let badge = null;
    let newStart = null;

    handle.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      // Apple Pencil emits hover events with no contact; ignore them.
      if (e.pointerType === "pen" && e.buttons === 0) return;
      pointerId = e.pointerId;
      originY = e.clientY;
      originTop = parseFloat(row.style.top);
      lifted = false;
    });

    handle.addEventListener("pointermove", (e) => {
      if (e.pointerId !== pointerId) return;
      if (!lifted) {
        if (Math.abs(e.clientY - originY) < 5) return; // a tap, not a drag
        lifted = true;
        dragging = true;
        row.classList.add("lifted");
        try {
          handle.setPointerCapture(pointerId);
        } catch (_) {}
        if (navigator.vibrate) navigator.vibrate(12);
        badge = document.createElement("div");
        badge.className = "drag-badge";
        row.appendChild(badge);
        updateBadge(originTop);
      }
      e.preventDefault();
      const top = Math.max(0, originTop + (e.clientY - originY));
      row.style.top = `${top}px`;
      updateBadge(top);
    });

    function updateBadge(top) {
      const raw = top / PX_PER_MIN + top0;
      newStart = Math.min(Math.max(Math.round(raw / SNAP_MIN) * SNAP_MIN, 0), 24 * 60 - 5);
      if (badge) badge.textContent = fmtClock(newStart);
    }

    async function finish(save) {
      if (pointerId !== null) {
        try {
          handle.releasePointerCapture(pointerId);
        } catch (_) {}
        pointerId = null;
      }
      if (!lifted) return; // a plain tap → the row's click handler opens edit
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
        try {
          await api("PATCH", `/v2/day/tasks/${task.id}`, { start_time: minToTime(newStart) });
          task.start_time = minToTime(newStart);
          render();
        } catch (e) {
          showError(e);
          loadDay().catch(() => {});
        }
      } else {
        render();
      }
    }

    handle.addEventListener("pointerup", () => finish(true));
    handle.addEventListener("pointercancel", () => finish(false));
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
    ring.classList.toggle("checked", next);
    row.querySelector(".icon").textContent = next ? "" : emojiFor(task.title);
    if (navigator.vibrate) navigator.vibrate(10);
    renderHeader();
    try {
      await api("PATCH", `/v2/day/tasks/${task.id}`, { done: next });
    } catch (e) {
      task.done = !next;
      showError(e);
      loadDay().catch(() => {});
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
          api("PATCH", `/v2/day/tasks/${task.id}`, { done: true }).then(loadDay).catch(showError)
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
    let candidate = sameDay(state.selected, now)
      ? Math.ceil((now.getHours() * 60 + now.getMinutes()) / 30) * 30
      : 9 * 60;
    const need = task.estimated_minutes || 30;
    for (const slot of blocks) {
      if (candidate + need <= slot.start) break;
      if (candidate < slot.end) candidate = slot.end;
    }
    candidate = Math.min(candidate, 23 * 60);
    try {
      await api("PATCH", `/v2/day/tasks/${task.id}`, { start_time: minToTime(candidate) });
      await loadDay();
    } catch (e) {
      showError(e);
    }
  }

  /* ---------- add / edit sheet ---------- */

  let sheetMinutes = 30;

  function openSheet(prefillMin) {
    state.editing = null;
    $("sheet-title").textContent = "New task";
    $("sheet-save").textContent = "Add to day";
    $("sheet-delete").classList.add("hidden");
    $("new-title").value = "";
    $("new-title").disabled = false;
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
    $("new-title").value = task.title;
    $("new-title").disabled = false;
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

  function closeSheet() {
    $("sheet").classList.add("hidden");
    $("sheet-backdrop").classList.add("hidden");
    state.editing = null;
  }

  $("dur-chips").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    setDuration(Number(btn.dataset.min));
  });

  $("sheet-save").addEventListener("click", async () => {
    const title = $("new-title").value.trim();
    if (!title) return;
    const time = $("new-time").value || null;
    try {
      if (state.editing) {
        await api("PATCH", `/v2/day/tasks/${state.editing}`, {
          title,
          start_time: time,
          estimated_minutes: sheetMinutes,
        });
      } else {
        await api("POST", "/v2/day/tasks", {
          title,
          date: iso(state.selected),
          start_time: time,
          estimated_minutes: sheetMinutes,
        });
      }
      closeSheet();
      toast(state.editing ? "Saved ✓" : "Added ✓");
      await loadDay();
    } catch (e) {
      showError(e);
    }
  });

  $("sheet-delete").addEventListener("click", async () => {
    if (!state.editing) return;
    const id = state.editing;
    closeSheet();
    try {
      await api("DELETE", `/v2/day/tasks/${id}`);
      toast("Deleted");
      await loadDay();
    } catch (e) {
      showError(e);
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
  }, 60000);

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && key()) loadDay({ keepScroll: true }).catch(showError);
  });

  if (!key()) {
    showGate(false);
  } else {
    loadDay().catch(showError);
  }
})();
