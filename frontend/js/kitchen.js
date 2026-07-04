const token = localStorage.getItem('token');
if (!token) window.location.href = 'login.html';

async function cargarCocina() {
    try {
        const res = await fetch('/kitchen_data', { headers: {'Authorization': 'Bearer ' + token} });
        const items = await res.json();
        
        // Agrupar por mesa
        const agrupado = {};
        items.forEach(i => {
            if(!agrupado[i.table_number]) agrupado[i.table_number] = [];
            agrupado[i.table_number].push(i);
        });

        const grid = document.getElementById('kitchen-grid');
        grid.innerHTML = '';
        
        if(Object.keys(agrupado).length === 0) {
            grid.innerHTML = '<div class="col-12 text-center mt-5 text-secondary"><h4>✅ No hay pedidos pendientes</h4></div>';
        } else {
            for(const [mesa, pedidos] of Object.entries(agrupado)) {
                let orderId = pedidos[0].order_id;
                let itemsHtml = pedidos.map(p => {
                    const notesHtml = p.notes ? `<div class="text-danger fw-bold ms-4 mb-1" style="font-size:0.9em; margin-top:-5px">👉 ${p.notes}</div>` : '';
                    const isReady = p.status === 'ready';
                    const textClass = isReady ? 'text-decoration-line-through text-muted' : '';
                    const btnHtml = `<button class="btn btn-sm ${isReady ? 'btn-secondary' : 'btn-outline-success'} rounded-circle px-2 py-0 me-2" style="font-size:0.8rem" onclick="toggleItemStatus(${p.order_id}, ${p.id}, '${isReady ? 'pending' : 'ready'}')">✔</button>`;
                    
                    return `
                    <div class="d-flex align-items-center mb-1 ${textClass}">
                        ${btnHtml}
                        <span class="item-qty">${p.qty}x</span>
                        <span class="item-name">${p.product_name}</span>
                    </div>
                    ${notesHtml}
                    `;
                }).join('');

                grid.innerHTML += `
                    <div class="col-12 col-md-6 col-lg-4 col-xl-3">
                        <div class="ticket d-flex flex-column h-100">
                            <div class="mesa-title">MESA ${mesa}</div>
                            <div class="flex-grow-1">
                                ${itemsHtml}
                            </div>
                            <button class="btn btn-success mt-3 fw-bold w-100" onclick="dispatchOrder(${orderId})">✅ Despachar Mesa</button>
                        </div>
                    </div>
                `;
            }
        }
        
        const now = new Date();
        document.getElementById('last-update').innerText = `Última actualización: ${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;
    } catch (e) {
        console.error("Error cargando cocina", e);
    }
}

cargarCocina(); // Carga inicial

// Conexión WebSocket
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${protocol}//${window.location.host}/ws/kitchen?token=${token}`;
let ws;

function connectWebSocket() {
    ws = new WebSocket(wsUrl);
    ws.onmessage = function(event) {
        if(event.data === "update_kitchen") {
            cargarCocina();
            // Play notification sound
            const audio = new Audio('https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3');
            audio.play().catch(e => console.log('Autoplay prevenido por el navegador'));
            
            // Flash animation (visual alert)
            document.body.style.transition = "background-color 0.2s";
            document.body.style.backgroundColor = "#0f172a";
            setTimeout(() => { document.body.style.backgroundColor = "#1e293b"; }, 300);
        }
    };
    ws.onclose = function() {
        setTimeout(connectWebSocket, 5000); // Reconnect
    };
}
connectWebSocket();

async function toggleItemStatus(orderId, itemId, newStatus) {
    try {
        const res = await fetch(`/api/pos/orders/${orderId}/items/${itemId}/status`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
            body: JSON.stringify({status: newStatus})
        });
        if(res.ok) cargarCocina();
    } catch(e) {
        console.error(e);
    }
}

async function dispatchOrder(orderId) {
    if(!confirm("¿Despachar esta mesa? Se quitará de la pantalla de cocina.")) return;
    try {
        const res = await fetch(`/api/pos/orders/${orderId}/kitchen_status`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
            body: JSON.stringify({kitchen_status: 'ready'})
        });
        if(res.ok) cargarCocina();
    } catch(e) {
        console.error(e);
    }
}
