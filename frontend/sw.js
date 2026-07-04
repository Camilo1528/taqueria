
const CACHE_NAME = 'taqueria-pro-v5';
const STATIC_ASSETS = [
  '/',
  '/admin.html',
  '/cashier.html',
  '/kitchen.html',
  '/customer.html',
  '/login.html',
  '/waiter.html',
  '/delivery.html',
  '/attendance.html',
  '/menu_board.html',
  '/display.html',
  '/css/style.css',
  '/css/admin.css',
  '/css/kitchen.css',
  '/js/kitchen.js',
  '/js/offline-queue.js',
  '/libs/bootstrap.min.css',
  '/libs/bootstrap.bundle.min.js',
  '/libs/chart.js',
  '/manifest.json'
];

// API endpoints que se pueden cachear para lectura offline
const CACHEABLE_API = [
  '/branding',
  '/api/pos/orders',
  '/api/customer/menu',
  '/api/shift/status'
];

// ─── INSTALL ──────────────────────────────────────────────
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS).catch(err => {
        console.warn('SW: Some assets failed to cache', err);
      });
    })
  );
});

// ─── ACTIVATE ─────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

// ─── FETCH ────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Solo interceptar requests del mismo origen
  if (url.origin !== location.origin) return;

  // Para APIs cacheables: Network-first con fallback a cache
  if (CACHEABLE_API.some(api => url.pathname.startsWith(api)) && event.request.method === 'GET') {
    event.respondWith(networkFirstThenCache(event.request));
    return;
  }

  // Para POST/PATCH/PUT a APIs: dejar pasar normal (el offline-queue.js maneja la cola)
  if (event.request.method !== 'GET') return;

  // Para assets estáticos: Cache-first con fallback a network
  event.respondWith(cacheFirstThenNetwork(event.request));
});

async function networkFirstThenCache(request) {
  try {
    const response = await fetch(request);
    // Guardar copia en cache
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, response.clone());
    return response;
  } catch (e) {
    // Sin red, intentar cache
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: 'offline', cached: false }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

async function cacheFirstThenNetwork(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, response.clone());
    return response;
  } catch (e) {
    // Página offline fallback
    if (request.headers.get('accept')?.includes('text/html')) {
      return new Response('<html><body style="font-family:sans-serif;text-align:center;padding:50px;"><h1>🔴 Sin Conexión</h1><p>Recarga cuando vuelvas a tener internet.</p></body></html>', {
        headers: { 'Content-Type': 'text/html' }
      });
    }
    return new Response('Offline', { status: 503 });
  }
}

// ─── BACKGROUND SYNC ──────────────────────────────────────
self.addEventListener('sync', event => {
  if (event.tag === 'sync-pending-operations') {
    event.waitUntil(syncPendingFromIDB());
  }
});

async function syncPendingFromIDB() {
  // Abrir IndexedDB directamente desde el SW
  const db = await openIDB();
  const tx = db.transaction('pending_operations', 'readonly');
  const store = tx.objectStore('pending_operations');
  const allOps = await idbGetAll(store);

  for (const op of allOps) {
    try {
      const res = await fetch(op.url, {
        method: op.method,
        headers: op.headers,
        body: op.body
      });
      if (res.ok) {
        const delTx = db.transaction('pending_operations', 'readwrite');
        delTx.objectStore('pending_operations').delete(op.id);
      }
    } catch (e) {
      break; // Seguimos sin conexión
    }
  }

  // Notificar a los clientes
  const clients = await self.clients.matchAll();
  clients.forEach(client => {
    client.postMessage({ type: 'SYNC_COMPLETE' });
  });
}

function openIDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('TaqueriaOfflineDB', 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('pending_operations')) {
        const store = db.createObjectStore('pending_operations', { keyPath: 'id', autoIncrement: true });
        store.createIndex('type', 'type', { unique: false });
        store.createIndex('timestamp', 'timestamp', { unique: false });
      }
      if (!db.objectStoreNames.contains('cached_data')) {
        db.createObjectStore('cached_data', { keyPath: 'key' });
      }
    };
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror = (e) => reject(e.target.error);
  });
}

function idbGetAll(store) {
  return new Promise((resolve, reject) => {
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = (e) => reject(e.target.error);
  });
}
