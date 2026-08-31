/* Regression tests for the day screen.
 *
 * Every case here is a bug that shipped. The point is not coverage for its own
 * sake — it is that each of these was invisible to the Python suite because it
 * lived entirely in the browser.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { boot, settle, task, today, rows, rowFor } from "./harness.mjs";

/* ---------- ticking ---------- */

test("ticking a task sends the change and keeps it ticked", async (t) => {
  const { doc, window, calls, close } = await boot({
    items: [task({ id: "a", title: "Shower", start_time: "07:00" })],
  });
  t.after(close);

  const row = rowFor(doc, "Shower");
  row.querySelector(".ring").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await settle(window);

  const patch = calls.find((c) => c.method === "PATCH");
  assert.ok(patch, "no PATCH reached the server");
  assert.equal(patch.path, "/v2/day/tasks/a");
  assert.deepEqual(patch.body, { done: true });
  assert.ok(row.classList.contains("done"), "the row did not stay ticked");
  assert.ok(row.querySelector(".ring").classList.contains("checked"));
});

test("ticking one of two tasks at the same time still saves", async (t) => {
  // The bug: two tasks booked at once render as side-by-side columns, whose
  // markup names the icon differently. Ticking one reached for the icon by the
  // other layout's name, threw, and the catch treated it as a failed save —
  // so the tick was reverted and no request was ever sent.
  const { doc, window, calls, close } = await boot({
    items: [
      task({ id: "shower", title: "Shower", start_time: "07:00", estimated_minutes: 30 }),
      task({ id: "skin", title: "Skin care", start_time: "07:15", estimated_minutes: 20 }),
    ],
  });
  t.after(close);

  const shower = rowFor(doc, "Shower");
  assert.ok(shower.classList.contains("overlap"), "expected the side-by-side layout");

  shower.querySelector(".ring").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await settle(window);

  const patch = calls.find((c) => c.method === "PATCH");
  assert.ok(patch, "ticking an overlapping task sent nothing to the server");
  assert.deepEqual(patch.body, { done: true });
  assert.ok(shower.classList.contains("done"), "the tick was undone on screen");
});

test("a failed save puts the tick back", async (t) => {
  const { doc, window, close } = await boot({
    items: [task({ id: "a", title: "Shower", start_time: "07:00" })],
    onRequest: ({ method }) =>
      method === "PATCH" ? { success: false, message: "nope", data: {} } : null,
  });
  t.after(close);

  rowFor(doc, "Shower").querySelector(".ring")
    .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await settle(window);

  // A failure redraws the day, so look at what is on screen now rather than
  // at the element we clicked, which has since been replaced.
  const redrawn = rowFor(doc, "Shower");
  assert.equal(redrawn.classList.contains("done"), false, "the screen claimed a save that failed");
  assert.equal(redrawn.querySelector(".ring").classList.contains("checked"), false);
});

/* ---------- overlapping layout ---------- */

test("tasks at the same time get their own column and their own tick", async (t) => {
  const { doc, close } = await boot({
    items: [
      task({ id: "a", title: "Gym", start_time: "17:30", estimated_minutes: 120 }),
      task({ id: "b", title: "Maths", start_time: "17:45", estimated_minutes: 45 }),
    ],
  });
  t.after(close);

  const [gym, maths] = [rowFor(doc, "Gym"), rowFor(doc, "Maths")];
  for (const row of [gym, maths]) {
    assert.ok(row.classList.contains("overlap"));
    assert.ok(row.querySelector(".ring"), "each column needs its own tick");
  }
  assert.notEqual(gym.style.left, maths.style.left, "columns must not sit on top of each other");
  // a divider between neighbours, none after the last
  assert.ok(gym.classList.contains("divided"));
  assert.equal(maths.classList.contains("divided"), false);
});

