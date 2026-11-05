/* global clients */
// Service worker: red primero, caché solo como respaldo sin conexión.
// Cambiar CACHE_NAME en cada versión fuerza a los dispositivos a renovar archivos.
const CACHE_NAME = "taqueria-cache-v6";
const urlsToCache = ["/login.html", "/customer.html", "/manifest.json", "/core.js", "/libs/bootstrap.min.css"];

// Datos en vivo: nunca se guardan en caché (ventas, cocina, mesas, marca...)
const LIVE_DATA = ["/api/", "/menu", "/dashboard_data", "/kitchen_data", "/tables/", "/branding", "/add_to_order", "/ws/"];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(urlsToCache)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n))))
      .then(() => clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (LIVE_DATA.some((p) => url.pathname.startsWith(p))) return;

  event.respondWith(
    fetch(req)
      .then((response) => {
        if (response && response.status === 200 && response.type === "basic") {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
        }
        return response;
      })
      .catch(() => caches.match(req)),
  );
});
