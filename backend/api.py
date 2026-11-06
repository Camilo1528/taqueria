import os
from fastapi import FastAPI, HTTPException, Security, Depends, WebSocket, WebSocketDisconnect, Header, UploadFile, File, Request
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from app.db import db
from app.db import db as _db
from dotenv import load_dotenv
import threading
import schedule
import time
import zipfile
import datetime
import logging
import secrets
import sqlite3
from collections import defaultdict

logging.basicConfig(filename='taqueria_server.log', level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("API")

load_dotenv()

# Inicialización de la API
app = FastAPI(title="Taquería Pro API")

# Ciberseguridad: Cargar clave desde .env y limitar CORS
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    logger.warning("API_KEY no está definida: los endpoints que la requieren quedarán bloqueados.")
api_key_header = APIKeyHeader(name="x-api-key")

# Orígenes permitidos separados por coma, p.ej. "http://192.168.1.10:8000,https://mitaqueria.com"
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors or ["*"],
    allow_credentials=bool(_cors),  # nunca credenciales con comodín "*"
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.kitchen_connections: List[WebSocket] = []
        self.cfd_connections: List[WebSocket] = []

    async def connect_kitchen(self, websocket: WebSocket):
        await websocket.accept()
        self.kitchen_connections.append(websocket)

    def disconnect_kitchen(self, websocket: WebSocket):
        if websocket in self.kitchen_connections:
            self.kitchen_connections.remove(websocket)

    async def connect_cfd(self, websocket: WebSocket):
        await websocket.accept()
        self.cfd_connections.append(websocket)

    def disconnect_cfd(self, websocket: WebSocket):
        if websocket in self.cfd_connections:
            self.cfd_connections.remove(websocket)

    @staticmethod
    async def _broadcast(connections: List[WebSocket], message: str):
        # Un dispositivo desconectado no debe tumbar la petición que avisa a los demás
        for connection in list(connections):
            try:
                await connection.send_text(message)
            except Exception:
                if connection in connections:
                    connections.remove(connection)

    async def broadcast_kitchen(self, message: str):
        await self._broadcast(self.kitchen_connections, message)

    async def broadcast_cfd(self, message: str):
        await self._broadcast(self.cfd_connections, message)

manager = ConnectionManager()

def get_api_key(api_key: str = Security(api_key_header)):
    if not API_KEY or not secrets.compare_digest(api_key or "", API_KEY):
        raise HTTPException(status_code=403, detail="Clave de API inválida")
    return api_key

# Modelo para recibir datos de productos desde el celular
class OrderItem(BaseModel):
    order_id: int
    product_id: int
    qty: int = Field(gt=0, le=100)

class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_cop: float = Field(ge=0)
    category_id: Optional[int] = None
    image_url: Optional[str] = None
    is_reward: Optional[int] = 0

class ProductResponse(BaseModel):
    id: int
    name: str
    price_cop: float
    category_id: Optional[int] = None
    image_url: Optional[str] = None
    is_reward: Optional[int] = 0

class CustomerOrderItem(BaseModel):
    product_id: int
    qty: int = Field(gt=0, le=100)
    notes: Optional[str] = Field(default="", max_length=300)

class CustomerOrderSchema(BaseModel):
    table_id: Optional[int] = None
    items: List[CustomerOrderItem] = Field(min_length=1, max_length=50)
    is_donation: bool = False
    is_delivery: bool = False
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    delivery_address: Optional[str] = None

class TableResponse(BaseModel):
    id: int
    name: str
    is_open: int
    current_order_id: Optional[int]
from app.security import verify_token, create_access_token

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/login")
def login(req: LoginRequest):
    success, msg, user = db.authenticate_user(req.username, req.password, __import__('app.security', fromlist=['verify_password']).verify_password)
    if not success:
        raise HTTPException(status_code=401, detail=msg)

    token = create_access_token({"sub": user["username"], "role": user["role"], "id": user["id"]})
    return {"token": token, "role": user["role"], "username": user["username"]}

class PinLoginRequest(BaseModel):
    pin: str

# Límite de intentos fallidos por IP para frenar la fuerza bruta de PINs.
_failed_logins: dict = defaultdict(list)
_MAX_FAILS, _WINDOW_SECONDS = 5, 300

def _check_rate_limit(ip: str) -> None:
    now = time.time()
    _failed_logins[ip] = [t for t in _failed_logins[ip] if now - t < _WINDOW_SECONDS]
    if len(_failed_logins[ip]) >= _MAX_FAILS:
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera unos minutos.")

@app.post("/api/login/pin")
def login_pin(req: PinLoginRequest, request: Request):
    ip = request.client.host if request.client else "?"
    _check_rate_limit(ip)
    success, msg, user = db.authenticate_pin(req.pin)
    if not success:
        _failed_logins[ip].append(time.time())
        raise HTTPException(status_code=401, detail=msg)
    _failed_logins.pop(ip, None)
    token = create_access_token({"sub": user["username"], "role": user["role"], "id": user["id"]})
    return {"token": token, "role": user["role"], "username": user["username"]}

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No autorizado")
    token = authorization.split(" ")[1]
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")
    return payload


def require_roles(*roles: str):
    """Dependencia que exige que el usuario tenga uno de los roles indicados."""
    def checker(current_user: dict = Depends(get_current_user)):
        if current_user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="No tienes permisos para esta acción")
        return current_user
    return checker

require_admin = require_roles("admin")
require_manager = require_roles("admin", "cajero")

# Integraciones reales: DIAN (interruptor), sincronización entre sedes y pagos Wompi
from app.integrations import build_router as _integrations_router, ensure_integrations_schema, sync_worker
ensure_integrations_schema()
app.include_router(_integrations_router(get_current_user, require_admin, require_manager, get_api_key,
                                        close_order=lambda oid, method: db.close_order_with_inventory(oid, method)))
threading.Thread(target=sync_worker, daemon=True).start()

# Fidelización, bonos y donaciones
from app.rewards import build_router as _rewards_router, ensure_rewards_schema, apply_loyalty, find_customer
ensure_rewards_schema()
app.include_router(_rewards_router(get_current_user, require_manager))

# Endpoints que el frontend usaba y faltaban (anuncios, PIN admin, domicilio público, ticket, producción)
from app.extras import build_router as _extras_router, ensure_extras_schema
ensure_extras_schema()
app.include_router(_extras_router(
    get_current_user,
    check_rate_limit=_check_rate_limit,
    register_fail=lambda ip: _failed_logins[ip].append(time.time()),
    broadcast_kitchen=manager.broadcast_kitchen,
    get_zones=lambda: get_delivery_zones(),
    require_manager=require_manager,
))

# Turnos de caja, validación contable diaria y cierre de mes
from app.accounting import build_router as _accounting_router, ensure_accounting_schema
ensure_accounting_schema()
app.include_router(_accounting_router(get_current_user, require_manager))


@app.get("/menu", response_model=List[ProductResponse])
def get_menu(current_user: dict = Depends(get_current_user)):
    """Retorna los productos activos para que el mesero los vea en su dispositivo."""
    try:
        # Consulta directamente la base de datos configurada en app/db.py
        productos = db.all("SELECT id, name, price_cop, category_id, image_url, is_reward FROM products WHERE active=1")
        return [dict(p) for p in productos]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/categories")
async def get_categories():
    rows = db.all("SELECT id, name FROM categories")
    return [dict(r) for r in rows]

@app.get("/api/admin/reports/custom")
async def custom_report(start_date: str, end_date: str, current_user: dict = Depends(require_admin)):
    try:
        if datetime.date.fromisoformat(start_date) > datetime.date.fromisoformat(end_date):
            raise HTTPException(status_code=400, detail="La fecha inicial es posterior a la final")
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido (AAAA-MM-DD)")
    rows = db.all("SELECT payment_method, total_cop FROM orders WHERE status='closed' AND branch_id IS NULL AND substr(closed_at,1,10) BETWEEN ? AND ?", (start_date, end_date))
    items = db.all("SELECT product_name, SUM(qty) qty FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.status='closed' AND o.branch_id IS NULL AND substr(o.closed_at,1,10) BETWEEN ? AND ? GROUP BY product_name ORDER BY qty DESC", (start_date, end_date))
    total = sum(r['total_cop'] for r in rows)
    by_payment = {}
    for r in rows:
        m = r['payment_method'] or 'sin_definir'
        by_payment[m] = by_payment.get(m, 0) + r['total_cop']
    return {'total': total, 'orders': len(rows), 'by_payment': by_payment, 'items': [dict(i) for i in items]}