test("overlapping tasks keep their duration-height pill and outside text", async (t) => {
  const { doc, close } = await boot({
    items: [
      task({ id: "college", title: "Sort college sheet", start_time: "18:30", estimated_minutes: 120 }),
      task({ id: "ice", title: "Ice ankle", start_time: "19:55", estimated_minutes: 20 }),
    ],
  });
  t.after(close);

  const college = rowFor(doc, "Sort college sheet");
  const ice = rowFor(doc, "Ice ankle");

  assert.equal(college.style.height, "216px", "the two-hour task must keep its full timeline height");
  assert.equal(ice.style.height, "52px", "short tasks keep the normal minimum touch height");

  for (const row of [college, ice]) {
    const pill = row.querySelector(".ov-time-shape");
    const copy = row.querySelector(".ov-body");
    assert.ok(pill, "the normal coloured duration pill should remain visible");
    assert.ok(copy, "the time and title should remain outside the pill");
    assert.equal(pill.contains(copy), false, "text must not be placed inside the coloured pill");
  }
});

test("the overlapping caption is gone", async (t) => {
  const { doc, close } = await boot({
    items: [
      task({ id: "a", title: "Gym", start_time: "17:30", estimated_minutes: 120 }),
      task({ id: "b", title: "Maths", start_time: "17:45", estimated_minutes: 45 }),
    ],
  });
  t.after(close);
  assert.doesNotMatch(doc.getElementById("list").textContent, /overlapping/i);
});

test("tasks that do not share a time keep the normal layout", async (t) => {
  const { doc, close } = await boot({
    items: [
      task({ id: "a", title: "Gym", start_time: "07:00", estimated_minutes: 60 }),
      task({ id: "b", title: "Maths", start_time: "12:00", estimated_minutes: 45 }),
    ],
  });
  t.after(close);
  for (const title of ["Gym", "Maths"]) {
    const row = rowFor(doc, title);
    assert.equal(row.classList.contains("overlap"), false);
    assert.ok(row.querySelector(".icon"), "the normal row keeps its circle");
  }
});

/* ---------- free-time slots ---------- */

test("the add button offers the moment the day is actually free", async (t) => {
  // The bug: free time was measured from the previous row's end rather than
  // from the latest end so far, so a long task overlapped by a short one
  // produced a slot starting in the middle of the long one.
  const { doc, window, close } = await boot({
    items: [
      task({ id: "long", title: "Gym", start_time: "09:00", estimated_minutes: 120 }), // to 11:00
      task({ id: "short", title: "Call", start_time: "09:30", estimated_minutes: 30 }), // to 10:00
      task({ id: "later", title: "Lunch", start_time: "13:00", estimated_minutes: 30 }),
    ],
  });
  t.after(close);

  const gap = doc.querySelector("#list .gap");
  assert.ok(gap, "no free slot was offered");
  gap.querySelector(".gap-add").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await settle(window);

  // 11:00 is when everything has finished, not 10:00
  assert.equal(doc.getElementById("new-time").value, "11:00");
});

test("a half hour of free time is enough to offer a slot", async (t) => {
  const { doc, close } = await boot({
    items: [
      task({ id: "a", title: "Gym", start_time: "09:00", estimated_minutes: 30 }), // to 09:30
      task({ id: "b", title: "Lunch", start_time: "10:00", estimated_minutes: 30 }),
    ],
  });
  t.after(close);
  assert.ok(doc.querySelector("#list .gap"), "30 minutes should offer a slot");
});

test("a short break offers nothing", async (t) => {
  const { doc, close } = await boot({
    items: [
      task({ id: "a", title: "Gym", start_time: "09:00", estimated_minutes: 30 }), // to 09:30
      task({ id: "b", title: "Lunch", start_time: "09:50", estimated_minutes: 30 }),
    ],
  });
  t.after(close);
  assert.equal(doc.querySelector("#list .gap"), null);
});

/* ---------- moving between days ---------- */

