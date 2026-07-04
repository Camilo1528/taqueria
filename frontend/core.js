// core.js - Funciones globales compartidas
const TOKEN = () => localStorage.getItem('token');
const AUTH = () => ({ 'Authorization': 'Bearer ' + TOKEN(), 'Content-Type': 'application/json' });

function logout() {
    localStorage.clear();
    window.location.href = '/login.html';
}

function toast(msg, type='success') {
    let c = document.getElementById('toasts');
    if (!c) {
        c = document.createElement('div');
        c.id = 'toasts';
        c.className = 'toast-container';
        document.body.appendChild(c);
    }
    const d = document.createElement('div');
    d.className = 'toast ' + type;
    const ico = {success:'check-circle-fill',error:'x-circle-fill',warning:'exclamation-triangle-fill'}[type]||'info-circle-fill';
    d.innerHTML = '<i class="bi bi-'+ico+'"></i> ' + msg;
    c.appendChild(d);
    setTimeout(()=>d.remove(), 3500);
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