@app.post("/api/products")
def create_product(data: ProductCreate, current_user: dict = Depends(require_manager)):
    try:
        db.execute(
            "INSERT INTO products (name, price_cop, category_id, image_url, is_reward, active) VALUES (?, ?, ?, ?, ?, 1)",
            (data.name, data.price_cop, data.category_id, data.image_url, data.is_reward)
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/products/{product_id}")
def update_product(product_id: int, data: ProductCreate, current_user: dict = Depends(require_manager)):
    try:
        db.execute(
            "UPDATE products SET name=?, price_cop=?, category_id=?, image_url=?, is_reward=? WHERE id=?",
            (data.name, data.price_cop, data.category_id, data.image_url, data.is_reward, product_id)
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/products/{product_id}")
def delete_product(product_id: int, current_user: dict = Depends(require_manager)):
    try:
        db.execute("UPDATE products SET active=0 WHERE id=?", (product_id,))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/customer/menu", response_model=List[ProductResponse])
def get_customer_menu():
    """Public endpoint for customers scanning the QR code"""
    try:
        productos = db.all("SELECT id, name, price_cop, category_id, image_url, is_reward FROM products WHERE active=1")
        return [dict(p) for p in productos]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/customer/order")
async def place_customer_order(data: CustomerOrderSchema):
    """Customer submits an order from their phone"""
    try:
        order_id = None
        if data.is_donation:
            order_id = db.insert("INSERT INTO orders (status, table_name, total_cop) VALUES ('open', 'Donacion', 0)", ())
        elif data.is_delivery:
            if not (data.customer_name and data.customer_phone and data.delivery_address):
                raise HTTPException(status_code=400, detail="Nombre, teléfono y dirección son obligatorios para domicilio")
            order_id = db.insert(
                "INSERT INTO orders (status, table_name, total_cop, is_delivery, customer_name, customer_phone, delivery_address) VALUES ('open', ?, 0, 1, ?, ?, ?)",
                (f"Domicilio - {data.customer_name}", data.customer_name, data.customer_phone, data.delivery_address)
            )
        else:
            if data.table_id is None:
                raise HTTPException(status_code=400, detail="Falta la mesa")
            table = db.one("SELECT * FROM tables WHERE id=?", (data.table_id,))
            if not table:
                raise HTTPException(status_code=404, detail="Mesa no encontrada")

            order_id = table['current_order_id']

            # Si la mesa no tiene orden abierta, creamos una
            if not order_id:
                order_id = db.insert("INSERT INTO orders (status, table_name, total_cop) VALUES ('open', ?, 0)", (f"Mesa {data.table_id}",))
                db.execute("UPDATE tables SET is_open=1, current_order_id=? WHERE id=?", (order_id, data.table_id))

        # Añadimos los productos
        for item in data.items:
            product = db.one("SELECT name, price_cop FROM products WHERE id=? AND active=1", (item.product_id,))
            if product:
                actual_price = 0 if data.is_donation else product['price_cop']
                total = actual_price * item.qty
                db.execute(
                    """INSERT INTO order_items (order_id, product_id, product_name, qty, price_cop, total_cop, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, item.product_id, product['name'], item.qty, actual_price, total, item.notes)
                )

        # Recalculamos el total
        subtotal_row = db.one("SELECT SUM(total_cop) as sub FROM order_items WHERE order_id=?", (order_id,))
        total_val = subtotal_row['sub'] if subtotal_row['sub'] else 0
        db.execute("UPDATE orders SET total_cop=? WHERE id=?", (total_val, order_id))

        await manager.broadcast_kitchen("update_kitchen")
        return {"status": "success", "order_id": order_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error procesando orden de cliente: {e}")
        raise HTTPException(status_code=500, detail=f"Error al procesar: {str(e)}")

@app.get("/tables/status", response_model=List[TableResponse])
def get_tables_status(current_user: dict = Depends(get_current_user)):
    """Permite al mesero visualizar el estado de las mesas en tiempo real."""
    mesas = db.all("SELECT id, name, is_open, current_order_id FROM tables")
    return [dict(m) for m in mesas]

@app.post("/add_to_order")
async def add_to_order(item: OrderItem, current_user: dict = Depends(get_current_user)):
    """Procesa el pedido enviado desde la tablet y actualiza la orden en la base de datos."""
    order = db.one("SELECT status FROM orders WHERE id=?", (item.order_id,))
    if not order or order['status'] != 'open':
        raise HTTPException(status_code=400, detail="La orden no existe o ya está cerrada")
    product = db.one("SELECT name, price_cop FROM products WHERE id=? AND active=1", (item.product_id,))

    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    try:
        total = product['price_cop'] * item.qty
        # Inserta el item con estado 'pending' para que aparezca en la pantalla de cocina
        db.execute(
            """INSERT INTO order_items (order_id, product_id, product_name, qty, price_cop, total_cop, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (item.order_id, item.product_id, product['name'], item.qty, product['price_cop'], total)
        )

        # Recalcula los totales de la orden para que el cajero vea el valor actualizado
        subtotal_row = db.one("SELECT SUM(total_cop) as sub FROM order_items WHERE order_id=?", (item.order_id,))
        subtotal = subtotal_row['sub'] if subtotal_row['sub'] else 0

        db.execute("UPDATE orders SET total_cop=? WHERE id=?", (subtotal, item.order_id))

        await manager.broadcast_kitchen("update_kitchen")
        logger.info(f"Nuevo pedido procesado: {product['name']} x{item.qty}")
        return {"status": "success", "message": f"Añadido: {product['name']} x{item.qty}"}
    except Exception as e:
        logger.error(f"Error procesando orden en add_to_order: {e}")
        raise HTTPException(status_code=500, detail=f"Error al procesar: {str(e)}")

@app.get("/kitchen_data")
def get_kitchen_data(current_user: dict = Depends(get_current_user)):
    """Devuelve los ítems pendientes agrupados para la pantalla de cocina."""
    items = db.all('''
        SELECT oi.*, oi.product_name, t.id AS table_number,
               COALESCE(t.name, o.table_name, 'Orden #' || o.id) AS table_name, o.is_delivery,
               o.customer_name, o.customer_phone, o.delivery_address
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        LEFT JOIN tables t ON t.current_order_id = o.id
        WHERE oi.status = 'pending' AND o.status = 'open'
        ORDER BY oi.id
    ''')
    return [dict(i) for i in items]

@app.get("/branding")
def get_branding():
    import json
    import os
    try:
        path = os.path.join(os.path.dirname(__file__), "branding.json")
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        # Este endpoint es público: nunca devolver llaves ni URLs internas
        for secret in ("dian_api_key", "master_server_url", "master_api_key"):
            data.pop(secret, None)
        from app.integrations import public_flags
        data.update(public_flags())
        return data
    except (OSError, ValueError):
        return {"business_name": "Restaurante", "theme_color": "#10b981", "logo_url": ""}

class BrandingSchema(BaseModel):
    business_name: str
    theme_color: str
    branch_id: str
    logo_url: Optional[str] = ""
    whatsapp_number: Optional[str] = ""
    loyalty_enabled: Optional[bool] = True
    delivery_zones: Optional[List[dict]] = None

@app.post("/branding")
def update_branding(data: BrandingSchema, current_user: dict = Depends(require_admin)):
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), "branding.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            existing = json.load(f)
    except (OSError, ValueError):
        existing = {}

    # Conservar el logo si no se envía uno nuevo
    if not data.logo_url and "logo_url" in existing:
        data.logo_url = existing["logo_url"]

    merged = {**existing, **data.model_dump()}
    # Claves antiguas que ya no viven aquí (branding.json es público):
    # la llave DIAN pasó a Integraciones y las imágenes a la sección Publicidad.
    for legacy in ("dian_api_key", "ad_images"):
        merged.pop(legacy, None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return {"status": "ok"}

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

def _save_upload(file: UploadFile, filepath: str) -> None:
    """Guarda el archivo subido con límite de tamaño. Escribe en un temporal y solo
    reemplaza el destino si todo salió bien (así no se daña, p. ej., el logo actual)."""
    tmp = filepath + ".part"
    total = 0
    try:
        with open(tmp, "wb") as buffer:
            while True:
                chunk = file.file.read(1024 * 256)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="La imagen pesa más de 5 MB. Redúcela e intenta de nuevo.")
                buffer.write(chunk)
        os.replace(tmp, filepath)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

def _safe_image_ext(file: UploadFile) -> str:
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_IMAGE_EXT or not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Solo se permiten imágenes PNG, JPG, WEBP o GIF")
    return ext

@app.post("/api/upload_logo")
async def upload_logo(file: UploadFile = File(...), current_user: dict = Depends(require_admin)):
    import os
    uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    ext = _safe_image_ext(file)
    filename = f"logo.{ext}"
    filepath = os.path.join(uploads_dir, filename)

    _save_upload(file, filepath)

    return {"status": "ok", "url": f"/uploads/{filename}"}

@app.post("/api/upload_image")
async def upload_image(file: UploadFile = File(...), current_user: dict = Depends(require_manager)):
    import os
    import uuid
    uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    ext = _safe_image_ext(file)
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(uploads_dir, filename)

    _save_upload(file, filepath)

    return {"status": "ok", "url": f"/uploads/{filename}"}

def _cop(v) -> str:
    return "$" + f"{round(v or 0):,.0f}".replace(",", ".")


def business_insights(summary: dict) -> list:
    """Lecturas útiles para el dueño, calculadas con las ventas, el inventario y las cuentas reales."""
    out = []
    today = datetime.date.today()
    hoy_total = summary.get("total") or 0
    hoy_ordenes = summary.get("orders") or 0
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

    # 1. Hoy vs. el mismo día de la semana (últimas 4 semanas)
    prev = [(today - datetime.timedelta(weeks=w)).isoformat() for w in range(1, 5)]
    rows = db.all("SELECT substr(closed_at,1,10) d, SUM(total_cop) v, COUNT(*) n FROM orders "
                  "WHERE status='closed' AND branch_id IS NULL AND substr(closed_at,1,10) IN (?,?,?,?) GROUP BY d", tuple(prev))
    if rows:
        prom = sum(r["v"] or 0 for r in rows) / len(rows)
        if prom > 0:
            hora = datetime.datetime.now().hour
            pct = (hoy_total - prom) / prom * 100
            base = f"Hoy llevas {_cop(hoy_total)} en ventas; un {dias[today.weekday()]} normal cierra en {_cop(prom)} (promedio de {len(rows)} semanas)."
            if hoy_total >= prom:
                out.append(base + f" Ya lo superaste en {pct:.0f}%.")
            elif hora >= 20:
                out.append(base + f" Vas {abs(pct):.0f}% por debajo.")
            else:
                out.append(base)
    elif hoy_total:
        out.append(f"Hoy llevas {_cop(hoy_total)} en {hoy_ordenes} {'orden' if hoy_ordenes == 1 else 'órdenes'}. Con más semanas de datos podré compararlo con días anteriores.")

    # 2. Ticket promedio hoy vs. últimos 28 días
    t28 = db.one("SELECT AVG(total_cop) v FROM orders WHERE status='closed' AND branch_id IS NULL AND total_cop > 0 "
                 "AND substr(closed_at,1,10) >= ? AND substr(closed_at,1,10) < ?",
                 ((today - datetime.timedelta(days=28)).isoformat(), today.isoformat()))["v"]
    if hoy_ordenes and t28:
        t_hoy = hoy_total / hoy_ordenes
        dif = (t_hoy - t28) / t28 * 100
        if abs(dif) >= 10:
            out.append(f"El ticket promedio de hoy es {_cop(t_hoy)}, {abs(dif):.0f}% {'más alto' if dif > 0 else 'más bajo'} que el de las últimas 4 semanas ({_cop(t28)}).")

    # 3. Producto estrella del día
    if summary.get("items"):
        top = summary["items"][0]
        out.append(f"Lo más vendido hoy: {top['product_name']} ({top['qty']:g} unidades).")

    # 4. Hora pico de los últimos 7 días
    pico = db.one("SELECT substr(closed_at,12,2) h, COUNT(*) n FROM orders WHERE status='closed' AND branch_id IS NULL "
                  "AND substr(closed_at,1,10) >= ? GROUP BY h ORDER BY n DESC LIMIT 1",
                  ((today - datetime.timedelta(days=7)).isoformat(),))
    if pico and pico["h"]:
        h = int(pico["h"])
        out.append(f"Tu hora más fuerte de la última semana es entre las {h}:00 y las {h + 1}:00 ({pico['n']} órdenes): ten la cocina y la caja completas a esa hora.")

    # 5. Inventario por debajo del mínimo
    bajos = db.all("SELECT name, stock_current, stock_min, COALESCE(stock_max,0) stock_max FROM inventory_items "
                   "WHERE stock_current <= stock_min AND COALESCE(active,1)=1 ORDER BY (stock_current - stock_min) ASC")
    if bajos:
        lista = ", ".join(f"{b['name']} (pedir {max(0, (b['stock_max'] or b['stock_min'] * 2) - b['stock_current']):g})" for b in bajos[:3])
        extra = f" y {len(bajos) - 3} más" if len(bajos) > 3 else ""
        out.append(f"{len(bajos)} productos de inventario están en o bajo el mínimo: {lista}{extra}. Revisa la columna «A pedir».")

    # 6. Cuentas abiertas hace mucho
    viejas = db.one("SELECT COUNT(*) n FROM orders WHERE status='open' AND created_at IS NOT NULL "
                    "AND created_at <= ?", ((datetime.datetime.now() - datetime.timedelta(minutes=45)).isoformat(timespec="seconds"),))["n"]
    if viejas:
        out.append(f"Hay {viejas} cuenta(s) abiertas hace más de 45 minutos: confirma con los meseros si ya se pueden cobrar.")

    if not out:
        out.append("Todavía no hay movimientos hoy. Apenas se registren ventas verás aquí el análisis del día.")
    return out


@app.get("/dashboard_data")
def get_dashboard_data(current_user: dict = Depends(require_manager)):
    summary = db.sales_summary_today()
    # Análisis del negocio calculado con los datos reales (no son frases fijas)
    insights = business_insights(summary)
    summary['ai_insights'] = insights
    # Cumpleaños de empleados activos en el mes actual (para el panel principal)
    month = f"-{datetime.datetime.now().month:02d}-"
    summary['birthdays'] = [dict(r) for r in db.all(
        "SELECT id, username, first_name, last_name, birth_date FROM users "
        "WHERE active=1 AND birth_date LIKE ? ORDER BY substr(birth_date, 9, 2)", ('%' + month + '%',))]
    return summary

class CFDUpdate(BaseModel):
    order_id: Optional[int] = None
    table: Optional[str] = None
    items: List[dict]
    total: float

@app.post("/api/cfd_update")
async def cfd_update(data: CFDUpdate, current_user: dict = Depends(require_manager)):
    """La caja envía la cuenta que está cobrando a la pantalla del cliente."""
    await manager.broadcast_cfd(data.model_dump_json())
    return {"status": "ok"}

@app.websocket("/ws/kitchen")
async def websocket_endpoint(websocket: WebSocket, token: str = None, api_key: str = None):
    if API_KEY and api_key and secrets.compare_digest(api_key, API_KEY):
        pass
    elif token:
        payload = verify_token(token)
        if not payload:
            await websocket.close(code=1008, reason="Invalid Token")
            return
    else:
        await websocket.close(code=1008, reason="Invalid Credentials")
        return
    await manager.connect_kitchen(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_kitchen(websocket)

@app.websocket("/ws/cfd")
async def websocket_cfd(websocket: WebSocket, api_key: str = None, token: str = None):
    # Acepta la sesión del cajero (pantalla en el mismo equipo) o la API key (equipos dedicados)
    ok_key = bool(API_KEY and api_key and secrets.compare_digest(api_key, API_KEY))
    ok_token = bool(token and verify_token(token))
    if not (ok_key or ok_token):
        await websocket.close(code=1008, reason="Credenciales inválidas")
        return
    await manager.connect_cfd(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_cfd(websocket)



def backup_db():
    backup_dir = os.path.join(os.path.dirname(__file__), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    from app.paths import DB_PATH
    if not os.path.exists(DB_PATH):
        return
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    snapshot = os.path.join(backup_dir, f"snapshot_{stamp}.db")
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(snapshot)
    try:
        src.backup(dst)  # copia consistente aunque haya escrituras en curso
    finally:
        dst.close()
        src.close()
    zip_name = os.path.join(backup_dir, f"backup_{stamp}.zip")
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(snapshot, "taqueria.db")
    os.remove(snapshot)

@app.get("/api/admin/backup")
def download_backup(current_user: dict = Depends(require_admin)):

    # Run a fresh backup right now before downloading
    backup_db()

    import glob
    backup_dir = os.path.join(os.path.dirname(__file__), "backups")
    list_of_files = glob.glob(f"{backup_dir}/*.zip")
    if not list_of_files:
        raise HTTPException(status_code=404, detail="No hay backups disponibles")

    latest_file = max(list_of_files, key=os.path.getctime)
    return FileResponse(path=latest_file, filename=os.path.basename(latest_file), media_type='application/zip')

schedule.every().day.at("03:00").do(backup_db)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)

threading.Thread(target=run_scheduler, daemon=True).start()


class ItemNotesSchema(BaseModel):
    notes: str

PAYMENT_METHODS = {"efectivo", "tarjeta", "donacion", "transferencia", "nequi", "daviplata", "bono", "mixto", "online"}

class PaymentSchema(BaseModel):
    order_id: int
    method: str
    cedula: Optional[str] = Field(default=None, max_length=20)
    tip_amount: float = Field(default=0.0, ge=0)
    redeemed_product_id: Optional[int] = None
    delivery_fee: Optional[float] = Field(default=None, ge=0, le=200000)

@app.post("/api/pos/pay")
def process_payment(data: PaymentSchema, current_user: dict = Depends(get_current_user)):
    import json, os
    method = data.method.strip().lower()
    if method not in PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail=f"Método de pago no válido: {data.method}")
    current = db.one("SELECT status, total_cop FROM orders WHERE id=?", (data.order_id,))
    if not current:
        raise HTTPException(status_code=404, detail="La orden no existe")
    if current["status"] != "open":
        raise HTTPException(status_code=400, detail="La orden ya fue cobrada")
    path = os.path.join(os.path.dirname(__file__), "branding.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            branding = json.load(f)
            loyalty_enabled = branding.get("loyalty_enabled", True)
    except (OSError, ValueError):
        loyalty_enabled = True

    voucher_code = None  # se conserva en la respuesta por compatibilidad con la caja
    loyalty = None
    # Bono que no cubre todo: el resto se paga con otro método. Si ya cubrió todo, el método es "bono".
    if method == "bono":
        o = db.one("SELECT total_cop, delivery_fee_cop, voucher_amount_cop FROM orders WHERE id=?", (data.order_id,))
        if (o["voucher_amount_cop"] or 0) < (o["total_cop"] or 0) + (o["delivery_fee_cop"] or 0):
            raise HTTPException(status_code=400, detail="El bono no cubre el total; cobra el resto con otro método")
    if method == "donacion":
        # Una donación no se cobra: los productos quedan en $0 (el valor de referencia queda en contabilidad)
        db.execute("UPDATE order_items SET price_cop=0, total_cop=0 WHERE order_id=?", (data.order_id,))
        db.execute("UPDATE orders SET total_cop=0, tip_amount_cop=0 WHERE id=?", (data.order_id,))
        data.tip_amount = 0
    if data.cedula and loyalty_enabled and method != "donacion":
        loyalty = apply_loyalty(data.order_id, data.cedula, data.redeemed_product_id)

    db.execute("UPDATE orders SET tip_amount_cop = ? WHERE id = ?", (data.tip_amount, data.order_id))
    if data.delivery_fee is not None:
        db.execute("UPDATE orders SET delivery_fee_cop = ? WHERE id = ?", (data.delivery_fee, data.order_id))
    success, msg = db.close_order_with_inventory(data.order_id, method)
    if success:
        from app.utils import write_ticket
        order = db.one("SELECT * FROM orders WHERE id=?", (data.order_id,))
        items = db.all("SELECT * FROM order_items WHERE order_id=?", (data.order_id,))
        if order:
            write_ticket(data.order_id, str(order['table_name'] or 'Mesa'), items, order['total_cop'], method)
        return {"status": "ok", "message": msg, "voucher_code": voucher_code, "loyalty": loyalty}
    else:
        raise HTTPException(status_code=400, detail=msg)


@app.get("/api/loyalty/rewards")
def get_loyalty_rewards():
    prods = db.all("SELECT id, name FROM products WHERE is_reward=1 AND active=1")
    return [dict(p) for p in prods]

@app.get("/api/loyalty/{cedula}")
def get_loyalty_points(cedula: str, current_user: dict = Depends(get_current_user)):
    c = find_customer(cedula)  # acepta cédula o teléfono
    return {"points": c['points'] if c else 0}

class AttendanceSchema(BaseModel):
    pin: str

@app.post("/api/attendance/log")
def log_attendance(data: AttendanceSchema, request: Request):
    ip = request.client.host if request.client else "?"
    _check_rate_limit(ip)  # evita probar PINs uno tras otro
    user = db.one("SELECT * FROM users WHERE pin=? AND active=1", (data.pin,))
    if not user:
        _failed_logins[ip].append(time.time())
        raise HTTPException(status_code=404, detail="PIN no reconocido")

    # Determinar si es entrada o salida (busca el último registro)
    last_log = db.one("SELECT log_type FROM attendance_logs WHERE user_id=? ORDER BY id DESC LIMIT 1", (user['id'],))
    new_type = 'out' if last_log and last_log['log_type'] == 'in' else 'in'

    timestamp = datetime.datetime.now().isoformat()
    db.execute("INSERT INTO attendance_logs (user_id, log_type, timestamp) VALUES (?,?,?)", (user['id'], new_type, timestamp))
    return {"status": "ok", "type": new_type, "user": user['first_name'] or user['username']}

@app.get("/api/pos/orders")
def get_open_orders(current_user: dict = Depends(get_current_user)):
    # Mesas abiertas + domicilios (que no tienen mesa) pendientes de cobro
    orders = db.all("""SELECT o.*, t.id AS table_number, COALESCE(t.name, o.table_name) AS table_name
                       FROM orders o LEFT JOIN tables t ON t.current_order_id = o.id
                       WHERE o.status='open' AND (t.id IS NOT NULL OR o.is_delivery=1 OR o.table_name LIKE 'Domicilio%'
                              OR o.table_name = 'Donacion')
                       ORDER BY o.id""")
    res = []
    for o in orders:
        items = db.all("SELECT * FROM order_items WHERE order_id=?", (o['id'],))
        odict = dict(o)
        odict['items'] = [dict(i) for i in items]
        res.append(odict)
    return res

@app.patch("/api/pos/orders/{order_id}/items/{item_id}/notes")
def update_item_notes(order_id: int, item_id: int, data: ItemNotesSchema, current_user: dict = Depends(get_current_user)):
    db.execute("UPDATE order_items SET notes=? WHERE id=? AND order_id=?", (data.notes, item_id, order_id))
    return {"status": "ok"}

class VoidSchema(BaseModel):
    reason: str = Field(min_length=3, max_length=200)
    admin_pin: Optional[str] = None

def _authorize_void(current_user: dict, admin_pin: Optional[str]) -> str:
    """Anular exige ser admin; cualquier otro rol necesita el PIN de un admin. Devuelve quién autorizó."""
    if current_user.get("role") == "admin":
        return current_user.get("sub") or "admin"
    if not admin_pin:
        raise HTTPException(status_code=403, detail="Se necesita el PIN de un administrador")
    ok, _, user = db.authenticate_pin(admin_pin)
    if not ok or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="PIN de administrador inválido")
    return user["username"]

def _open_order_or_400(order_id: int):
    order = db.one("SELECT * FROM orders WHERE id=?", (order_id,))
    if not order:
        raise HTTPException(status_code=404, detail="La cuenta no existe")
    if order["status"] != "open":
        raise HTTPException(status_code=400, detail="La cuenta ya no está abierta")
    return order

@app.post("/api/pos/orders/{order_id}/void")
async def void_order(order_id: int, data: VoidSchema, current_user: dict = Depends(get_current_user)):
    """Anula una cuenta abierta: no se borra, queda como 'cancelled' y no suma a ventas ni arqueo.
    El inventario no se toca porque solo se descuenta al cobrar."""
    order = _open_order_or_400(order_id)
    autorizo = _authorize_void(current_user, data.admin_pin)
    with db.connect() as con:
        con.execute("UPDATE orders SET status='cancelled', closed_at=? WHERE id=? AND status='open'",
                    (datetime.datetime.now().isoformat(timespec='seconds'), order_id))
        con.execute("UPDATE order_items SET status='cancelled' WHERE order_id=?", (order_id,))
        con.execute("UPDATE tables SET is_open=0, current_order_id=NULL WHERE current_order_id=?", (order_id,))
    nombre = order["table_name"] or f"Orden #{order_id}"
    db.log(current_user.get('sub'), "VOID_ORDER",
           f"Anulada {nombre} (#{order_id}) por ${order['total_cop'] or 0:,.0f}. Motivo: {data.reason}. Autorizó: {autorizo}")
    await manager.broadcast_kitchen("update_kitchen")
    return {"status": "ok"}

@app.post("/api/pos/orders/{order_id}/items/{item_id}/remove")
async def remove_order_item(order_id: int, item_id: int, data: VoidSchema, current_user: dict = Depends(get_current_user)):
    """Quita un producto cargado por error y recalcula el total de la cuenta."""
    _open_order_or_400(order_id)
    item = db.one("SELECT * FROM order_items WHERE id=? AND order_id=?", (item_id, order_id))
    if not item:
        raise HTTPException(status_code=404, detail="El producto no está en esta cuenta")
    autorizo = _authorize_void(current_user, data.admin_pin)
    with db.connect() as con:
        con.execute("DELETE FROM order_items WHERE id=? AND order_id=?", (item_id, order_id))
        sub = con.execute("SELECT COALESCE(SUM(total_cop),0) s FROM order_items WHERE order_id=?", (order_id,)).fetchone()["s"]
        con.execute("UPDATE orders SET total_cop=? WHERE id=?", (sub, order_id))
    db.log(current_user.get('sub'), "REMOVE_ORDER_ITEM",
           f"Quitado {item['qty']}x {item['product_name']} (${item['total_cop'] or 0:,.0f}) de la cuenta #{order_id}. "
           f"Motivo: {data.reason}. Autorizó: {autorizo}")
    await manager.broadcast_kitchen("update_kitchen")
    return {"status": "ok"}

ITEM_STATUSES = {"pending", "preparing", "ready", "delivered", "cancelled"}
KITCHEN_STATUSES = {"pending", "preparing", "ready", "on_the_way", "delivered"}

class ItemStatusSchema(BaseModel):
    status: str

@app.patch("/api/pos/orders/{order_id}/items/{item_id}/status")
async def update_item_status(order_id: int, item_id: int, data: ItemStatusSchema, current_user: dict = Depends(get_current_user)):
    if data.status not in ITEM_STATUSES:
        raise HTTPException(status_code=400, detail="Estado no válido")
    db.execute("UPDATE order_items SET status=? WHERE id=? AND order_id=?", (data.status, item_id, order_id))
    await manager.broadcast_kitchen("update_kitchen")
    return {"status": "ok"}

class KitchenStatusSchema(BaseModel):
    kitchen_status: str

@app.patch("/api/pos/orders/{order_id}/kitchen_status")
async def update_kitchen_status(order_id: int, data: KitchenStatusSchema, current_user: dict = Depends(get_current_user)):
    if data.kitchen_status not in KITCHEN_STATUSES:
        raise HTTPException(status_code=400, detail="Estado no válido")
    db.execute("UPDATE orders SET kitchen_status=? WHERE id=?", (data.kitchen_status, order_id))
    if data.kitchen_status == 'ready':
        # Despachar la orden marca todos sus platos como listos (así sale de la pantalla de cocina)
        db.execute("UPDATE order_items SET status='ready' WHERE order_id=? AND status='pending'", (order_id,))
    await manager.broadcast_kitchen("update_kitchen")
    if data.kitchen_status == 'ready':
        await manager.broadcast_kitchen("update_customer_screen") # Optional: Si usaran la misma connection manager
    return {"status": "ok"}

class NewInventoryItemSchema(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    stock_min: float = Field(ge=0)
    stock_max: float = Field(default=0, ge=0)
    unit: str = "und"
    inventory_type: str = "ingrediente"

class InventoryLimitsSchema(BaseModel):
    stock_min: float
    stock_max: float

@app.get("/api/inventory")
def get_inventory(current_user: dict = Depends(get_current_user)):
    try:
        items = db.all("SELECT * FROM inventory_items WHERE COALESCE(active,1)=1")
        return [dict(i) for i in items]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/inventory")
def create_inventory_item(data: NewInventoryItemSchema, current_user: dict = Depends(require_manager)):
    if data.stock_max and data.stock_max < data.stock_min:
        raise HTTPException(status_code=400, detail="El máximo no puede ser menor que el mínimo")
    db.execute("INSERT INTO inventory_items (name, stock_current, stock_min, stock_max, unit, inventory_type) VALUES (?, ?, ?, ?, ?, ?)",
               (data.name, 0.0, data.stock_min, data.stock_max, data.unit, data.inventory_type))
    db.log(current_user.get('sub'), "CREATE_INVENTORY_ITEM", f"Creado: {data.name}")
    return {"status": "ok"}

class AddStockSchema(BaseModel):
    qty: float = Field(gt=0)
    notes: Optional[str] = None

@app.put("/api/inventory/{item_id}/limits")
def update_inventory_limits(item_id: int, data: InventoryLimitsSchema, current_user: dict = Depends(require_manager)):
    _require_inventory_item(item_id)
    if data.stock_min < 0 or data.stock_max < data.stock_min:
        raise HTTPException(status_code=400, detail="El máximo debe ser mayor o igual al mínimo")
    db.execute("UPDATE inventory_items SET stock_min=?, stock_max=? WHERE id=?", (data.stock_min, data.stock_max, item_id))
    return {"status": "ok"}

@app.post("/api/inventory/{item_id}/add_stock")
def add_inventory_stock(item_id: int, data: AddStockSchema, current_user: dict = Depends(require_manager)):
    _require_inventory_item(item_id)
    db.execute("UPDATE inventory_items SET stock_current = stock_current + ? WHERE id=?", (data.qty, item_id))
    log_msg = f"Añadido {data.qty} al item {item_id}"
    if data.notes:
        log_msg += f". Notas: {data.notes}"
    db.log(current_user.get('sub'), "ADD_STOCK", log_msg)
    return {"status": "ok"}

class WasteSchema(BaseModel):
    amount: float = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)

def _require_inventory_item(item_id: int):
    row = db.one("SELECT * FROM inventory_items WHERE id=?", (item_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Ítem de inventario no encontrado")
    return row

@app.delete("/api/inventory/{item_id}")
def delete_inventory_item(item_id: int, current_user: dict = Depends(require_manager)):
    """Oculta el ítem (no lo borra) para no romper el historial de stock y mermas."""
    row = _require_inventory_item(item_id)
    usos = db.all("SELECT p.name FROM recipe_items r JOIN products p ON p.id = r.product_id WHERE r.inventory_item_id=?", (item_id,))
    if usos:
        nombres = ", ".join(u["name"] for u in usos[:5])
        raise HTTPException(status_code=409, detail=f"No se puede eliminar: lo usan las recetas de {nombres}. Quítalo de esas recetas primero.")
    db.execute("UPDATE inventory_items SET active=0 WHERE id=?", (item_id,))
    db.log(current_user.get('sub'), "DELETE_INVENTORY_ITEM", f"Eliminado: {row['name']} (id {item_id})")
    return {"status": "ok"}

@app.post("/api/inventory/{item_id}/waste")
def register_waste(item_id: int, data: WasteSchema, current_user: dict = Depends(require_manager)):
    _require_inventory_item(item_id)
    db.execute("UPDATE inventory_items SET stock_current = stock_current - ? WHERE id=?", (data.amount, item_id))
    db.execute("INSERT INTO waste_logs (inventory_item_id, qty, reason, user_id) VALUES (?,?,?,?)",
               (item_id, data.amount, data.reason, current_user.get('id', 0)))
    db.log(current_user.get('sub'), "WASTE", f"Merma de {data.amount} en item {item_id} por {data.reason}")
    return {"status": "ok"}
class RecipeItemSchema(BaseModel):
    inventory_item_id: int
    qty_needed: float = Field(gt=0)

@app.get("/api/products/{product_id}/recipe")
def get_product_recipe(product_id: int, current_user: dict = Depends(get_current_user)):
    rows = db.all('''
        SELECT r.product_id, r.inventory_item_id, r.qty_needed, i.name as inventory_name, i.inventory_type
        FROM recipe_items r
        JOIN inventory_items i ON i.id = r.inventory_item_id
        WHERE r.product_id = ?
    ''', (product_id,))
    return [dict(r) for r in rows]

@app.post("/api/products/{product_id}/recipe")
def add_recipe_item(product_id: int, data: RecipeItemSchema, current_user: dict = Depends(require_manager)):
    if not db.one("SELECT id FROM products WHERE id=?", (product_id,)):
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    _require_inventory_item(data.inventory_item_id)
    # Delete if exists to act as an upsert/update
    db.execute("DELETE FROM recipe_items WHERE product_id=? AND inventory_item_id=?", (product_id, data.inventory_item_id))
    db.execute("INSERT INTO recipe_items (product_id, inventory_item_id, qty_needed) VALUES (?,?,?)",
               (product_id, data.inventory_item_id, data.qty_needed))
    db.log(current_user.get('sub'), "UPDATE_RECIPE", f"Receta act. para prod {product_id}")
    return {"status": "ok"}

@app.delete("/api/products/{product_id}/recipe/{inventory_item_id}")
def delete_recipe_item(product_id: int, inventory_item_id: int, current_user: dict = Depends(require_manager)):
    db.execute("DELETE FROM recipe_items WHERE product_id=? AND inventory_item_id=?", (product_id, inventory_item_id))
    db.log(current_user.get('sub'), "DELETE_RECIPE_ITEM", f"Borrado item {inventory_item_id} de {product_id}")
    return {"status": "ok"}

@app.get("/api/inventory/predict")
def predict_purchases(current_user: dict = Depends(require_manager)):
    # Simple ML heuristic: Calculate daily consumption of each inventory item based on closed orders in the last 7 days.
    # We join orders -> order_items -> recipes -> inventory_items.
    # Note: SQLite datetime('now', '-7 days') works nicely.

    query = """
    SELECT
        i.id, i.name, i.stock_current, i.unit,
        i.stock_min, i.stock_max,
        SUM(r.qty_needed * oi.qty) as consumed_7_days
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    JOIN recipe_items r ON r.product_id = oi.product_id
    JOIN inventory_items i ON i.id = r.inventory_item_id
    WHERE o.status='closed' AND o.branch_id IS NULL
      AND o.closed_at >= datetime('now', '-7 days')
    GROUP BY i.id
    """

    consumption_data = db.all(query)
    predictions = []

    for row in consumption_data:
        daily_consumption = (row['consumed_7_days'] or 0) / 7.0

        # Runway (Days remaining)
        runway = 999
        if daily_consumption > 0:
            runway = row['stock_current'] / daily_consumption

        if runway < 3 or row['stock_current'] <= (row['stock_min'] or 0):
            # Reponer hasta el máximo definido; si no hay máximo, cubrir 7 días
            target = row['stock_max'] or (daily_consumption * 7)
            suggested_buy = target - row['stock_current']
            if suggested_buy < 0: suggested_buy = 0

            predictions.append({
                "item_id": row['id'],
                "name": row['name'],
                "stock_current": row['stock_current'],
                "unit": row['unit'],
                "daily_consumption": round(daily_consumption, 2),
                "runway_days": round(runway, 1),
                "suggested_buy": round(suggested_buy, 2)
            })

    # Sort by lowest runway
    predictions.sort(key=lambda x: x['runway_days'])

    return {"status": "ok", "predictions": predictions}

@app.get("/api/users")
def get_users(current_user: dict = Depends(require_admin)):
    return [dict(r) for r in db.all("SELECT id, username, role, pin, active, daily_wage, first_name, last_name, "
                                    "cedula, phone, birth_date FROM users ORDER BY active DESC, username")]

VALID_ROLES = {"admin", "cajero", "mesero", "cocina", "domiciliario"}

class UserCreateSchema(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=6, max_length=128)
    role: str
    pin: str = Field(pattern=r"^\d{4,8}$")
    daily_wage: float = Field(default=0, ge=0)
    first_name: Optional[str] = Field(default="", max_length=60)
    last_name: Optional[str] = Field(default="", max_length=60)
    cedula: Optional[str] = Field(default="", max_length=20)
    phone: Optional[str] = Field(default="", max_length=20)
    birth_date: Optional[str] = Field(default="", max_length=10)

class UserUpdateSchema(BaseModel):
    role: str
    pin: str = Field(pattern=r"^\d{4,8}$")
    daily_wage: float = Field(default=0, ge=0)
    first_name: Optional[str] = Field(default="", max_length=60)
    last_name: Optional[str] = Field(default="", max_length=60)
    cedula: Optional[str] = Field(default="", max_length=20)
    phone: Optional[str] = Field(default="", max_length=20)
    birth_date: Optional[str] = Field(default="", max_length=10)
    password: Optional[str] = Field(default=None, max_length=128)

def _valid_birth(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail="Fecha de cumpleaños inválida")

@app.post("/api/users")
def create_user(data: UserCreateSchema, current_user: dict = Depends(require_admin)):
    from app.security import hash_password
    if data.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Rol no válido")
    if db.one("SELECT id FROM users WHERE lower(username)=lower(?)", (data.username,)):
        raise HTTPException(status_code=400, detail="Ese usuario ya existe")
    # El PIN identifica al empleado en el login y la asistencia: debe ser único
    if db.one("SELECT id FROM users WHERE pin=? AND active=1", (data.pin,)):
        raise HTTPException(status_code=400, detail="Ese PIN ya está en uso")
    hash_pw = hash_password(data.password)
    db.execute("INSERT INTO users (username, password_hash, role, pin, active, daily_wage, first_name, last_name, cedula, phone, birth_date) "
               "VALUES (?,?,?,?,1,?,?,?,?,?,?)",
               (data.username, hash_pw, data.role, data.pin, data.daily_wage, data.first_name or None, data.last_name or None,
                data.cedula or None, data.phone or None, _valid_birth(data.birth_date)))
    return {"status": "ok"}

@app.put("/api/users/{user_id}")
def update_user(user_id: int, data: UserUpdateSchema, current_user: dict = Depends(require_admin)):
    from app.security import hash_password
    if not db.one("SELECT id FROM users WHERE id=?", (user_id,)):
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    if data.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Rol no válido")
    if user_id == current_user.get("id") and data.role != "admin":
        raise HTTPException(status_code=400, detail="No puedes quitarte a ti mismo el rol de administrador")
    if db.one("SELECT id FROM users WHERE pin=? AND active=1 AND id != ?", (data.pin, user_id)):
        raise HTTPException(status_code=400, detail="Ese PIN ya está en uso")
    db.execute("UPDATE users SET role=?, pin=?, daily_wage=?, first_name=?, last_name=?, cedula=?, phone=?, birth_date=? WHERE id=?",
               (data.role, data.pin, data.daily_wage, data.first_name or None, data.last_name or None, data.cedula or None,
                data.phone or None, _valid_birth(data.birth_date), user_id))
    if data.password:
        if len(data.password) < 6:
            raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 6 caracteres")
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(data.password), user_id))
    db.log(current_user.get("sub"), "user_updated", str(user_id))
    return {"status": "ok"}

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, current_user: dict = Depends(require_admin)):
    if user_id == current_user.get("id"):
        raise HTTPException(status_code=400, detail="No puedes desactivar tu propio usuario")
    db.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
    return {"status": "ok"}

@app.get("/api/reports/sales_trend")
def get_sales_trend(current_user: dict = Depends(require_manager)):
    # Group sales by day for the last 7 days
    rows = db.all("""
        SELECT substr(closed_at,1,10) as date, SUM(total_cop) as total
        FROM orders
        WHERE status='closed' AND branch_id IS NULL AND closed_at >= date('now', 'localtime', '-6 days')
        GROUP BY date
        ORDER BY date DESC
        LIMIT 7
    """)
    # Returns {date: ..., total: ...}
    return [dict(r) for r in rows]


# --- RESERVATIONS ---
class ReservationSchema(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(pattern=r"^[0-9+ ]{7,15}$")
    res_date: datetime.date
    res_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    guests: int = Field(gt=0, le=50)

RESERVATION_STATUSES = {"pending", "confirmed", "arrived", "cancelled", "completed"}

class ReservationStatusSchema(BaseModel):
    status: str

@app.post("/api/reservations")
def create_reservation(res: ReservationSchema):
    if res.res_date < datetime.date.today():
        raise HTTPException(status_code=400, detail="La fecha de la reserva ya pasó")
    db.execute("INSERT INTO reservations (name, phone, res_date, res_time, guests) VALUES (?, ?, ?, ?, ?)",
               (res.name, res.phone, res.res_date.isoformat(), res.res_time, res.guests))
    return {"status": "ok"}

@app.get("/api/reservations")
def get_reservations(current_user: dict = Depends(get_current_user)):
    rows = db.all("SELECT * FROM reservations ORDER BY res_date ASC, res_time ASC")
    return [dict(r) for r in rows]

@app.post("/api/reservations/{res_id}/status")
def update_reservation(res_id: int, data: ReservationStatusSchema, current_user: dict = Depends(get_current_user)):
    status = data.status
    if status not in RESERVATION_STATUSES:
        raise HTTPException(status_code=400, detail="Estado no válido")
    db.execute("UPDATE reservations SET status=? WHERE id=?", (status, res_id))
    return {"status": "ok"}

# --- ONLINE PAYMENTS ---

# --- DELIVERY ---
@app.get("/api/delivery/pending")
def get_pending_deliveries(current_user: dict = Depends(get_current_user)):
    rows = [dict(r) for r in db.all("""
        SELECT o.*
        FROM orders o
        WHERE (o.table_name LIKE 'Domicilio%' OR o.is_delivery = 1)
          AND o.status = 'open'
    """)]

    # Enrich with items
    for r in rows:
        r['items'] = [dict(i) for i in db.all("SELECT * FROM order_items WHERE order_id=?", (r['id'],))]
    return rows

class AssignDeliverySchema(BaseModel):
    driver_id: int

@app.post("/api/delivery/assign/{order_id}")
def assign_delivery(order_id: int, data: AssignDeliverySchema, current_user: dict = Depends(require_manager)):
    if not db.one("SELECT id FROM users WHERE id=? AND active=1", (data.driver_id,)):
        raise HTTPException(status_code=404, detail="Domiciliario no encontrado")
    if not db.one("SELECT id FROM orders WHERE id=? AND status='open'", (order_id,)):
        raise HTTPException(status_code=404, detail="Orden no encontrada o ya cerrada")
    logger.info(f"🚀 WHATSAPP AL CLIENTE: 'Tu pedido (Orden #{order_id}) va en camino con tu domiciliario. ¡Espéralo pronto!'")
    db.execute("UPDATE orders SET driver_id = ?, kitchen_status = 'on_the_way' WHERE id = ?", (data.driver_id, order_id))
    return {"status": "ok"}

DEFAULT_DELIVERY_ZONES = [
    {"name": "Cerca (hasta 2 km)", "fee": 3000},
    {"name": "Media (2 a 5 km)", "fee": 5000},
    {"name": "Lejos (más de 5 km)", "fee": 8000},
]

def get_delivery_zones() -> list:
    import json
    try:
        with open(os.path.join(os.path.dirname(__file__), "branding.json"), "r", encoding="utf-8-sig") as f:
            zones = json.load(f).get("delivery_zones")
        if isinstance(zones, list) and zones:
            return [{"name": str(z.get("name", "")), "fee": float(z.get("fee", 0))} for z in zones if z.get("name")]
    except (OSError, ValueError, AttributeError):
        pass
    return DEFAULT_DELIVERY_ZONES

@app.get("/api/delivery/zones")
def list_delivery_zones():
    """Público: lo usa la página de pedidos para mostrar el valor del envío por zona."""
    return get_delivery_zones()

class DeliveryFeeSchema(BaseModel):
    fee: float = Field(ge=0, le=200000)
    zone: Optional[str] = Field(default=None, max_length=80)

@app.put("/api/delivery/{order_id}/fee")
def set_delivery_fee(order_id: int, data: DeliveryFeeSchema, current_user: dict = Depends(require_manager)):
    if not db.one("SELECT id FROM orders WHERE id=? AND status='open'", (order_id,)):
        raise HTTPException(status_code=404, detail="Pedido no encontrado o ya cobrado")
    db.execute("UPDATE orders SET delivery_fee_cop=?, delivery_zone=COALESCE(?, delivery_zone) WHERE id=?",
               (data.fee, data.zone, order_id))
    db.log(current_user.get("sub"), "delivery_fee", f"orden {order_id}: {data.fee} ({data.zone or '-'})")
    return {"status": "ok"}

@app.post("/api/delivery/accept/{order_id}")
def accept_delivery(order_id: int, current_user: dict = Depends(get_current_user)):
    """El domiciliario toma un pedido libre (queda asignado a él y 'en camino')."""
    with db.connect() as con:
        cur = con.execute("UPDATE orders SET driver_id=?, kitchen_status='on_the_way' "
                          "WHERE id=? AND status='open' AND (driver_id IS NULL OR driver_id=?) "
                          "AND COALESCE(kitchen_status,'') != 'delivered'",
                          (current_user.get("id"), order_id, current_user.get("id")))
        con.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=409, detail="Otro domiciliario ya tomó este pedido o ya fue entregado")
    return {"status": "ok"}

class NewDeliverySchema(BaseModel):
    customer_name: str = Field(min_length=1, max_length=80)
    customer_phone: str = Field(pattern=r"^[0-9+ ]{7,15}$")
    delivery_address: str = Field(min_length=3, max_length=200)
    delivery_fee: float = Field(default=0, ge=0, le=200000)
    delivery_zone: Optional[str] = Field(default=None, max_length=80)

@app.post("/api/pos/delivery")
def create_delivery(data: NewDeliverySchema, current_user: dict = Depends(get_current_user)):
    order_id = db.insert(
        "INSERT INTO orders (status, table_name, total_cop, is_delivery, customer_name, customer_phone, delivery_address, "
        "delivery_fee_cop, delivery_zone, created_at) VALUES ('open', ?, 0, 1, ?, ?, ?, ?, ?, ?)",
        (f"Domicilio - {data.customer_name}", data.customer_name, data.customer_phone, data.delivery_address,
         data.delivery_fee, data.delivery_zone, datetime.datetime.now().isoformat(timespec="seconds"))
    )
    return {"status": "ok", "order_id": order_id}

@app.post("/api/delivery/complete/{order_id}")
def complete_delivery(order_id: int, current_user: dict = Depends(get_current_user)):
    # Se marca como entregado. El cobro debió hacerse o se hace después.
    # Admin y caja pueden marcar cualquier domicilio; el domiciliario solo los suyos.
    with db.connect() as con:
        if current_user.get("role") in ("admin", "cajero"):
            cur = con.execute("UPDATE orders SET kitchen_status = 'delivered' WHERE id = ?", (order_id,))
        else:
            cur = con.execute("UPDATE orders SET kitchen_status = 'delivered' WHERE id = ? AND driver_id = ?",
                              (order_id, current_user.get('id')))
        con.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Domicilio no encontrado o no está asignado a ti")
    logger.info(f"📱 WHATSAPP AL CLIENTE: 'Tu pedido (Orden #{order_id}) ha sido entregado. ¡Que lo disfrutes!'")
    return {"status": "ok"}

# --- DIAN FACTURACIÓN ELECTRÓNICA ---

class DianCustomerSchema(BaseModel):
    order_id: int
    document_type: str  # CC, NIT
    document_number: str
    name: str
    email: str

@app.post("/api/dian/invoice")
def generate_dian_invoice(data: DianCustomerSchema, current_user: dict = Depends(require_manager)):
    from app.integrations import load_config
    cfg = load_config()
    if not cfg["dian_enabled"]:
        raise HTTPException(status_code=403, detail="La facturación electrónica está desactivada. Actívala en Configuración.")
    # La DIAN solo acepta facturas emitidas por un proveedor tecnológico autorizado.
    # Nunca se genera un CUFE propio: una factura inventada no tiene validez legal.
    raise HTTPException(status_code=501, detail=(
        f"Facturación activada, pero falta conectar el proveedor tecnológico"
        f"{' (' + cfg['dian_provider'] + ')' if cfg['dian_provider'] else ''}. "
        "Pide a soporte que habilite la integración con tu proveedor."))


# ==========================================
# GIFT CARDS & BIRTHDAYS MODULE
# ==========================================
import string
import random

class GiftCardSchema(BaseModel):
    value_cop: float = Field(gt=0)
    type: str = "CUSTOMER" # "CUSTOMER" (Venta) o "EMPLOYEE" (Regalo)
    description: Optional[str] = ""

class RedeemSchema(BaseModel):
    amount: float = Field(gt=0)

@app.post("/api/vouchers/gift_card")
async def create_gift_card(data: GiftCardSchema, current_user: dict = Depends(require_manager)):
    code = "BONO-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    db = _db.connect()

    # Determinar el tipo interno e identificador según lo que manda el frontend
    internal_type = "GIFT_CARD" if data.type == "CUSTOMER" else "COURTESY_GIFT"
    identifier = "CUSTOMER" if data.type == "CUSTOMER" else "GIFT"

    try:
        db.execute("INSERT INTO vouchers (id, type, value_cop, balance_cop, is_redeemed, created_at, identifier) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (code, internal_type, data.value_cop, data.value_cop, 0, datetime.datetime.now().isoformat(), identifier))
        db.commit()
        return {"code": code, "value": data.value_cop}
    finally:
        db.close()

@app.get("/api/vouchers/{code}/validate")
async def validate_voucher(code: str, current_user: dict = Depends(get_current_user)):
    db = _db.connect()
    try:
        cur = db.execute("SELECT balance_cop, is_redeemed FROM vouchers WHERE id = ?", (code,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Bono no encontrado")
        if row['is_redeemed'] == 1 or row['balance_cop'] <= 0:
            raise HTTPException(status_code=400, detail="Bono sin saldo o ya redimido")
        return {"code": code, "balance": row['balance_cop']}
    finally:
        db.close()

@app.post("/api/vouchers/{code}/redeem")
async def redeem_voucher(code: str, data: RedeemSchema, current_user: dict = Depends(get_current_user)):
    db = _db.connect()
    try:
        cur = db.execute("SELECT balance_cop FROM vouchers WHERE id = ?", (code,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Bono no encontrado")

        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="El monto debe ser mayor que cero")
        if row['balance_cop'] < data.amount:
            raise HTTPException(status_code=400, detail="Saldo insuficiente en el bono")
        new_balance = row['balance_cop'] - data.amount
        is_redeemed = 1 if new_balance <= 0 else 0
        new_balance = max(0, new_balance)

        # Condición sobre el saldo para evitar dobles canjes simultáneos
        cur = db.execute("UPDATE vouchers SET balance_cop = ?, is_redeemed = ? WHERE id = ? AND balance_cop >= ?",
                         (new_balance, is_redeemed, code, data.amount))
        if cur.rowcount == 0:
            raise HTTPException(status_code=409, detail="El saldo cambió, intenta de nuevo")
        db.commit()
        return {"success": True, "new_balance": new_balance}
    finally:
        db.close()

@app.get("/api/vouchers")
async def get_vouchers(current_user: dict = Depends(require_manager)):
    db = _db.connect()
    try:
        cur = db.execute("SELECT id, type, value_cop, balance_cop, is_redeemed, created_at, identifier FROM vouchers ORDER BY created_at DESC")
        vouchers = [dict(row) for row in cur.fetchall()]
        return vouchers
    finally:
        db.close()

@app.get("/api/employees/birthdays")
async def get_birthdays(current_user: dict = Depends(require_manager)):
    db = _db.connect()
    try:
        current_month = f"-{datetime.datetime.now().month:02d}-"
        cur = db.execute("SELECT id, username, first_name, last_name, birth_date FROM users WHERE active=1 AND birth_date LIKE ?", ('%' + current_month + '%',))
        employees = []
        for row in cur.fetchall():
            employees.append(dict(row))
        return employees
    finally:
        db.close()

class IssueBonusSchema(BaseModel):
    employee_id: int
    value_cop: float = Field(gt=0)

@app.post("/api/employees/issue_birthday_bonus")
async def issue_birthday_bonus(data: IssueBonusSchema, current_user: dict = Depends(require_manager)):
    emp = _db.one("SELECT id FROM users WHERE id=? AND active=1", (data.employee_id,))
    if not emp:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    year = str(datetime.datetime.now().year)
    if _db.one("SELECT id FROM vouchers WHERE type='BIRTHDAY' AND identifier=? AND substr(created_at,1,4)=?",
               (f"EMP-{data.employee_id}", year)):
        raise HTTPException(status_code=400, detail="Este empleado ya recibió su bono de cumpleaños este año")
    code = "HBAY-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    db = _db.connect()
    try:
        db.execute("INSERT INTO vouchers (id, type, value_cop, balance_cop, is_redeemed, created_at, identifier) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (code, "BIRTHDAY", data.value_cop, data.value_cop, 0, datetime.datetime.now().isoformat(), f"EMP-{data.employee_id}"))
        db.commit()
        return {"code": code, "value": data.value_cop}
    finally:
        db.close()


# ==========================================
# ARCHIVOS ESTÁTICOS — deben montarse al final: el mount "/" captura
# cualquier ruta registrada después de él.
# ==========================================
@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    # HTML/JS/CSS: el navegador debe confirmar con el servidor si hay versión nueva
    # (con ETag es una respuesta 304 muy liviana). Así cada actualización llega a todos los equipos.
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css", ".json")):
        response.headers["Cache-Control"] = "no-cache"
    return response

_backend_dir = os.path.dirname(__file__)
frontend_path = os.path.join(os.path.dirname(_backend_dir), "frontend")
uploads_path = os.path.join(_backend_dir, "uploads")
os.makedirs(uploads_path, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_path), name="uploads")

if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
