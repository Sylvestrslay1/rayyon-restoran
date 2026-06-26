const CACHE = 'rayyon-v3';
const STATIC = [
  '/',
  '/index.html',
  '/menu.html',
  '/loyalty-card.html',
  '/manifest.json',
  '/css/style.css',
  '/js/main.js',
  '/js/i18n.js',
];
const SYNC_TAG = 'offline-orders';
const DB_NAME = 'rayyon-offline';
const DB_STORE = 'pending-orders';

// ===== IndexedDB yordamchi =====
function openDB() {
  return new Promise((res, rej) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = e => e.target.result.createObjectStore(DB_STORE, { autoIncrement: true });
    req.onsuccess = e => res(e.target.result);
    req.onerror = () => rej(req.error);
  });
}
async function dbAdd(item) {
  const db = await openDB();
  return new Promise((res, rej) => {
    const tx = db.transaction(DB_STORE, 'readwrite');
    tx.objectStore(DB_STORE).add(item).onsuccess = e => res(e.target.result);
    tx.onerror = () => rej(tx.error);
  });
}
async function dbGetAll() {
  const db = await openDB();
  return new Promise((res, rej) => {
    const tx = db.transaction(DB_STORE, 'readonly');
    const req = tx.objectStore(DB_STORE).getAll();
    req.onsuccess = () => res(req.result);
    req.onerror = () => rej(req.error);
  });
}
async function dbClear() {
  const db = await openDB();
  return new Promise((res, rej) => {
    const tx = db.transaction(DB_STORE, 'readwrite');
    tx.objectStore(DB_STORE).clear().onsuccess = () => res();
    tx.onerror = () => rej(tx.error);
  });
}

// ===== Install =====
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(STATIC))
      .then(() => self.skipWaiting())
  );
});

// ===== Activate =====
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// ===== Fetch =====
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // SSE uzilmaydi
  if (url.pathname === '/api/events') return;

  // POST /api/session/*/order — offline uchun saqlash
  if (e.request.method === 'POST' && url.pathname.match(/\/api\/session\/\d+\/order/)) {
    e.respondWith(
      fetch(e.request.clone()).catch(async () => {
        const body = await e.request.clone().json().catch(() => null);
        if (body) {
          await dbAdd({ url: url.pathname, body, ts: Date.now() });
          if ('SyncManager' in self) {
            await self.registration.sync.register(SYNC_TAG);
          }
        }
        return new Response(JSON.stringify({ ok: true, offline: true }),
          { headers: { 'Content-Type': 'application/json' } });
      })
    );
    return;
  }

  // API — network only (cache yo'q)
  if (url.pathname.startsWith('/api/')) return;
  // Admin panel — network first
  if (url.pathname.startsWith('/admin/')) return;

  // Statik fayllar — cache first, keyin network
  e.respondWith(
    caches.match(e.request).then(cached => {
      const net = fetch(e.request).then(res => {
        if (res.ok && e.request.method === 'GET') {
          caches.open(CACHE).then(c => c.put(e.request, res.clone()));
        }
        return res;
      });
      return cached || net;
    })
  );
});

// ===== Background Sync =====
self.addEventListener('sync', e => {
  if (e.tag === SYNC_TAG) {
    e.waitUntil(replayOfflineOrders());
  }
});

async function replayOfflineOrders() {
  const orders = await dbGetAll();
  if (!orders.length) return;
  const results = await Promise.allSettled(
    orders.map(o =>
      fetch(o.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(o.body),
      })
    )
  );
  const allOk = results.every(r => r.status === 'fulfilled' && r.value.ok);
  if (allOk) {
    await dbClear();
    // Barcha ochiq tab larga xabar berish
    const clients = await self.clients.matchAll({ type: 'window' });
    clients.forEach(c => c.postMessage({ type: 'SYNC_COMPLETE', count: orders.length }));
  }
}

// ===== Push Notification =====
self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : {};
  e.waitUntil(
    self.registration.showNotification(data.title || 'Rayyon Restoran', {
      body: data.body || '',
      icon: '/favicon.ico',
      badge: '/favicon.ico',
      tag: data.tag || 'rayyon',
      data: { url: data.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(
    self.clients.matchAll({ type: 'window' }).then(clients => {
      const focused = clients.find(c => c.focus);
      if (focused) return focused.focus();
      return self.clients.openWindow(e.notification.data.url || '/');
    })
  );
});
