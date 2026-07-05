let mesaId = null;
let carrito = [];

// 1. Obtener estado de mesas desde la API
async function cargarMesas() {
  const res = await fetch("/tables/status", {
    headers: { "x-api-key": "123456" },
  });
  const mesas = await res.json();
  const div = document.getElementById("lista-mesas");
  div.innerHTML = "";

  mesas.forEach((m) => {
    const btnClass = m.is_open ? "btn-primary" : "btn-outline-secondary";
    div.innerHTML += `
            <div class="col-4">
                <button class="btn ${btnClass} w-100 btn-mesa shadow-sm" onclick="abrirMenu(${m.id}, ${m.table_number}, ${m.is_open})">
                    ${m.table_number}
                </button>
            </div>`;
  });
}

function abrirMenu(id, num, activa) {
  if (!activa) {
    Swal.fire({
      icon: "warning",
      title: "Mesa Cerrada",
      text: "La mesa debe ser abierta primero en la caja principal.",
    });
    return;
  }
  mesaId = id;
  document.getElementById("label-mesa").innerText = num;
  document.getElementById("view-mesas").style.display = "none";
  document.getElementById("view-menu").style.display = "block";
  document.getElementById("bar-pedido").style.display = "block";
  cargarProductos();
}

function irAMesas() {
  document.getElementById("view-mesas").style.display = "block";
  document.getElementById("view-menu").style.display = "none";
  document.getElementById("bar-pedido").style.display = "none";
  carrito = [];
  actualizarCart();
}

// 2. Cargar Menú desde la API
async function cargarProductos() {
  const res = await fetch("/menu", { headers: { "x-api-key": "123456" } });
  const prods = await res.json();
  const div = document.getElementById("grid-productos");
  div.innerHTML = "";

  prods.forEach((p) => {
    div.innerHTML += `
            <div class="col-6 col-md-4">
                <div class="card card-producto p-3 text-center h-100" onclick="agregarItem(${p.id})">
                    <div class="fw-bold">${p.name}</div>
                    <div class="text-primary small fw-bold mt-1">$${p.price_cop}</div>
                </div>
            </div>`;
  });
}

function agregarItem(id) {
  carrito.push({ product_id: id, qty: 1 });
  actualizarCart();
}

function actualizarCart() {
  document.getElementById("cart-count").innerText = carrito.length;
  document.getElementById("btn-enviar").disabled = carrito.length === 0;
}

// 3. Sincronizar con el Servidor (Paso 2)
async function confirmarPedido() {
  if (carrito.length === 0) return;
  const btn = document.getElementById("btn-enviar");
  btn.disabled = true;
  btn.innerText = "PROCESANDO...";

  try {
    for (const item of carrito) {
      await fetch("/add_to_order", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-api-key": "123456" },
        body: JSON.stringify({
          order_id: mesaId,
          product_id: item.product_id,
          qty: item.qty,
        }),
      });
    }
    Swal.fire({
      icon: "success",
      title: "¡Enviado!",
      text: "El pedido fue enviado a cocina",
      timer: 1500,
      showConfirmButton: false,
    });
    irAMesas();
    cargarMesas();
  } catch (e) {
    Swal.fire({
      icon: "error",
      title: "Error",
      text: "Error al conectar con el servidor.",
    });
    btn.disabled = false;
    btn.innerHTML = `<i class="fa-solid fa-paper-plane me-2"></i> ENVIAR A COCINA`;
  }
}

cargarMesas();
