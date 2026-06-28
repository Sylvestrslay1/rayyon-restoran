const CACHE = 'rayyon-v5';
const STATIC = [
  '/',
  '/index.html',
  '/menu.html',
  '/cashier.html',
  '/kitchen.html',
  '/waiter.html',
  '/staff-login.html',
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
async function dbDeleteByKey(key) {
  const db = await openDB();
  return new Promise((res, rej) => {
    const tx = db.transaction(DB_STORE, 'readwrite');
    tx.objectStore(DB_STORE).delete(key).onsuccess = () => res();
    tx.onerror = () => rej(tx.error);
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
// FIX: har bir fayl alohida yuklanadi — bitta 404 butun SW ni to'xtatmaydi
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(async cache => {
      const results = await Promise.allSettled(
        STATIC.map(url => cache.add(url).catch(err => {
          console.warn(`SW: kesh qo'shilmadi ${url}:`, err);
        }))
      );
      const failed = results.filter(r => r.status === 'rejected').length;
      if (failed) console.warn(`SW install: ${failed} ta fayl keshlanmadi`);
      return self.skipWaiting();
    })
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
          const token = e.request.headers.get('X-Session-Token') || '';
          if (token) body._session_token = token;
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

  // API — network only
  if (url.pathname.startsWith('/api/')) return;

  // FIX: Admin panel — network first, kesh fallback (tarmoq uzilsa ham ishlaydi)
  if (url.pathname.startsWith('/admin/')) {
    e.respondWith(
      fetch(e.request).then(res => {
        if (res.ok) {
          caches.open(CACHE).then(c => c.put(e.request, res.clone()));
        }
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // Statik fayllar — cache first, keyin network
  e.respondWith(
    caches.match(e.request).then(cached => {
      const net = fetch(e.request).then(res => {
        if (res.ok && e.request.method === 'GET') {
          caches.open(CACHE).then(c => c.put(e.request, res.clone()));
        }
        return res;
      }).catch(() => cached);  // tarmoq uzilsa keshdan qaytaradi
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
  const db = await openDB();
  const orders = await new Promise((res, rej) => {
    const tx = db.transaction(DB_STORE, 'readonly');
    const req = tx.objectStore(DB_STORE).getAllKeys();
    req.onsuccess = () => {
      const keys = req.result;
      const store = db.transaction(DB_STORE, 'readonly').objectStore(DB_STORE);
      const items = [];
      let pending = keys.length;
      if (!pending) { res([]); return; }
      keys.forEach(key => {
        store.get(key).onsuccess = ev => {
          items.push({ key, data: ev.target.result });
          if (--pending === 0) res(items);
        };
      });
    };
    req.onerror = () => rej(req.error);
  });

  if (!orders.length) return;

  // FIX: Har bir buyurtmani alohida qayta yuboramiz — muvaffaqiyatlilarini darhol o'chiramiz
  let successCount = 0;
  for (const { key, data: o } of orders) {
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (o.body && o.body._session_token) {
        headers['X-Session-Token'] = o.body._session_token;
      }
      const res = await fetch(o.url, {
        method: 'POST',
        headers,
        body: JSON.stringify(o.body),
      });
      if (res.ok) {
        await dbDeleteByKey(key);  // faqat muvaffaqiyatlilarni o'chiramiz
        successCount++;
      }
    } catch (_) {
      // Tarmoq yo'q — keyingi sync da qayta urinib ko'ramiz
    }
  }

  if (successCount > 0) {
    const clients = await self.clients.matchAll({ type: 'window' });
    clients.forEach(c => c.postMessage({ type: 'SYNC_COMPLETE', count: successCount }));
  }
}

// ===== Push Notification =====
self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : {};
  e.waitUntil(
    self.registration.showNotification(data.title || 'Rayyon Restoran', {
      body: data.body || '',
      icon: '/assets/icon-192.png',
      badge: '/assets/icon-192.png',
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
