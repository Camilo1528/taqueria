# 🌮 Taquería Pro - Memory & Estado del Proyecto

## 🖥️ Servidor VPS
- **IP:** `173.249.2.17`
- **Dominio:** `elcultococina.com` (gestionado por Cloudflare)
- **Usuario SSH:** `root`
- **Contraseña SSH:** ⚠️ DESCONOCIDA — necesita ser recuperada del proveedor VPS
- **Directorio del proyecto en VPS:** `/opt/taqueria`
- **Cloudflare SSL:** Configurado en modo "Flexible"

## 🔑 Credenciales del Sistema
- **Admin login web:** `camilo152893@gmail.com` / `M@p#1953`
- **GitHub repo:** `https://github.com/Camilo1528/taqueria`
- **Cloudflare Token:** `<OCULTADO_POR_SEGURIDAD>`

## 🐳 Deploy en VPS
Cada vez que se hagan cambios, conectarse por SSH y ejecutar:
```bash
cd /opt/taqueria
git pull origin main
docker-compose up -d --build
```

## 📁 Estructura del Proyecto
```
taqueria/
├── backend/
│   ├── api.py              # FastAPI backend principal
│   ├── app/
│   │   ├── db.py           # Clase DB con métodos sqlite3
│   │   ├── paths.py        # Rutas de archivos (DB_PATH etc.)
│   │   ├── security.py     # JWT y bcrypt
│   │   └── utils.py        # Utilidades generales
│   ├── data/
│   │   └── taqueria.db     # Base de datos SQLite
│   ├── backups/            # Backups automáticos diarios (3am)
│   ├── qr_output/          # QR generados por mesa
│   ├── tickets/            # Tickets de venta generados
│   └── run_all.py          # Script para correr localmente
├── frontend/
│   ├── login.html          # Página de inicio de sesión
│   ├── admin.html          # Panel administrador
│   ├── cashier.html        # Punto de venta / caja
│   ├── kitchen.html        # Pantalla de cocina (WebSocket)
│   ├── waiter.html         # Pantalla de mesero
│   ├── customer.html       # Menú auto-servicio (QR)
│   ├── delivery.html       # Gestión de domicilios
│   ├── display.html        # Pantalla CFD / display cliente
│   ├── ticket.html         # Plantilla ticket térmico 80mm [NUEVO]
│   ├── core.js             # Funciones JS compartidas [NUEVO]
│   ├── manifest.json       # PWA manifest [NUEVO]
│   ├── sw.js               # Service Worker offline [NUEVO]
│   └── menu_board.html     # Tablero de menú digital
└── docker-compose.yml      # Configuración Docker
```

## 🗄️ Base de Datos - Tablas Principales
| Tabla | Descripción |
|-------|-------------|
| `users` | Usuarios con roles: admin, cashier, cook, waiter, driver |
| `tables` | Mesas con estado y orden activa |
| `orders` | Órdenes (mesa, domicilio, etc.) |
| `order_items` | Items de cada orden |
| `products` | Productos del menú con `category_id` |
| `categories` | Categorías de productos |
| `inventory_items` | Inventario con stock actual y mínimo |
| `recipe_items` | Recetas: qué inventario consume cada producto |
| `cash_shifts` | Turnos de caja y arqueos |
| `expenses` | Gastos y salidas de caja |
| `customers` | Clientes con programa de puntos |
| `attendance_logs` | Registro de asistencia del personal |
| `reservations` | Reservas de mesas |
| `ads` | Anuncios para pantalla CFD |
| `vouchers` | Bonos de regalo |
| `waste_logs` | Registro de mermas |
| `purchases` | Compras a proveedores |

## 🔌 API Endpoints Principales
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/login` | Login con usuario/contraseña → JWT |
| POST | `/api/login/pin` | Login con PIN de 4-6 dígitos |
| GET | `/api/customer/menu` | Menú público (sin auth) |
| POST | `/api/customer/order` | Crear orden desde QR cliente |
| GET | `/api/categories` | Categorías de productos [NUEVO] |
| GET | `/api/admin/reports/custom` | Reporte por rango de fechas [NUEVO] |
| GET | `/api/admin/backup` | Descargar backup de DB |
| POST | `/api/pos/pay` | Procesar pago de orden |
| GET | `/branding` | Nombre, logo y color del negocio |
| WS | `/ws/kitchen` | WebSocket cocina en tiempo real |
| WS | `/ws/cfd` | WebSocket pantalla CFD |

## ✅ Mejoras Implementadas (Jul 2026)
- [x] **Backup manual**: Botón en admin panel para descargar DB
- [x] **PWA / Modo Offline**: `manifest.json` + `sw.js` en todos los HTML
- [x] **`core.js` centralizado**: `AUTH()`, `TOKEN()`, `toast()`, `logout()` compartidos
- [x] **Reportes por fechas**: Endpoint + UI con exportar CSV en admin panel
- [x] **Ticket térmico 80mm**: `ticket.html` con auto-print, botón 🖨️ en caja
- [x] **Filtros de categoría**: Pestañas en `customer.html`, agrupación por categoría

## ⏳ Pendiente de Deploy
El código está en GitHub pero **aún no se ha hecho `git pull` en el VPS**.
Para activar todas las mejoras, ejecutar en el servidor:
```bash
cd /opt/taqueria && git pull origin main && docker-compose up -d --build
```

## 🛠️ Cómo Correr Localmente
```bash
cd taqueria/backend
python run_all.py
# Acceder en: http://localhost:8000/login.html
```

## 📋 Roles de Usuarios
| Rol | Acceso |
|-----|--------|
| `admin` | Todo: reportes, inventario, usuarios, configuración |
| `cashier` | Caja, pagos, arqueo de turno |
| `cook` | Pantalla de cocina, actualizar estado de items |
| `waiter` | Tomar pedidos, ver menú |
| `driver` | Gestión de domicilios |

## 🔧 Solución de Problemas Comunes
| Problema | Solución |
|---------|----------|
| Error 522 en Cloudflare | Verificar que Docker esté corriendo: `docker ps` |
| Cloudflare SSL error | Mantener SSL en modo "Flexible" en Cloudflare |
| WebSocket no conecta | Verificar que el token de la sesión de cocina sea válido |
| DB no persiste al reiniciar | Verificar volúmenes en `docker-compose.yml` |
| Login falla | Verificar que `run_all.py` esté corriendo (local) o Docker (VPS) |
