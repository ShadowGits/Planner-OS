/* Loads the real PWA into a real DOM.
 *
 * These tests exist because every screen bug shipped so far — a tick that
 * silently undid itself, a day that snapped back to today, an add button
 * offering a time in the middle of another task — lived in app.js, which had
 * no tests at all. So the harness runs the actual file against the actual
 * index.html rather than a copy of the logic, and fakes only the network.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const HERE = dirname(fileURLToPath(import.meta.url));
const PWA = join(HERE, "..", "..", "planner_api", "static", "pwa");

export const APP_JS = readFileSync(join(PWA, "app.js"), "utf8");
const INDEX_HTML = readFileSync(join(PWA, "index.html"), "utf8");

/** One task as the day endpoint returns it. */
export function task(over = {}) {
  return {
    id: over.id || "t1",
    title: "Task",
    status: "todo",
    done: false,
    start_time: "09:00",
    estimated_minutes: 30,
    priority: "medium",
    due_date: null,
    scheduled_date: today(),
    notes: null,
    project_id: null,
    parent_task_id: null,
    ...over,
  };
}

export function today() {
  const d = new Date();
  if (d.getHours() < 4) d.setDate(d.getDate() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * Boot the app with a given set of items for every day.
 *
 * Returns the window plus `calls`, every request the app made, so a test can
 * assert on what reached the server as well as what reached the screen.
 */
export async function boot({ items = [], onRequest = null } = {}) {
  // runScripts lets the file execute with the real globals it expects. The
  // page's own <script src> is never fetched (external resources are off), so
  // the app starts only when this harness injects it, after fetch is faked.
  const dom = new JSDOM(INDEX_HTML, {
    url: "https://planner.test/app/",
    pretendToBeVisual: true,
    runScripts: "dangerously",
  });
  const { window } = dom;

  const calls = [];
  window.fetch = async (path, options = {}) => {
    const method = options.method || "GET";
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ method, path, body });

    const custom = onRequest && onRequest({ method, path, body });
    // "pending" holds the response open for ever, so a test can check what the
    // screen shows while a request is still in flight.
    if (custom === "pending") return new Promise(() => {});
    if (custom) return reply(custom);

    if (method === "GET" && path.startsWith("/v2/day")) {
      const date = new URL(path, "https://planner.test").searchParams.get("date") || today();
      return reply({
        success: true,
        message: "ok",
        data: { date, timezone: "Asia/Kolkata", items },
      });
    }
    return reply({ success: true, message: "ok", data: {} });
  };

  window.localStorage.setItem("day-planner-key", "test-key");
  window.navigator.vibrate = () => {};
  // jsdom has no layout, so anything reading geometry gets zeroes; the app
  // only uses these for scroll position, which no assertion depends on.
  window.scrollTo = () => {};
  // jsdom ships no matchMedia; the palette helpers ask it whether the phone is
  // in dark mode. Answer "light" so colours are deterministic in tests.
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  });

  // jsdom implements no PointerEvent, which is what the drag handler listens
  // for. This is a faithful enough stand-in: a MouseEvent carrying the pointer
  // fields the handler reads.
  if (!window.PointerEvent) {
    window.PointerEvent = class PointerEvent extends window.MouseEvent {
      constructor(type, init = {}) {
        super(type, init);
        this.pointerId = init.pointerId ?? 1;
        this.pointerType = init.pointerType ?? "touch";
        this.isPrimary = init.isPrimary ?? true;
      }
    };
  }
  // Pointer capture is a no-op here; the app already guards these in try/catch.
  const proto = window.Element.prototype;
  proto.setPointerCapture ||= function () {};
  proto.releasePointerCapture ||= function () {};
  proto.hasPointerCapture ||= function () { return false; };

  const errors = [];
  window.addEventListener("error", (e) => errors.push(e.error || e.message));
  const script = window.document.createElement("script");
  script.textContent = APP_JS;
  window.document.body.appendChild(script);
  await settle(window);
  // The app keeps hourly timers running; without closing the window they hold
  // the test process open for ever.
  const close = () => window.close();
  return { dom, window, doc: window.document, calls, errors, close };
}

function reply(payload) {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  };
}

/** Let pending promises and timers resolve. */
export async function settle(window, ticks = 6) {
  for (let i = 0; i < ticks; i++) {
    await new Promise((r) => window.setTimeout(r, 0));
  }
}

/** Every rendered timeline row, in screen order. */
export function rows(doc) {
  return [...doc.querySelectorAll("#list .row")];
}

export function rowFor(doc, title) {
  return rows(doc).find((r) => r.textContent.includes(title));
}
