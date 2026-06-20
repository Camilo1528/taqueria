const API_KEY = "123456";

async function cargarCocina() {
    try {
        const res = await fetch('/kitchen_data', { headers: {'x-api-key': API_KEY} });
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
                let itemsHtml = pedidos.map(p => `
                    <div class="d-flex align-items-center mb-2">
                        <span class="item-qty">${p.qty}x</span>
                        <span class="item-name">${p.product_name}</span>
                    </div>
                `).join('');

                grid.innerHTML += `
                    <div class="col-12 col-md-6 col-lg-4 col-xl-3">
                        <div class="ticket">
                            <div class="mesa-title">MESA ${mesa}</div>
                            ${itemsHtml}
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
const wsUrl = `${protocol}//${window.location.host}/ws/kitchen?api_key=${API_KEY}`;
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
