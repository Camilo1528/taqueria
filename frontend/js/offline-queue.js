/**
 * offline-queue.js
 * Módulo de cola offline usando IndexedDB para Taquería Pro.
 * Almacena operaciones pendientes (pagos, gastos, etc.) cuando no hay conexión
 * y las sincroniza automáticamente al recuperar internet.
 */

const DB_NAME = 'TaqueriaOfflineDB';
const DB_VERSION = 1;
const STORE_QUEUE = 'pending_operations';
const STORE_CACHE = 'cached_data';

class OfflineQueue {
    constructor() {
        this.db = null;
        this.isOnline = navigator.onLine;
        this._initListeners();
    }

    _initListeners() {
        window.addEventListener('online', () => {
            this.isOnline = true;
            this._updateStatusUI(true);
            this.syncAll();
        });
        window.addEventListener('offline', () => {
            this.isOnline = false;
            this._updateStatusUI(false);
        });
    }

    _updateStatusUI(online) {
        let badge = document.getElementById('offline-status-badge');
        if (!badge) {
            badge = document.createElement('div');
            badge.id = 'offline-status-badge';
            badge.style.cssText = 'position:fixed;top:10px;right:10px;z-index:9999;padding:8px 16px;border-radius:20px;font-weight:bold;font-size:14px;transition:all 0.3s;box-shadow:0 2px 8px rgba(0,0,0,0.2);';
            document.body.appendChild(badge);
        }
        if (online) {
            badge.innerHTML = '🟢 En Línea';
            badge.style.background = '#10b981';
            badge.style.color = 'white';
            setTimeout(() => { badge.style.opacity = '0.3'; }, 3000);
            badge.onmouseenter = () => { badge.style.opacity = '1'; };
            badge.onmouseleave = () => { badge.style.opacity = '0.3'; };
        } else {
            badge.innerHTML = '🔴 Sin Conexión (Modo Offline)';
            badge.style.background = '#ef4444';
            badge.style.color = 'white';
            badge.style.opacity = '1';
        }
    }

    async open() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onupgradeneeded = (e) => {
                const db = e.target.result;
                if (!db.objectStoreNames.contains(STORE_QUEUE)) {
                    const store = db.createObjectStore(STORE_QUEUE, { keyPath: 'id', autoIncrement: true });
                    store.createIndex('type', 'type', { unique: false });
                    store.createIndex('timestamp', 'timestamp', { unique: false });
                }
                if (!db.objectStoreNames.contains(STORE_CACHE)) {
                    db.createObjectStore(STORE_CACHE, { keyPath: 'key' });
                }
            };
            request.onsuccess = (e) => {
                this.db = e.target.result;
                resolve(this.db);
            };
            request.onerror = (e) => reject(e.target.error);
        });
    }

    async enqueue(type, url, options) {
        if (!this.db) await this.open();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(STORE_QUEUE, 'readwrite');
            const store = tx.objectStore(STORE_QUEUE);
            const op = {
                type: type,
                url: url,
                method: options.method || 'POST',
                headers: options.headers || {},
                body: options.body || null,
                timestamp: new Date().toISOString(),
                retries: 0
            };
            const req = store.add(op);
            req.onsuccess = () => resolve(req.result);
            req.onerror = (e) => reject(e.target.error);
        });
    }

    async getAll() {
        if (!this.db) await this.open();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(STORE_QUEUE, 'readonly');
            const store = tx.objectStore(STORE_QUEUE);
            const req = store.getAll();
            req.onsuccess = () => resolve(req.result);
            req.onerror = (e) => reject(e.target.error);
        });
    }

    async remove(id) {
        if (!this.db) await this.open();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(STORE_QUEUE, 'readwrite');
            const store = tx.objectStore(STORE_QUEUE);
            const req = store.delete(id);
            req.onsuccess = () => resolve();
            req.onerror = (e) => reject(e.target.error);
        });
    }

    async count() {
        if (!this.db) await this.open();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(STORE_QUEUE, 'readonly');
            const store = tx.objectStore(STORE_QUEUE);
            const req = store.count();
            req.onsuccess = () => resolve(req.result);
            req.onerror = (e) => reject(e.target.error);
        });
    }

    // Cache de datos para uso offline (órdenes, productos, branding)
    async cacheData(key, data) {
        if (!this.db) await this.open();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(STORE_CACHE, 'readwrite');
            const store = tx.objectStore(STORE_CACHE);
            store.put({ key: key, data: data, updated: new Date().toISOString() });
            tx.oncomplete = () => resolve();
            tx.onerror = (e) => reject(e.target.error);
        });
    }

    async getCachedData(key) {
        if (!this.db) await this.open();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(STORE_CACHE, 'readonly');
            const store = tx.objectStore(STORE_CACHE);
            const req = store.get(key);
            req.onsuccess = () => resolve(req.result ? req.result.data : null);
            req.onerror = (e) => reject(e.target.error);
        });
    }

    // Sincronizar todas las operaciones pendientes
    async syncAll() {
        const pending = await this.getAll();
        if (pending.length === 0) return { synced: 0, failed: 0 };

        let synced = 0, failed = 0;
        
        for (const op of pending) {
            try {
                const res = await fetch(op.url, {
                    method: op.method,
                    headers: op.headers,
                    body: op.body
                });
                if (res.ok) {
                    await this.remove(op.id);
                    synced++;
                } else {
                    failed++;
                }
            } catch (e) {
                failed++;
                // Si falla, significa que seguimos sin conexión
                break;
            }
        }

        if (synced > 0) {
            this._showSyncNotification(synced, failed);
        }

        return { synced, failed };
    }

    _showSyncNotification(synced, failed) {
        const notif = document.createElement('div');
        notif.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;background:#1f2937;color:white;padding:16px 24px;border-radius:12px;font-size:14px;box-shadow:0 4px 12px rgba(0,0,0,0.3);animation:slideUp 0.3s ease;';
        notif.innerHTML = `✅ <b>${synced}</b> operación(es) sincronizada(s)${failed > 0 ? ` | ❌ ${failed} fallida(s)` : ''}`;
        document.body.appendChild(notif);
        setTimeout(() => notif.remove(), 5000);
    }

    // Fetch con fallback offline
    async fetchWithOffline(url, options = {}, cacheKey = null) {
        // Si estamos online, intentar normalmente
        if (this.isOnline) {
            try {
                const res = await fetch(url, options);
                // Si es GET y tiene cacheKey, guardar resultado en cache
                if (cacheKey && (!options.method || options.method === 'GET') && res.ok) {
                    const clone = res.clone();
                    const data = await clone.json();
                    await this.cacheData(cacheKey, data);
                }
                return res;
            } catch (e) {
                // Falló la conexión inesperadamente
                this.isOnline = false;
                this._updateStatusUI(false);
            }
        }

        // Estamos offline
        if (!options.method || options.method === 'GET') {
            // Para GETs, devolver datos cacheados
            if (cacheKey) {
                const cached = await this.getCachedData(cacheKey);
                if (cached) {
                    return new Response(JSON.stringify(cached), {
                        status: 200,
                        headers: { 'Content-Type': 'application/json' }
                    });
                }
            }
            throw new Error('Sin conexión y sin datos en caché');
        } else {
            // Para POSTs/PATCHs, encolar la operación
            await this.enqueue(options.method || 'POST', url, options);
            // Devolver una respuesta simulada exitosa
            return new Response(JSON.stringify({ status: 'queued_offline' }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' }
            });
        }
    }
}

// Instancia global
const offlineQueue = new OfflineQueue();
offlineQueue.open();
