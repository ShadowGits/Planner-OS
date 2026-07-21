/* Structured-style day planner over the /v2/day API.
   All state lives in Postgres; this file only renders and reports. */

(() => {
  "use strict";

  const PX_PER_MIN = 1.15;
  const MIN_CARD_PX = 56;
  const SNAP_MIN = 5;
  const KEY_STORE = "day-planner-key";

  const $ = (id) => document.getElementById(id);

  const state = {
    selected: startOfDay(new Date()),
    items: [],
    tz: null,
    dragging: false,
  };

  /* ---------- helpers ---------- */

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
    d.setHours(Math.floor(min / 60), min % 60, 0, 0);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  function fmtHour(min) {
    const d = new Date();
    d.setHours(Math.floor(min / 60), 0, 0, 0);
    return d.toLocaleTimeString([], { hour: "numeric" });
  }

  const EMOJI_RULES = [
    [/german|deutsch|a1|a2|duolingo/i, "🇩🇪"],
    [/gym|workout|lift|train/i, "🏋️"],
    [/run|jog|walk/i, "🏃"],
    [/math|calc|algebra|geometry/i, "📐"],
    [/study|learn|read|course|revise/i, "📚"],
    [/call|phone|hr\b/i, "📞"],
    [/mail|email|reply/i, "✉️"],
    [/visa|embassy|passport|apostille/i, "🛂"],
    [/college|uni|apply|application|sop|lor/i, "🎓"],
    [/doc|form|paper|print/i, "📄"],
    [/bank|money|finance|pay|invest|tax/i, "💰"],
    [/food|cook|meal|lunch|dinner|breakfast/i, "🍳"],
    [/clean|laundry|tidy/i, "🧹"],
    [/meet|sync|standup|interview/i, "👥"],
    [/code|build|deploy|bug|dev/i, "💻"],
    [/write|journal|blog|note/i, "✍️"],
    [/ielts|toefl|test|exam/i, "📝"],
    [/sleep|rest|nap/i, "😴"],
  ];

  const PASTELS = [
    "#ffe3e0", "#fff0d4", "#e5f4d7", "#d8f0f4", "#e2e7ff",
    "#f4e0f4", "#e0f4ea", "#fde8d2", "#e8e4fb", "#d9f0ff",
  ];
  const PASTELS_DARK = [
    "#4b2f2d", "#4b3e26", "#33452c", "#2b4348", "#2f3555",
    "#472f47", "#2c4639", "#4a3a27", "#383152", "#28404f",
  ];

  function emojiFor(title) {
    for (const [re, e] of EMOJI_RULES) if (re.test(title)) return e;
    return "📌";
  }

  function pastelFor(title) {
    let h = 0;
    for (const c of title) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    return (dark ? PASTELS_DARK : PASTELS)[h % PASTELS.length];
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

  async function loadDay() {
    const out = await api("GET", `/v2/day?date=${iso(state.selected)}`);
    state.items = out.data.items;
    state.tz = out.data.timezone;
    render();
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
    $("day-title").textContent =
      names[diff] ??
      state.selected.toLocaleDateString([], { weekday: "long" });
    $("day-subtitle").textContent = state.selected.toLocaleDateString([], {
      weekday: diff in names ? "long" : undefined,
      day: "numeric",
      month: "long",
    });

    const done = state.items.filter((t) => t.done).length;
    const total = state.items.length;
    const r = 19;
    const circ = 2 * Math.PI * r;
    const fg = $("ring-fg");
    fg.style.strokeDasharray = circ;
    fg.style.strokeDashoffset = total ? circ * (1 - done / total) : circ;
    $("ring-label").textContent = `${done}/${total}`;
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
      pill.addEventListener("click", () => {
        state.selected = startOfDay(d);
        loadDay().catch(showError);
      });
      strip.appendChild(pill);
    }
  }

  $("week-prev").addEventListener("click", () => shiftDays(-7));
  $("week-next").addEventListener("click", () => shiftDays(7));

  function shiftDays(n) {
    const d = new Date(state.selected);
    d.setDate(d.getDate() + n);
    state.selected = startOfDay(d);
    loadDay().catch(showError);
  }

  /* ---------- timeline ---------- */

  function render() {
    renderHeader();
    renderWeek();

    const timed = state.items.filter((t) => t.start_time);
    const inbox = state.items.filter((t) => !t.start_time);

    renderInbox(inbox);

    const grid = $("grid");
    grid.innerHTML = "";
    $("empty").classList.toggle("hidden", state.items.length > 0);
    if (!timed.length && !inbox.length) {
      grid.style.height = "0px";
      return;
    }

    const mins = timed.map((t) => timeToMin(t.start_time));
    const ends = timed.map(
      (t, i) => mins[i] + (t.estimated_minutes || 30)
    );
    let startH = Math.min(7, ...mins.map((m) => Math.floor(m / 60)));
    let endH = Math.max(22, ...ends.map((m) => Math.ceil(m / 60) + 1));
    if (!timed.length) [startH, endH] = [7, 22];

    grid.style.height = `${(endH - startH) * 60 * PX_PER_MIN + 20}px`;

    const spine = document.createElement("div");
    spine.className = "spine";
    grid.appendChild(spine);

    for (let h = startH; h <= endH; h++) {
      const row = document.createElement("div");
      row.className = "hour";
      row.style.top = `${(h - startH) * 60 * PX_PER_MIN}px`;
      row.innerHTML = `<span>${fmtHour(h * 60)}</span>`;
      grid.appendChild(row);
    }

    if (sameDay(state.selected, new Date())) {
      const now = new Date();
      const m = now.getHours() * 60 + now.getMinutes();
      if (m >= startH * 60 && m <= endH * 60) {
        const line = document.createElement("div");
        line.className = "now-line";
        line.style.top = `${(m - startH * 60) * PX_PER_MIN}px`;
        grid.appendChild(line);
      }
    }

    for (const task of timed) grid.appendChild(taskCard(task, startH));
  }

  function taskCard(task, startH) {
    const start = timeToMin(task.start_time);
    const dur = task.estimated_minutes || 30;
    const el = document.createElement("div");
    el.className = "task" + (task.done ? " done" : "");
    el.style.top = `${(start - startH * 60) * PX_PER_MIN}px`;
    el.style.height = `${Math.max(MIN_CARD_PX, dur * PX_PER_MIN)}px`;
    el.dataset.id = task.id;

    const node = document.createElement("button");
    node.className = "node" + (task.done ? " checked" : "");
    node.style.background = task.done ? "" : pastelFor(task.title);
    node.textContent = task.done ? "✓" : emojiFor(task.title);
    node.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleDone(task, node, el);
    });
    el.appendChild(node);

    const title = document.createElement("div");
    title.className = "title";
    title.textContent = task.title;
    el.appendChild(title);

    const when = document.createElement("div");
    when.className = "when";
    when.textContent = `${fmtClock(start)} – ${fmtClock(start + dur)}`;
    el.appendChild(when);

    attachDrag(el, task, startH);
    return el;
  }

  async function toggleDone(task, node, card) {
    const next = !task.done;
    task.done = next;
    node.classList.toggle("checked", next);
    node.textContent = next ? "✓" : emojiFor(task.title);
    node.style.background = next ? "" : pastelFor(task.title);
    card.classList.toggle("done", next);
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

  /* press-and-hold to lift, drag vertically, snap, save.
     Cards have touch-action:none so the browser never steals the gesture for
     a page scroll. We capture the pointer on down, then decide: a quick
     vertical move before the hold fires means "scroll" (we pan the page
     ourselves), a held-still touch means "drag". */
  function attachDrag(el, task, startH) {
    let holdTimer = null;
    let lifted = false;
    let scrolling = false;
    let originY = 0;
    let originTop = 0;
    let lastY = 0;
    let pointerId = null;
    let badge = null;
    let newStart = null;

    el.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".node")) return;
      if (e.pointerType === "mouse" && e.button !== 0) return;
      originY = e.clientY;
      lastY = e.clientY;
      originTop = parseFloat(el.style.top);
      pointerId = e.pointerId;
      scrolling = false;
      try {
        el.setPointerCapture(e.pointerId);
      } catch (_) {}
      holdTimer = setTimeout(() => {
        lifted = true;
        state.dragging = true;
        el.classList.add("lifted");
        if (navigator.vibrate) navigator.vibrate(15);
        badge = document.createElement("div");
        badge.className = "drag-badge";
        el.appendChild(badge);
        updateBadge(parseFloat(el.style.top));
      }, 240);
    });

    el.addEventListener("pointermove", (e) => {
      if (!lifted) {
        const dy = e.clientY - originY;
        // Moved before the hold fired → this is a scroll, not a drag.
        if (!scrolling && Math.abs(dy) > 8) {
          scrolling = true;
          clearTimeout(holdTimer);
          holdTimer = null;
        }
        if (scrolling) {
          // touch-action is none, so pan the page by hand to mimic scroll.
          window.scrollBy(0, lastY - e.clientY);
          lastY = e.clientY;
        }
        return;
      }
      e.preventDefault();
      const top = Math.max(0, originTop + (e.clientY - originY));
      el.style.top = `${top}px`;
      updateBadge(top);
    });

    function updateBadge(top) {
      const raw = top / PX_PER_MIN + startH * 60;
      newStart = Math.round(raw / SNAP_MIN) * SNAP_MIN;
      newStart = Math.min(Math.max(newStart, 0), 24 * 60 - 5);
      if (badge) badge.textContent = fmtClock(newStart);
    }

    async function finish(save) {
      clearTimeout(holdTimer);
      holdTimer = null;
      scrolling = false;
      if (pointerId !== null) {
        try {
          el.releasePointerCapture(pointerId);
        } catch (_) {}
        pointerId = null;
      }
      if (!lifted) return;
      lifted = false;
      state.dragging = false;
      el.classList.remove("lifted");
      if (badge) {
        badge.remove();
        badge = null;
      }
      if (save && newStart !== null && minToTime(newStart) !== task.start_time.slice(0, 5)) {
        el.style.top = `${(newStart - startH * 60) * PX_PER_MIN}px`;
        try {
          await api("PATCH", `/v2/day/tasks/${task.id}`, {
            start_time: minToTime(newStart),
          });
          task.start_time = minToTime(newStart);
          render();
        } catch (e) {
          showError(e);
          loadDay().catch(() => {});
        }
      } else {
        el.style.top = `${originTop}px`;
      }
    }

    el.addEventListener("pointerup", () => finish(true));
    el.addEventListener("pointercancel", () => finish(false));
  }

  /* ---------- inbox ---------- */

  function renderInbox(items) {
    const box = $("inbox");
    box.classList.toggle("hidden", items.length === 0);
    const list = $("inbox-list");
    list.innerHTML = "";
    for (const task of items) {
      const card = document.createElement("div");
      card.className = "inbox-card";
      if (task.done) card.style.opacity = "0.6";
      const emoji = document.createElement("div");
      emoji.className = "emoji";
      emoji.style.background = pastelFor(task.title);
      emoji.textContent = task.done ? "✓" : emojiFor(task.title);
      const t = document.createElement("div");
      t.className = "t";
      t.textContent = task.title;
      if (task.done) t.style.textDecoration = "line-through";
      card.appendChild(emoji);
      card.appendChild(t);
      if (!task.done) {
        const clock = document.createElement("button");
        clock.className = "clock";
        clock.textContent = "Schedule";
        clock.addEventListener("click", () => scheduleNext(task));
        card.appendChild(clock);
        emoji.addEventListener("click", () =>
          api("PATCH", `/v2/day/tasks/${task.id}`, { done: true })
            .then(loadDay)
            .catch(showError)
        );
      }
      list.appendChild(card);
    }
  }

  async function scheduleNext(task) {
    const timed = state.items
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
    for (const slot of timed) {
      if (candidate + need <= slot.start) break;
      if (candidate < slot.end) candidate = slot.end;
    }
    candidate = Math.min(candidate, 23 * 60);
    try {
      await api("PATCH", `/v2/day/tasks/${task.id}`, {
        start_time: minToTime(candidate),
      });
      await loadDay();
    } catch (e) {
      showError(e);
    }
  }

  /* ---------- add sheet ---------- */

  let sheetMinutes = 30;

  $("fab").addEventListener("click", () => {
    $("sheet").classList.remove("hidden");
    $("sheet-backdrop").classList.remove("hidden");
    $("new-title").value = "";
    $("new-time").value = "";
    $("new-title").focus();
  });

  $("sheet-backdrop").addEventListener("click", closeSheet);

  function closeSheet() {
    $("sheet").classList.add("hidden");
    $("sheet-backdrop").classList.add("hidden");
  }

  $("dur-chips").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    for (const b of $("dur-chips").children) b.classList.remove("on");
    btn.classList.add("on");
    sheetMinutes = Number(btn.dataset.min);
  });

  $("sheet-save").addEventListener("click", async () => {
    const title = $("new-title").value.trim();
    if (!title) return;
    try {
      await api("POST", "/v2/day/tasks", {
        title,
        date: iso(state.selected),
        start_time: $("new-time").value || null,
        estimated_minutes: sheetMinutes,
      });
      closeSheet();
      toast("Added ✓");
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
    toastTimer = setTimeout(() => el.classList.add("hidden"), 2200);
  }

  function showError(e) {
    if (String(e.message) !== "unauthorized") toast(e.message || "Something failed");
  }

  /* ---------- boot ---------- */

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  setInterval(() => {
    if (!state.dragging && !document.hidden) loadDay().catch(() => {});
  }, 60000);

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && key()) loadDay().catch(showError);
  });

  if (!key()) {
    showGate(false);
    render();
  } else {
    loadDay().catch(showError);
  }
})();
