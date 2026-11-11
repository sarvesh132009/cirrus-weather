/* Cirrus service worker: shows notifications and, where the browser allows it (installed app on Chrome/Android),
   checks for new alerts in the background about every few hours. */
'use strict';
const db = () => new Promise((ok, no) => { const r = indexedDB.open('cirrus', 1); r.onupgradeneeded = () => r.result.createObjectStore('kv'); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
const get = async () => { const d = await db(); return new Promise((ok) => { const r = d.transaction('kv').objectStore('kv').get('state'); r.onsuccess = () => ok(r.result || null); r.onerror = () => ok(null); }); };
const put = async (v) => { const d = await db(); return new Promise((ok) => { const t = d.transaction('kv', 'readwrite'); t.objectStore('kv').put(v, 'state'); t.oncomplete = ok; t.onerror = ok; }); };

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

async function sweep() {
  const st = await get();
  if (!st || !st.notify || !st.places || !st.places.length) return;
  const now = Date.now();
  for (const p of st.places.slice(0, 3)) {
    let data;
    try { data = await (await fetch(`/api/alerts?lat=${p.lat.toFixed(2)}&lon=${p.lon.toFixed(2)}&name=${encodeURIComponent(p.name || '')}`)).json(); } catch { continue; }
    for (const a of data.alerts || []) {
      if (a.level < st.minLevel || (st.seen || {})[a.id]) continue;
      st.seen = { ...(st.seen || {}), [a.id]: now };
      await self.registration.showNotification(`${a.label}: ${a.title}`, { body: `${p.name} · ${a.when}\n${a.detail}`, tag: a.id, renotify: true, requireInteraction: a.level >= 3,
        icon: '/static/icon-192.png', badge: '/static/icon-192.png', vibrate: [300, 150, 300], silent: false,
        data: { url: `/forecast/overview?lat=${p.lat}&lon=${p.lon}&name=${encodeURIComponent(p.name || '')}` } });
    }
  }
  await put(st);
}
self.addEventListener('periodicsync', (e) => { if (e.tag === 'cirrus-alerts') e.waitUntil(sweep()); });
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((all) => {
    for (const c of all) if ('focus' in c) { c.navigate(url).catch(() => {}); return c.focus(); }
    return self.clients.openWindow(url);
  }));
});
