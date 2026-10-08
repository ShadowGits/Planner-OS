/* Network-first app shell so new deploys load automatically; the cache is
   only a fallback for offline. The /v2 API always goes straight to network. */

const CACHE = "day-planner-v35";
const SHELL = ["./", "index.html", "styles.css", "app.js", "focus-timer.js", "focus-timer.css", "work-log.js", "work-log.css", "manifest.webmanifest", "icon-180.png", "icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k.startsWith("day-planner-") && k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const scope = new URL(self.registration.scope);
  const relative = url.pathname.slice(scope.pathname.length);
  // Only cache public app-shell files. OAuth pages, authenticated APIs and
  // external responses must never be stored in the offline shell cache.
  if (event.request.method !== "GET" || url.origin !== scope.origin ||
      !url.pathname.startsWith(scope.pathname) ||
      !["", "index.html", "styles.css", "app.js", "focus-timer.js", "focus-timer.css", "work-log.js", "work-log.css", "manifest.webmanifest", "icon-180.png", "icon-512.png"].includes(relative)) return;
  const cacheKey = new URL(url);
  cacheKey.search = "";
  // Network-first: always try the latest, fall back to cache when offline.
  // cache:"reload" skips the browser's own HTTP cache, which could otherwise
  // hand back a stale app.js and hide a deploy from the phone entirely.
  event.respondWith(
    fetch(event.request, { cache: "reload" })
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          event.waitUntil(caches.open(CACHE).then((c) => c.put(cacheKey.href, copy)));
        }
        return res;
      })
      .catch(() => caches.match(cacheKey.href))
  );
});

/* ---------- push notifications ---------- */

// A reminder arrives as a push message. Show it as a system notification.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { title: "Planner OS", body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "Planner OS";
  const options = {
    body: data.body || "",
    icon: "icon-180.png",
    badge: "icon-180.png",
    tag: data.tag || undefined,        // same tag replaces, never stacks duplicates
    data: { url: data.url || "/app/" },
    requireInteraction: false,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

// The browser can retire a push subscription by itself — updating this worker
// is enough to trigger it. Re-subscribe with the same server key and hand the
// replacement to any open page, which has the app key needed to register it.
// With no page open there is nothing to send it with, so the app also re-syncs
// whatever subscription it holds on every launch.
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil(
    (async () => {
      try {
        const key =
          (event.oldSubscription && event.oldSubscription.options &&
            event.oldSubscription.options.applicationServerKey) || null;
        if (!key) return;
        const sub = await self.registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: key,
        });
        const clients = await self.clients.matchAll({
          type: "window",
          includeUncontrolled: true,
        });
        for (const client of clients) {
          client.postMessage({ type: "push-subscription-changed", subscription: sub.toJSON() });
        }
      } catch {
        // Nothing useful to do here; the next app launch re-syncs.
      }
    })()
  );
});

// Tapping a notification focuses an open app window, or opens one.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const scope = new URL(self.registration.scope);
  let target = scope.href;
  try {
    const requested = new URL((event.notification.data && event.notification.data.url) || scope.href, scope);
    if (requested.origin === scope.origin && requested.pathname.startsWith(scope.pathname)) target = requested.href;
  } catch {}
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes("/app") && "focus" in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});
