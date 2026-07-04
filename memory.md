# Memoria del Proyecto: Taquería Pro

Este documento registra todas las funcionalidades, configuraciones y módulos que se han desarrollado en el sistema Taquería Pro para asegurar que la inteligencia artificial (o futuros desarrolladores) tenga el contexto completo de lo que ya está construido.

## 🏗️ Arquitectura General
- **Backend:** Python con FastAPI (servidor en `api.py`). Base de datos en SQLite (`taqueria.db`) configurada en modo WAL para concurrencia.
- **Frontend:** Vanilla JavaScript, HTML5, CSS (Bootstrap 5). Sin frameworks pesados. Todo funciona como PWA (Progressive Web App).
- **Tiempo Real:** WebSockets (`/ws/kitchen`, `/ws/cfd`) para comunicación instantánea entre Cajero, Cocina y Pantalla de Clientes.
- **Sincronización Cloud:** Módulo `cloud_sync.py` que sincroniza los pedidos y estado de la base de datos local con un servidor central remoto en segundo plano.

## 🚀 Módulos Completados (v2.0 Franquicia)

### 1. Sistema POS (Punto de Venta) - `cashier.html`
- Toma de pedidos fluida con modificadores y notas por producto.
- Integración nativa con Impresoras Térmicas ESC/POS vía la API **Web Serial** (impresión silenciosa sin diálogos del navegador).
- Cobro multi-método (Efectivo, Tarjeta, Transferencia, Nequi/Daviplata).
- Bloqueo automático por inactividad (3 minutos) por seguridad.
- Arqueo de caja (Z-Report) automático y con impresión.

### 2. CRM y Fidelización (Puntos)
- Al ingresar el teléfono del cliente durante la venta, acumula 1 punto por cada $100 COP gastados.
- Si el cliente tiene puntos, el sistema muestra un badge azul y permite descontar dichos puntos del monto total a pagar.

### 3. Panel de Control (Admin) - `admin.html`
- **Dashboard Estadístico:** Integrado con `Chart.js` para mostrar tendencias de ventas (línea), productos más vendidos (barras) y métodos de pago (pastel).
- **Inventario y Mermas:** Registro de compras de insumos, stock mínimo, y un botón específico para registrar **Mermas** (pérdidas/caducidad) que se almacenan en `waste_logs`.
- **Gestión de Personal (CRUD):** Creación y eliminación de empleados (roles: admin, cajero, cocinero, mesero). Generación e impresión de credenciales QR para cada uno.
- **Control de Asistencia:** Los empleados escanean su QR para registrar entrada y salida, visible en el tab de Asistencia.
- **Generador de QR para Mesas (Self-Ordering):** Permite imprimir en bloque los QRs que identifican cada mesa del restaurante para el menú digital interactivo.

### 4. KDS (Kitchen Display System) - `kitchen.html`
- Visualización de pedidos en tiempo real (Sockets).
- Despacho parcial o total de los pedidos con notificaciones que viajan al CFD.
- Tiempos de preparación monitorizados para medir rendimiento por cocinero (Gamificación / Leaderboards).

### 5. CFD (Customer Facing Display) - `display.html`
- Pantalla pasiva que le muestra al cliente el estado de su ticket mientras espera.
- Carrusel de anuncios o publicidad para antojar a los clientes de promociones o adicionales.

### 6. Auto-Servicio (Menú QR) - `customer.html`
- Los clientes escanean el QR de su mesa, seleccionan sus platos y los envían directo al KDS y al POS como una orden pendiente.
- Diseño mobile-first.

---
**Última Actualización:** 02 de Julio de 2026.
**Estado:** Sistema 100% operativo en su versión "Franquicia" (Nivel 2.0).
