import os
from fastapi import FastAPI, HTTPException, Security, Depends, WebSocket, WebSocketDisconnect, Header, UploadFile, File
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from app.db import db
import uvicorn
from dotenv import load_dotenv
import threading
import schedule
import time
import zipfile
import datetime
import logging
import requests

logging.basicConfig(filename='taqueria_server.log', level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("API")

load_dotenv()

# Inicialización de la API
app = FastAPI(title="Taquería Pro API")

# Ciberseguridad: Cargar clave desde .env y limitar CORS
API_KEY = os.getenv("API_KEY", "123456")
api_key_header = APIKeyHeader(name="x-api-key")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # En producción cambiar por la IP de los iPads/Red local
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key_header = APIKeyHeader(name="x-api-key")

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

    async def broadcast_kitchen(self, message: str):
        for connection in self.kitchen_connections:
            await connection.send_text(message)

    async def broadcast_cfd(self, message: str):
        for connection in self.cfd_connections:
            await connection.send_text(message)

manager = ConnectionManager()

def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Clave de API inválida")
    return api_key

# Modelo para recibir datos de productos desde el celular
class OrderItem(BaseModel):
    order_id: int
    product_id: int
    qty: int

class ProductCreate(BaseModel):
    name: str
    price_cop: float
    category_id: Optional[int] = None
    image_url: Optional[str] = None

class ProductResponse(BaseModel):
    id: int
    name: str
    price_cop: float
    category_id: Optional[int] = None
    image_url: Optional[str] = None

class CustomerOrderItem(BaseModel):
    product_id: int
    qty: int
    notes: Optional[str] = ""

class CustomerOrderSchema(BaseModel):
    table_id: int
    items: List[CustomerOrderItem]
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

@app.post("/api/login/pin")
def login_pin(req: PinLoginRequest):
    success, msg, user = db.authenticate_pin(req.pin)
    if not success:
        raise HTTPException(status_code=401, detail=msg)
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


@app.get("/menu", response_model=List[ProductResponse])
def get_menu(current_user: dict = Depends(get_current_user)):
    """Retorna los productos activos para que el mesero los vea en su dispositivo."""
    try:
        # Consulta directamente la base de datos configurada en app/db.py
        productos = db.all("SELECT id, name, price_cop, category_id, image_url FROM products WHERE active=1")
        return [dict(p) for p in productos]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/products")
def create_product(data: ProductCreate, current_user: dict = Depends(get_current_user)):
    try:
        db.execute(
            "INSERT INTO products (name, price_cop, category_id, image_url, active) VALUES (?, ?, ?, ?, 1)",
            (data.name, data.price_cop, data.category_id, data.image_url)
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/products/{product_id}")
def update_product(product_id: int, data: ProductCreate, current_user: dict = Depends(get_current_user)):
    try:
        db.execute(
            "UPDATE products SET name=?, price_cop=?, category_id=?, image_url=? WHERE id=?",
            (data.name, data.price_cop, data.category_id, data.image_url, product_id)
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/products/{product_id}")
def delete_product(product_id: int, current_user: dict = Depends(get_current_user)):
    try:
        db.execute("UPDATE products SET active=0 WHERE id=?", (product_id,))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/customer/menu", response_model=List[ProductResponse])
def get_customer_menu():
    """Public endpoint for customers scanning the QR code"""
    try:
        productos = db.all("SELECT id, name, price_cop, category_id, image_url FROM products WHERE active=1")
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
            order_id = db.insert(
                "INSERT INTO orders (status, table_name, total_cop, is_delivery, customer_name, customer_phone, delivery_address) VALUES ('open', ?, 0, 1, ?, ?, ?)",
                (f"Domicilio - {data.customer_name}", data.customer_name, data.customer_phone, data.delivery_address)
            )
        else:
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
            product = db.one("SELECT name, price_cop FROM products WHERE id=?", (item.product_id,))
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
    product = db.one("SELECT name, price_cop FROM products WHERE id=?", (item.product_id,))
    
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    try:
        total = product['price_cop'] * item.qty
        # Inserta el item con estado 'pending' para que aparezca en la pantalla de cocina
        db.execute(
            """INSERT INTO order_items (order_id, product_id, product_name, qty, unit_price_cop, total_cop, status) 
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""", 
            (item.order_id, item.product_id, product['name'], item.qty, product['price_cop'], total)
        )
        
        # Recalcula los totales de la orden para que el cajero vea el valor actualizado
        subtotal_row = db.one("SELECT SUM(total_cop) as sub FROM order_items WHERE order_id=?", (item.order_id,))
        subtotal = subtotal_row['sub'] if subtotal_row['sub'] else 0
        
        db.execute("UPDATE orders SET subtotal_cop=?, total_cop=? WHERE id=?", (subtotal, subtotal, item.order_id))
        
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
        SELECT oi.*, p.name product_name, t.table_number 
        FROM order_items oi 
        JOIN orders o ON o.id = oi.order_id 
        JOIN tables t ON t.current_order_id = o.id 
        WHERE oi.status = 'pending'
    ''')
    return [dict(i) for i in items]

@app.get("/branding")
def get_branding():
    import json
    import os
    try:
        path = os.path.join(os.path.dirname(__file__), "branding.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"business_name": "Restaurante", "theme_color": "#10b981", "logo_url": ""}

class BrandingSchema(BaseModel):
    business_name: str
    theme_color: str
    branch_id: str
    logo_url: Optional[str] = ""
    dian_api_key: Optional[str] = ""
    whatsapp_number: Optional[str] = ""
    ad_images: Optional[List[str]] = []

@app.post("/branding")
def update_branding(data: BrandingSchema, current_user: dict = Depends(get_current_user)):
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), "branding.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except:
        existing = {}
    
    # Preserve existing logo_url if not provided
    if not data.logo_url and "logo_url" in existing:
        data.logo_url = existing["logo_url"]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data.model_dump(), f)
    return {"status": "ok"}

@app.post("/api/upload_logo")
async def upload_logo(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    import os
    import shutil
    uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    
    ext = file.filename.split(".")[-1]
    filename = f"logo.{ext}"
    filepath = os.path.join(uploads_dir, filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"status": "ok", "url": f"/uploads/{filename}"}

@app.post("/api/upload_image")
async def upload_image(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    import os
    import shutil
    import uuid
    uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(uploads_dir, filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"status": "ok", "url": f"/uploads/{filename}"}

@app.get("/dashboard_data")
def get_dashboard_data(current_user: dict = Depends(get_current_user)):
    summary = db.sales_summary_today()
    # IA Predictiva (Cerebro)
    insights = []
    if summary['items']:
        top_item = summary['items'][0]['product_name']
        insights.append(f"Tu producto estrella hoy es '{top_item}'. ¡Asegúrate de preparar suficiente inventario para mañana!")
    if summary['total'] > 500000:
        insights.append("¡Excelente trabajo! Has superado la barrera de medio millón en ventas hoy. El negocio va en crecimiento.")
    elif summary['total'] == 0:
        insights.append("Aún no hay ventas registradas. ¡Aprovecha para organizar el local y estar listo!")
    else:
        insights.append("Las ventas fluyen con normalidad. Sugiero lanzar una promoción de bebida para aumentar el ticket promedio.")
    summary['ai_insights'] = insights
    return summary

class CFDUpdate(BaseModel):
    order_id: Optional[int] = None
    table: Optional[str] = None
    items: List[dict]
    total: float

@app.post("/api/cfd_update")
async def cfd_update(data: CFDUpdate, api_key: str = Depends(get_api_key)):
    await manager.broadcast_cfd(data.model_dump_json())
    return {"status": "ok"}

@app.websocket("/ws/kitchen")
async def websocket_endpoint(websocket: WebSocket, api_key: str = None):
    if api_key != API_KEY:
        await websocket.close(code=1008, reason="Invalid API Key")
        return
    await manager.connect_kitchen(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_kitchen(websocket)

@app.websocket("/ws/cfd")
async def websocket_cfd(websocket: WebSocket, api_key: str = None):
    if api_key != API_KEY:
        await websocket.close(code=1008, reason="Invalid API Key")
        return
    await manager.connect_cfd(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_cfd(websocket)



@app.post("/api/sync_receive")
def sync_receive(data: dict):
    """Endpoint MODO MAESTRO: Recibe ventas de las sucursales y las guarda en su propia DB"""
    try:
        data.get("branch_id")
        for order in data.get("orders", []):
            try:
                db.execute("INSERT INTO orders (id, status, table_number, total_cop, payment_method, created_at, closed_at) VALUES (?,?,?,?,?,?,?)",
                           (order['id'], order['status'], order['table_number'], order['total_cop'], order['payment_method'], order['created_at'], order['closed_at']))
                for item in order['items']:
                    db.execute("INSERT INTO order_items (order_id, product_id, product_name, qty, price_cop, total_cop) VALUES (?,?,?,?,?,?)",
                               (order['id'], item['product_id'], item['product_name'], item['qty'], item['price_cop'], item['total_cop']))
            except:
                pass # Ignorar si ya existe
        return {"status": "ok", "message": "Synced"}
    except Exception as e:
        logger.error(f"Error en Master Sync: {e}")
        return {"status": "error"}

def backup_db():
    backup_dir = os.path.join(os.path.dirname(__file__), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    db_path = os.path.join(os.path.dirname(__file__), "..", "taqueria.db")
    if os.path.exists(db_path):
        zip_name = os.path.join(backup_dir, f"backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
        with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(db_path, "taqueria.db")

schedule.every().day.at("03:00").do(backup_db)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)

def cloud_sync_worker():
    """Hilo MODO SUCURSAL: Envía ventas a la Nube cada 5 mins si hay internet."""
    import json, os
    while True:
        try:
            path = os.path.join(os.path.dirname(__file__), "branding.json")
            with open(path, "r", encoding="utf-8") as f:
                branding = json.load(f)
            
            master_url = branding.get("master_server_url")
            branch_id = branding.get("branch_id", "SUC-01")
            
            if master_url and master_url.startswith("http"):
                # Busca órdenes cerradas que no se hayan sincronizado (Simulado aquí recogiendo las de hoy)
                from datetime import date
                today = date.today().isoformat()
                unsynced = db.all("SELECT * FROM orders WHERE status='closed' AND substr(closed_at,1,10)=?", (today,))
                
                if unsynced:
                    payload_orders = []
                    for o in unsynced:
                        items = db.all("SELECT * FROM order_items WHERE order_id=?", (o['id'],))
                        odict = dict(o)
                        odict['items'] = [dict(i) for i in items]
                        payload_orders.append(odict)
                    
                    res = requests.post(f"{master_url}/api/sync_receive", json={"branch_id": branch_id, "orders": payload_orders}, timeout=5)
                    if res.status_code == 200:
                        logger.info(f"Sincronizados {len(unsynced)} pedidos a la NUBE MAESTRA.")
        except Exception as e:
            pass # Falla silenciosa si no hay internet
        time.sleep(300)

threading.Thread(target=run_scheduler, daemon=True).start()
threading.Thread(target=cloud_sync_worker, daemon=True).start()


class ItemNotesSchema(BaseModel):
    notes: str

class PaymentSchema(BaseModel):
    order_id: int
    method: str
    phone: Optional[str] = None
    tip_amount: float = 0.0
    points_used: int = 0

@app.post("/api/pos/pay")
def process_payment(data: PaymentSchema, current_user: dict = Depends(get_current_user)):
    if data.phone:
        order = db.one("SELECT total_cop FROM orders WHERE id=?", (data.order_id,))
        if order:
            points_earned = int(order['total_cop'] / 100)
            db.execute("INSERT INTO customers (phone, points) VALUES (?, ?) ON CONFLICT(phone) DO UPDATE SET points = points + ?", 
                       (data.phone, points_earned, points_earned))
            
            if data.points_used > 0:
                db.execute("UPDATE customers SET points = points - ? WHERE phone=?", (data.points_used, data.phone))
                db.execute("UPDATE orders SET total_cop = total_cop - ? WHERE id=?", (data.points_used, data.order_id))
    
    db.execute("UPDATE orders SET tip_amount_cop = ? WHERE id = ?", (data.tip_amount, data.order_id))
    success, msg = db.close_order_with_inventory(data.order_id, data.method)
    if success:
        from app.utils import write_ticket
        order = db.one("SELECT * FROM orders WHERE id=?", (data.order_id,))
        items = db.all("SELECT * FROM order_items WHERE order_id=?", (data.order_id,))
        if order:
            write_ticket(data.order_id, str(order.get('table_name', 'Mesa')), items, order['total_cop'], data.method)
        return {"status": "ok", "message": msg}
    else:
        raise HTTPException(status_code=400, detail=msg)

class AttendanceSchema(BaseModel):
    pin: str

@app.post("/api/attendance/log")
def log_attendance(data: AttendanceSchema):
    user = db.one("SELECT * FROM users WHERE pin=?", (data.pin,))
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Determinar si es entrada o salida (busca el último registro)
    last_log = db.one("SELECT log_type FROM attendance_logs WHERE user_id=? ORDER BY id DESC LIMIT 1", (user['id'],))
    new_type = 'out' if last_log and last_log['log_type'] == 'in' else 'in'
    
    timestamp = datetime.now().isoformat()
    db.execute("INSERT INTO attendance_logs (user_id, log_type, timestamp) VALUES (?,?,?)", (user['id'], new_type, timestamp))
    return {"status": "ok", "type": new_type, "user": user['first_name'] or user['username']}

@app.get("/api/pos/orders")
def get_open_orders(current_user: dict = Depends(get_current_user)):
    orders = db.all("SELECT o.*, t.id as table_number, t.name as table_name FROM orders o JOIN tables t ON t.current_order_id = o.id WHERE o.status='open'")
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

class ItemStatusSchema(BaseModel):
    status: str

@app.patch("/api/pos/orders/{order_id}/items/{item_id}/status")
async def update_item_status(order_id: int, item_id: int, data: ItemStatusSchema, current_user: dict = Depends(get_current_user)):
    db.execute("UPDATE order_items SET status=? WHERE id=? AND order_id=?", (data.status, item_id, order_id))
    await manager.broadcast_kitchen("update_kitchen")
    return {"status": "ok"}

class KitchenStatusSchema(BaseModel):
    kitchen_status: str

@app.patch("/api/pos/orders/{order_id}/kitchen_status")
async def update_kitchen_status(order_id: int, data: KitchenStatusSchema, current_user: dict = Depends(get_current_user)):
    db.execute("UPDATE orders SET kitchen_status=? WHERE id=?", (data.kitchen_status, order_id))
    await manager.broadcast_kitchen("update_kitchen")
    if data.kitchen_status == 'ready':
        await manager.broadcast_kitchen("update_customer_screen") # Optional: Si usaran la misma connection manager
    return {"status": "ok"}

class NewInventoryItemSchema(BaseModel):
    name: str
    stock_min: float
    inventory_type: str = "ingrediente"

@app.get("/api/inventory")
def get_inventory(current_user: dict = Depends(get_current_user)):
    try:
        items = db.all("SELECT * FROM inventory_items")
        return [dict(i) for i in items]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/inventory")
def create_inventory_item(data: NewInventoryItemSchema, current_user: dict = Depends(get_current_user)):
    db.execute("INSERT INTO inventory_items (name, stock_current, stock_min, inventory_type) VALUES (?, ?, ?, ?)",
               (data.name, 0.0, data.stock_min, data.inventory_type))
    db.log(current_user.get('username', 'admin'), "CREATE_INVENTORY_ITEM", f"Creado: {data.name}")
    return {"status": "ok"}

class AddStockSchema(BaseModel):
    amount: float

@app.post("/api/inventory/{item_id}/add_stock")
def add_inventory_stock(item_id: int, data: AddStockSchema, current_user: dict = Depends(get_current_user)):
    db.execute("UPDATE inventory_items SET stock_current = stock_current + ? WHERE id=?", (data.amount, item_id))
    db.log("admin", "ADD_STOCK", f"Añadido {data.amount} al item {item_id}")
    return {"status": "ok"}

class WasteSchema(BaseModel):
    amount: float
    reason: str

@app.post("/api/inventory/{item_id}/waste")
def register_waste(item_id: int, data: WasteSchema, current_user: dict = Depends(get_current_user)):
    db.execute("UPDATE inventory_items SET stock_current = stock_current - ? WHERE id=?", (data.amount, item_id))
    db.execute("INSERT INTO waste_logs (inventory_item_id, qty, reason, user_id) VALUES (?,?,?,?)",
               (item_id, data.amount, data.reason, current_user.get('id', 0)))
    db.log("admin", "WASTE", f"Merma de {data.amount} en item {item_id} por {data.reason}")
    return {"status": "ok"}
class RecipeItemSchema(BaseModel):
    inventory_item_id: int
    qty_needed: float

@app.get("/api/products/{product_id}/recipe")
def get_product_recipe(product_id: int, current_user: dict = Depends(get_current_user)):
    items = db.execute('''
        SELECT r.product_id, r.inventory_item_id, r.qty_needed, i.name as inventory_name, i.inventory_type 
        FROM recipe_items r 
        JOIN inventory_items i ON i.id = r.inventory_item_id 
        WHERE r.product_id = ?
    ''', (product_id,))
    return items

@app.post("/api/products/{product_id}/recipe")
def add_recipe_item(product_id: int, data: RecipeItemSchema, current_user: dict = Depends(get_current_user)):
    # Delete if exists to act as an upsert/update
    db.execute("DELETE FROM recipe_items WHERE product_id=? AND inventory_item_id=?", (product_id, data.inventory_item_id))
    db.execute("INSERT INTO recipe_items (product_id, inventory_item_id, qty_needed) VALUES (?,?,?)", 
               (product_id, data.inventory_item_id, data.qty_needed))
    db.log(current_user.get('username', 'admin'), "UPDATE_RECIPE", f"Receta act. para prod {product_id}")
    return {"status": "ok"}

@app.delete("/api/products/{product_id}/recipe/{inventory_item_id}")
def delete_recipe_item(product_id: int, inventory_item_id: int, current_user: dict = Depends(get_current_user)):
    db.execute("DELETE FROM recipe_items WHERE product_id=? AND inventory_item_id=?", (product_id, inventory_item_id))
    db.log(current_user.get('username', 'admin'), "DELETE_RECIPE_ITEM", f"Borrado item {inventory_item_id} de {product_id}")
    return {"status": "ok"}

@app.get("/api/inventory/predict")
def predict_purchases(current_user: dict = Depends(get_current_user)):
    # Simple ML heuristic: Calculate daily consumption of each inventory item based on closed orders in the last 7 days.
    # We join orders -> order_items -> recipes -> inventory_items.
    # Note: SQLite datetime('now', '-7 days') works nicely.
    
    query = """
    SELECT 
        i.id, i.name, i.stock_current, i.unit,
        SUM(r.qty * oi.qty) as consumed_7_days
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    JOIN recipe_items r ON r.product_id = oi.product_id
    JOIN inventory_items i ON i.id = r.inventory_item_id
    WHERE o.status = 'closed'
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
            
        if runway < 3:
            # Suggest a 7-day restock
            suggested_buy = (daily_consumption * 7) - row['stock_current']
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
def get_users(current_user: dict = Depends(get_current_user)):
    return [dict(r) for r in db.all("SELECT id, username, role, pin, active, daily_wage FROM users")]

class UserCreateSchema(BaseModel):
    username: str
    password: str
    role: str
    pin: str
    daily_wage: float

@app.post("/api/users")
def create_user(data: UserCreateSchema, current_user: dict = Depends(get_current_user)):
    from app.security import hash_password
    hash_pw = hash_password(data.password)
    db.execute("INSERT INTO users (username, password_hash, role, pin, active, daily_wage) VALUES (?,?,?,?,1,?)",
               (data.username, hash_pw, data.role, data.pin, data.daily_wage))
    return {"status": "ok"}

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, current_user: dict = Depends(get_current_user)):
    db.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
    return {"status": "ok"}

@app.get("/api/reports/sales_trend")
def get_sales_trend(current_user: dict = Depends(get_current_user)):
    # Group sales by day for the last 7 days
    rows = db.all("""
        SELECT substr(closed_at,1,10) as date, SUM(total_cop) as total 
        FROM orders 
        WHERE status='closed' 
        GROUP BY date 
        ORDER BY date DESC 
        LIMIT 7
    """)
    # Returns {date: ..., total: ...}
    return [dict(r) for r in rows]


# --- RESERVATIONS ---
class ReservationSchema(BaseModel):
    name: str
    phone: str
    res_date: str
    res_time: str
    guests: int

@app.post("/api/reservations")
def create_reservation(res: ReservationSchema):
    db.execute("INSERT INTO reservations (name, phone, res_date, res_time, guests) VALUES (?, ?, ?, ?, ?)",
               (res.name, res.phone, res.res_date, res.res_time, res.guests))
    return {"status": "ok"}

@app.get("/api/reservations")
def get_reservations(current_user: dict = Depends(get_current_user)):
    rows = db.all("SELECT * FROM reservations ORDER BY res_date ASC, res_time ASC")
    return [dict(r) for r in rows]

@app.post("/api/reservations/{res_id}/status")
def update_reservation(res_id: int, data: dict, current_user: dict = Depends(get_current_user)):
    status = data.get("status", "pending")
    db.execute("UPDATE reservations SET status=? WHERE id=?", (status, res_id))
    return {"status": "ok"}

# --- ONLINE PAYMENTS ---
@app.post("/api/customer/pay/{order_id}")
def customer_online_pay(order_id: int):
    # Simulates MercadoPago / Wompi successful callback
    db.close_order_with_inventory(order_id, "online")
    return {"status": "ok"}


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
def assign_delivery(order_id: int, data: AssignDeliverySchema, current_user: dict = Depends(get_current_user)):
    logger.info(f"🚀 WHATSAPP AL CLIENTE: 'Tu pedido (Orden #{order_id}) va en camino con tu domiciliario. ¡Espéralo pronto!'")
    db.execute("UPDATE orders SET driver_id = ?, kitchen_status = 'on_the_way' WHERE id = ?", (data.driver_id, order_id))
    return {"status": "ok"}

class NewDeliverySchema(BaseModel):
    customer_name: str
    customer_phone: str
    delivery_address: str

@app.post("/api/pos/delivery")
def create_delivery(data: NewDeliverySchema, current_user: dict = Depends(get_current_user)):
    order_id = db.insert(
        "INSERT INTO orders (status, table_name, total_cop, is_delivery, customer_name, customer_phone, delivery_address) VALUES ('open', ?, 0, 1, ?, ?, ?)", 
        (f"Domicilio - {data.customer_name}", data.customer_name, data.customer_phone, data.delivery_address)
    )
    return {"status": "ok", "order_id": order_id}

@app.post("/api/delivery/complete/{order_id}")
def complete_delivery(order_id: int, current_user: dict = Depends(get_current_user)):
    driver_id = current_user.get('id')
    # Se marca como entregado. El cobro debió hacerse o se hace después.
    logger.info(f"📱 WHATSAPP AL CLIENTE: 'Tu pedido (Orden #{order_id}) ha sido entregado. ¡Que lo disfrutes!'")
    db.execute("UPDATE orders SET kitchen_status = 'delivered' WHERE id = ? AND driver_id = ?", (order_id, driver_id))
    return {"status": "ok"}

# --- DIAN FACTURACIÓN ELECTRÓNICA ---
from app.dian import simulate_dian_invoice

class DianCustomerSchema(BaseModel):
    order_id: int
    document_type: str  # CC, NIT
    document_number: str
    name: str
    email: str

@app.post("/api/dian/invoice")
def generate_dian_invoice(data: DianCustomerSchema, current_user: dict = Depends(get_current_user)):
    order = db.one("SELECT * FROM orders WHERE id=?", (data.order_id,))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    customer_data = {
        "nit": data.document_number,
        "name": data.name,
        "email": data.email
    }
    
    # 1. Enviar a DIAN (Simulado)
    invoice_result = simulate_dian_invoice(dict(order), customer_data)
    
    # 2. Guardar metadata fiscal en la orden para que salga en el ticket
    new_notes = f"{order['notes'] or ''}\n[DIAN CUFE: {invoice_result['cufe']}]\n[FEV: {invoice_result['invoice_number']}]"
    db.execute("UPDATE orders SET notes = ? WHERE id = ?", (new_notes, data.order_id))
    
    return invoice_result

import os
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
uploads_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", "uploads")
if os.path.exists(uploads_path):
    app.mount("/uploads", StaticFiles(directory=uploads_path), name="uploads")

if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")


# --- MULTI-BRANCH SYNC (FRANCHISE) ---
@app.post("/api/sync/master")
def sync_to_master(current_user: dict = Depends(get_current_user)):
    try:
        # Collect basic metrics
        orders_count = db.one("SELECT COUNT(*) as c FROM orders")['c']
        total_sales = db.one("SELECT SUM(total_cop) as t FROM orders WHERE status='closed'")['t'] or 0
        
        payload = {
            "branch_id": "TAQ-001",
            "timestamp": datetime.datetime.now().isoformat(),
            "metrics": {
                "total_orders": orders_count,
                "total_sales_cop": total_sales
            }
        }
        
        # Simulate network delay and sending to master
        time.sleep(1.5)
        logger.info(f"☁️ SYNC MASTER EXITOSO: {payload}")
        return {"status": "ok", "message": "Datos sincronizados con Servidor Maestro", "data": payload}
    except Exception as e:
        logger.error(f"Error syncing master: {e}")
        raise HTTPException(status_code=500, detail="Error de sincronización")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# ==========================================
# GIFT CARDS & BIRTHDAYS MODULE
# ==========================================
import string
import random
from datetime import datetime

class GiftCardSchema(BaseModel):
    value_cop: float
    type: str = "CUSTOMER" # "CUSTOMER" (Venta) o "EMPLOYEE" (Regalo)
    description: Optional[str] = ""

class RedeemSchema(BaseModel):
    amount: float

@app.post("/api/vouchers/gift_card")
async def create_gift_card(data: GiftCardSchema, current_user: dict = Depends(get_current_user)):
    code = "BONO-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    db = get_db()
    
    # Determinar el tipo interno e identificador según lo que manda el frontend
    internal_type = "GIFT_CARD" if data.type == "CUSTOMER" else "COURTESY_GIFT"
    identifier = "CUSTOMER" if data.type == "CUSTOMER" else "GIFT"
    
    try:
        db.execute("INSERT INTO vouchers (id, type, value_cop, balance_cop, is_redeemed, created_at, identifier) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (code, internal_type, data.value_cop, data.value_cop, 0, datetime.now().isoformat(), identifier))
        db.commit()
        return {"code": code, "value": data.value_cop}
    finally:
        db.close()

@app.get("/api/vouchers/{code}/validate")
async def validate_voucher(code: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
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
    db = get_db()
    try:
        cur = db.execute("SELECT balance_cop FROM vouchers WHERE id = ?", (code,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Bono no encontrado")
        
        new_balance = row['balance_cop'] - data.amount
        is_redeemed = 1 if new_balance <= 0 else 0
        new_balance = max(0, new_balance)

        db.execute("UPDATE vouchers SET balance_cop = ?, is_redeemed = ? WHERE id = ?", (new_balance, is_redeemed, code))
        db.commit()
        return {"success": True, "new_balance": new_balance}
    finally:
        db.close()

@app.get("/api/vouchers")
async def get_vouchers(current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        cur = db.execute("SELECT id, type, value_cop, balance_cop, is_redeemed, created_at, identifier FROM vouchers ORDER BY created_at DESC")
        vouchers = [dict(row) for row in cur.fetchall()]
        return vouchers
    finally:
        db.close()

@app.get("/api/employees/birthdays")
async def get_birthdays(current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        current_month = f"-{datetime.now().month:02d}-"
        cur = db.execute("SELECT id, username, first_name, last_name, birth_date FROM users WHERE active=1 AND birth_date LIKE ?", ('%' + current_month + '%',))
        employees = []
        for row in cur.fetchall():
            employees.append(dict(row))
        return employees
    finally:
        db.close()

class IssueBonusSchema(BaseModel):
    employee_id: int
    value_cop: float

@app.post("/api/employees/issue_birthday_bonus")
async def issue_birthday_bonus(data: IssueBonusSchema, current_user: dict = Depends(get_current_user)):
    code = "HBAY-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    db = get_db()
    try:
        db.execute("INSERT INTO vouchers (id, type, value_cop, balance_cop, is_redeemed, created_at, identifier) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (code, "BIRTHDAY", data.value_cop, data.value_cop, 0, datetime.now().isoformat(), f"EMP-{data.employee_id}"))
        db.commit()
        return {"code": code, "value": data.value_cop}
    finally:
        db.close()
