// core.js - Funciones globales compartidas

// Si alguien abre el archivo directamente (doble clic), la app no puede hablar con el servidor:
// se muestra un aviso claro en lugar de una pantalla rota.
if (location.protocol === 'file:') {
    document.addEventListener('DOMContentLoaded', () => {
        const d = document.createElement('div');
        d.style.cssText = 'position:fixed;inset:0;z-index:100000;background:#0b1020;color:#e2e8f0;display:flex;' +
            'align-items:center;justify-content:center;padding:24px;font:16px/1.5 Inter,system-ui,sans-serif;text-align:center';
        d.innerHTML = '<div style="max-width:520px"><div style="font-size:48px">🌮</div>' +
            '<h2 style="margin:12px 0 8px;color:#fff">Abre Taquería Pro desde el servidor</h2>' +
            '<p>Este archivo se abrió directamente desde la carpeta, y así la aplicación no puede funcionar ' +
            '(no carga el diseño ni los datos).</p>' +
            '<p>Inicia el servidor y entra desde el navegador a:<br>' +
            '<b style="color:#a5b4fc;font-size:20px">http://localhost:8000</b></p>' +
            '<p style="color:#94a3b8;font-size:13px">En otros equipos del local usa la dirección IP del computador del servidor, ' +
            'por ejemplo http://192.168.1.10:8000</p></div>';
        document.body.appendChild(d);
    });
}
const TOKEN = () => localStorage.getItem('token');
const AUTH = () => ({ 'Authorization': 'Bearer ' + TOKEN(), 'Content-Type': 'application/json' });

function logout() {
    localStorage.clear();
    window.location.href = '/login.html';
}

// Avisos emergentes. Usa clases propias (app-toast): Bootstrap oculta ".toast" sin ".show".
function toast(msg, type='success') {
    if (!document.getElementById('app-toast-style')) {
        const st = document.createElement('style');
        st.id = 'app-toast-style';
        st.textContent =
          '#app-toasts{position:fixed;right:16px;bottom:16px;z-index:99999;display:flex;flex-direction:column;gap:8px;max-width:calc(100vw - 32px)}' +
          '.app-toast{display:flex;align-items:center;gap:10px;padding:12px 16px;border-radius:12px;color:#fff;font:600 14px/1.35 Inter,system-ui,sans-serif;' +
          'box-shadow:0 8px 24px rgba(0,0,0,.25);max-width:380px;animation:appToastIn .25s ease-out}' +
          '.app-toast.success{background:#059669}.app-toast.error{background:#dc2626}.app-toast.warning{background:#d97706}.app-toast.info{background:#2563eb}' +
          '@keyframes appToastIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}';
        document.head.appendChild(st);
    }
    let c = document.getElementById('app-toasts');
    if (!c) {
        c = document.createElement('div');
        c.id = 'app-toasts';
        c.setAttribute('role', 'status');
        c.setAttribute('aria-live', 'polite');
        document.body.appendChild(c);
    }
    const d = document.createElement('div');
    d.className = 'app-toast ' + type;
    const ico = {success:'check-circle-fill',error:'x-circle-fill',warning:'exclamation-triangle-fill'}[type]||'info-circle-fill';
    const i = document.createElement('i');
    i.className = 'bi bi-' + ico;
    const span = document.createElement('span');
    span.textContent = msg;
    d.append(i, span);
    c.appendChild(d);
    setTimeout(()=>d.remove(), type === 'error' ? 6000 : 3500);
}

function updateClockGlobal(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const n = new Date();
    el.textContent =
      n.toLocaleTimeString('es-CO',{hour:'2-digit',minute:'2-digit',second:'2-digit'}) +
      '   ' + n.toLocaleDateString('es-CO',{weekday:'long',day:'numeric',month:'long'});
}

// PWA Service Worker Registration
if('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(err => {
            console.log('SW registration failed: ', err);
        });
    });
}
