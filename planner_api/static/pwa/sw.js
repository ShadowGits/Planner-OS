/* Network-first app shell so new deploys load automatically; the cache is
   only a fallback for offline. The /v2 API always goes straight to network. */

const CACHE = "day-planner-v28";
const SHELL = ["./", "index.html", "styles.css", "app.js", "manifest.webmanifest", "icon-180.png", "icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/v2/")) return;
  // Network-first: always try the latest, fall back to cache when offline.
  // cache:"reload" skips the browser's own HTTP cache, which could otherwise
  // hand back a stale app.js and hide a deploy from the phone entirely.
  event.respondWith(
    fetch(event.request, { cache: "reload" })
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(event.request, copy));
        return res;
      })
      .catch(() => caches.match(event.request))
  );
});

/* ---------- push notifications ---------- */

// A reminder arrives as a push message. Show it as a system notification.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
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

// Tapping a notification focuses an open app window, or opens one.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/app/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes("/app") && "focus" in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});
