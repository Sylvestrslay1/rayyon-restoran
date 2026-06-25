const CACHE = 'rayyon-v2';
const STATIC = [
  '/',
  '/index.html',
  '/menu.html',
  '/manifest.json',
  '/css/style.css',
  '/js/main.js',
  '/js/i18n.js',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // API so'rovlari va SSE — cache qilinmaydi
  if (url.pathname.startsWith('/api/') || url.pathname === '/api/events') return;
  // Admin panel — network first
  if (url.pathname.startsWith('/admin/')) return;

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