test("returning to the app keeps the day you chose", async (t) => {
  // The bug: any return to the foreground forced the screen back to today,
  // which on a phone happens constantly — so picking tomorrow never stuck.
  const { doc, window, close } = await boot({ items: [] });
  t.after(close);

  const strip = [...doc.querySelectorAll(".day-pill")];
  const other = strip.find((p) => !p.classList.contains("today"));
  other.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await settle(window);
  const chosen = doc.getElementById("day-title").textContent;

  doc.dispatchEvent(new window.Event("visibilitychange"));
  await settle(window);

  assert.equal(doc.getElementById("day-title").textContent, chosen);
});

test("switching to another day does not leave the old day on screen", async (t) => {
  // The bug: the previous day's tasks stayed visible under the new heading
  // until the fetch returned, and stayed for ever if it failed.
  let allow = true;
  const { doc, window, close } = await boot({
    items: [task({ id: "a", title: "Yesterdays thing", start_time: "09:00" })],
    onRequest: ({ method, path }) => {
      if (!allow && method === "GET" && path.startsWith("/v2/day")) {
        return { success: true, message: "ok", data: { date: today(), timezone: "UTC", items: [] } };
      }
      return null;
    },
  });
  t.after(close);
  assert.ok(rowFor(doc, "Yesterdays thing"));

  allow = false;
  const other = [...doc.querySelectorAll(".day-pill")].find((p) => !p.classList.contains("selected"));
  other.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await settle(window);

  assert.equal(rowFor(doc, "Yesterdays thing"), undefined);
});

/* ---------- splitting ---------- */

test("splitting a task halves it rather than duplicating its length", async (t) => {
  // The bug: the new slot was created with the whole duration, and posted a
  // field name the endpoint ignores, so it landed with no date at all.
  const { doc, window, calls, close } = await boot({
    items: [task({ id: "a", title: "Study", start_time: "16:00", estimated_minutes: 90 })],
  });
  t.after(close);

  rowFor(doc, "Study").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await settle(window);
  doc.getElementById("sheet-split").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await settle(window);

  const posts = calls.filter((c) => c.method === "POST" && c.path === "/v2/day/tasks");
  assert.equal(posts.length, 2, "a split makes two slots");
  assert.deepEqual(posts.map((p) => p.body.estimated_minutes).sort(), [45, 45]);
  for (const post of posts) {
    assert.equal(post.body.date, today(), "a slot with no date is invisible everywhere");
    assert.equal(post.body.parent_task_id, "a");
  }
});

test("a habit cannot be split", async (t) => {
  const { doc, window, calls, close } = await boot({
    items: [
      task({ id: `habit:abc:${today()}`, title: "Gym", start_time: "17:30", is_habit: true }),
    ],
  });
  t.after(close);

  rowFor(doc, "Gym").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await settle(window);
  doc.getElementById("sheet-split").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await settle(window);

  assert.equal(calls.filter((c) => c.method === "POST").length, 0);
});

/* ---------- dragging ---------- */

test("a dropped task moves before the server has answered", async (t) => {
  // The drop used to await the save and only then repaint, so on a cold
  // server the row sat at its old time for seconds after being let go.
  const { doc, window, close } = await boot({
    items: [task({ id: "a", title: "Gym", start_time: "09:00", estimated_minutes: 60 })],
    onRequest: ({ method }) => (method === "PATCH" ? "pending" : null),
  });
  t.after(close);

  const row = rowFor(doc, "Gym");
  const before = row.style.top;

  const at = (y) => ({ bubbles: true, pointerId: 1, clientX: 20, clientY: y });
  row.dispatchEvent(new window.PointerEvent("pointerdown", at(100)));
  await new Promise((r) => window.setTimeout(r, 320)); // the press-and-hold
  row.dispatchEvent(new window.PointerEvent("pointermove", at(280)));
  row.dispatchEvent(new window.PointerEvent("pointerup", at(280)));
  await settle(window);

  // The save is deliberately still unanswered, so anything visible now is
  // the optimistic move.
  const moved = rowFor(doc, "Gym");
  assert.notEqual(moved.style.top, before, "the row did not move until the server replied");
});
