const token = localStorage.getItem("token");
if (!token) window.location.href = "login.html";

async function cargarCocina() {
  try {
    const res = await fetch("/kitchen_data", {
      headers: { Authorization: "Bearer " + token },
    });
    if (res.status === 401) {
      localStorage.removeItem("token");
      window.location.href = "login.html";
      return;
    }
    const items = await res.json();
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

    // Agrupar por orden (mesas y domicilios)
    const agrupado = {};
    items.forEach((i) => {
      if (!agrupado[i.order_id]) agrupado[i.order_id] = [];
      agrupado[i.order_id].push(i);
    });

    const grid = document.getElementById("kitchen-grid");
    grid.innerHTML = "";

    if (Object.keys(agrupado).length === 0) {
      grid.innerHTML =
        '<div class="col-12 text-center mt-5 text-secondary"><h4>✅ No hay pedidos pendientes</h4></div>';
    } else {
      for (const pedidos of Object.values(agrupado)) {
        const orderId = pedidos[0].order_id;
        const titulo = pedidos[0].is_delivery ? "🛵 " + esc(pedidos[0].table_name) : esc(pedidos[0].table_name).toUpperCase();
        let itemsHtml = pedidos
          .map((p) => {
            const notesHtml = p.notes
              ? `<div class="text-danger fw-bold ms-4 mb-1" style="font-size:0.9em; margin-top:-5px">👉 ${esc(p.notes)}</div>`
              : "";
            const isReady = p.status === "ready";
            const textClass = isReady
              ? "text-decoration-line-through text-muted"
              : "";
            const btnHtml = `<button class="btn btn-sm ${isReady ? "btn-secondary" : "btn-outline-success"} rounded-circle px-2 py-0 me-2" style="font-size:0.8rem" onclick="toggleItemStatus(${p.order_id}, ${p.id}, '${isReady ? "pending" : "ready"}')">✔</button>`;

            return `
                    <div class="d-flex align-items-center mb-1 ${textClass}">
                        ${btnHtml}
                        <span class="item-qty">${p.qty}x</span>
                        <span class="item-name">${esc(p.product_name)}</span>
                    </div>
                    ${notesHtml}
                    `;
          })
          .join("");

        grid.innerHTML += `
                    <div class="col-12 col-md-6 col-lg-4 col-xl-3">
                        <div class="ticket d-flex flex-column h-100">
                            <div class="mesa-title">${titulo}</div>
                            ${pedidos[0].is_delivery ? `<div class="mb-2 p-2 rounded" style="line-height:1.4;font-size:0.95rem;background:#fff7ed;border:1px solid #fdba74">
                              📞 <b>${esc(pedidos[0].customer_phone) || "Sin teléfono"}</b><br>
                              📍 ${esc(pedidos[0].delivery_address) || "Sin dirección"}</div>` : ""}
                            <div class="flex-grow-1">
                                ${itemsHtml}
                            </div>
                            <button class="btn btn-success mt-3 fw-bold w-100" onclick="dispatchOrder(${orderId})">✅ Pedido listo</button>
                        </div>
                    </div>
                `;
      }
    }

    const now = new Date();
    document.getElementById("last-update").innerText =
      `Última actualización: ${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}:${now.getSeconds().toString().padStart(2, "0")}`;
  } catch (e) {
    console.error("Error cargando cocina", e);
  }
}

cargarCocina(); // Carga inicial
// Respaldo: si la conexión en vivo falla, la pantalla igual se actualiza cada 15 s
setInterval(cargarCocina, 15000);

// Conexión WebSocket
const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
const wsUrl = `${protocol}//${window.location.host}/ws/kitchen?token=${token}`;
let ws;

function connectWebSocket() {
  ws = new WebSocket(wsUrl);
  ws.onmessage = function (event) {
    if (event.data === "update_kitchen") {
      cargarCocina();
      playChime(); // aviso sonoro (funciona sin internet)

      // Flash animation (visual alert)
      document.body.style.transition = "background-color 0.2s";
      document.body.style.backgroundColor = "#0f172a";
      setTimeout(() => {
        document.body.style.backgroundColor = "#1e293b";
      }, 300);
    }
  };
  ws.onclose = function () {
    setTimeout(connectWebSocket, 5000); // Reconnect
  };
}
connectWebSocket();

// Tono de aviso generado en el navegador: no depende de internet ni de sitios externos
let audioCtx = null;
function playChime() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const now = audioCtx.currentTime;
    [880, 1320].forEach((freq, i) => {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, now + i * 0.18);
      gain.gain.exponentialRampToValueAtTime(0.35, now + i * 0.18 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.18 + 0.35);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(now + i * 0.18);
      osc.stop(now + i * 0.18 + 0.4);
    });
  } catch (e) {
    /* el navegador bloquea el sonido hasta que alguien toque la pantalla */
  }
}
// El navegador solo permite sonido después de una interacción: se habilita al primer toque
document.addEventListener("click", () => {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    audioCtx.resume();
  } catch (e) {}
}, { once: true });

async function toggleItemStatus(orderId, itemId, newStatus) {
  try {
    const res = await fetch(
      `/api/pos/orders/${orderId}/items/${itemId}/status`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + token,
        },
        body: JSON.stringify({ status: newStatus }),
      },
    );
    if (res.ok) cargarCocina();
  } catch (e) {
    console.error(e);
  }
}

async function dispatchOrder(orderId) {
  if (!confirm("¿Marcar este pedido como listo? Se quitará de la pantalla de cocina."))
    return;
  try {
    const res = await fetch(`/api/pos/orders/${orderId}/kitchen_status`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + token,
      },
      body: JSON.stringify({ kitchen_status: "ready" }),
    });
    if (res.ok) cargarCocina();
  } catch (e) {
    console.error(e);
  }
}
