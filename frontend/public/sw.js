/* PipelineOS service worker (M-1): offline-tolerant read cache + write queue.
   Shell: cache-first. API GETs (my activities, kanban, pipelines): network-first
   with cache fallback. Failed activity-complete POSTs queue and replay online. */
const SHELL = "pos-shell-v1";
const API = "pos-api-v1";
const QUEUE_KEY = "pos-write-queue";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/"])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});

const CACHEABLE_API = [/\/api\/v1\/activities\/my\//, /\/api\/v1\/pipelines\//,
  /\/api\/v1\/lost-reasons\//, /\/api\/v1\/activity-types\//];

async function queueWrite(request) {
  const body = await request.clone().text();
  const entry = { url: request.url, body, headers: [...request.headers.entries()] };
  const cache = await caches.open(API);
  const existing = await cache.match(QUEUE_KEY);
  const queue = existing ? await existing.json() : [];
  queue.push(entry);
  await cache.put(QUEUE_KEY, new Response(JSON.stringify(queue)));
}

async function flushQueue() {
  const cache = await caches.open(API);
  const existing = await cache.match(QUEUE_KEY);
  if (!existing) return;
  const queue = await existing.json();
  const remaining = [];
  for (const entry of queue) {
    try {
      const r = await fetch(entry.url, { method: "POST", body: entry.body,
        headers: Object.fromEntries(entry.headers) });
      if (!r.ok && r.status >= 500) remaining.push(entry);
    } catch {
      remaining.push(entry);
    }
  }
  await cache.put(QUEUE_KEY, new Response(JSON.stringify(remaining)));
}

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method === "GET" && url.pathname === "/") {
    e.respondWith(fetch(e.request).then((r) => {
      const copy = r.clone();
      caches.open(SHELL).then((c) => c.put("/", copy));
      return r;
    }).catch(() => caches.match("/")));
    return;
  }
  if (e.request.method === "GET" && CACHEABLE_API.some((re) => re.test(url.pathname))) {
    e.respondWith(fetch(e.request).then((r) => {
      const copy = r.clone();
      caches.open(API).then((c) => c.put(e.request, copy));
      flushQueue();
      return r;
    }).catch(() => caches.match(e.request)));
    return;
  }
  if (e.request.method === "POST" && /\/api\/v1\/activities\/\d+\/complete\//.test(url.pathname)) {
    e.respondWith(fetch(e.request.clone()).catch(async () => {
      await queueWrite(e.request);
      return new Response(JSON.stringify({ queued: true, prompt_next: false }),
        { status: 202, headers: { "Content-Type": "application/json" } });
    }));
  }
});

self.addEventListener("message", (e) => {
  if (e.data === "flush") flushQueue();
});
