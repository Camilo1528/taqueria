
load_dotenv()

# InicializaciÃ³n de la API
app = FastAPI(title="TaquerÃ­a Pro API")

# Ciberseguridad: Cargar clave desde .env y limitar CORS
API_KEY = os.getenv("API_KEY", "123456")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # En producciÃ³n cambiar por la IP de los iPads/Red local
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],

manager = ConnectionManager()

from fastapi import Header
from app.security import verify_token, create_access_token
from app.db import db
from pydantic import BaseModel

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

def get_api_key(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No autorizado")
    token = authorization.split(" ")[1]
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token invÃ¡lido o expirado")
    return payload

# Modelo para recibir datos de productos desde el celular
class OrderItem(BaseModel):
    order_id: int
    product_id: int
    qty: int
    notes: Optional[str] = ""

class ProductResponse(BaseModel):
    id: int
        total = product['price_cop'] * item.qty
        # Inserta el item con estado 'pending' para que aparezca en la pantalla de cocina
        db.execute(
            """INSERT INTO order_items (order_id, product_id, product_name, qty, price_cop, total_cop, notes) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""", 
            (item.order_id, item.product_id, product['name'], item.qty, product['price_cop'], total, item.notes)
        )
        
        # Recalcula los totales de la orden para que el cajero vea el valor actualizado
        subtotal_row = db.one("SELECT SUM(total_cop) as sub FROM order_items WHERE order_id=?", (item.order_id,))
        total_val = subtotal_row['sub'] if subtotal_row['sub'] else 0
        
        db.execute("UPDATE orders SET total_cop=? WHERE id=?", (total_val, item.order_id))
        
        await manager.broadcast_kitchen("update_kitchen")
        logger.info(f"Nuevo pedido procesado: {product['name']} x{item.qty}")
        return {"status": "success", "message": f"AÃ±adido: {product['name']} x{item.qty}"}
    except Exception as e:
        logger.error(f"Error procesando orden en add_to_order: {e}")
        raise HTTPException(status_code=500, detail=f"Error al procesar: {str(e)}")

@app.get("/kitchen_data")
def get_kitchen_data(api_key: str = Depends(get_api_key)):
    """Devuelve los Ã­tems pendientes agrupados para la pantalla de cocina."""
    items = db.all('''
        SELECT oi.*, p.name product_name, t.id as table_number 
        FROM order_items oi 
        JOIN orders o ON o.id = oi.order_id 
        JOIN tables t ON t.current_order_id = o.id 
        JOIN products p ON p.id = oi.product_id
        WHERE o.status = 'open' AND o.kitchen_status != 'ready'
    ''')
    return [dict(i) for i in items]

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"business_name": "Restaurante", "theme_color": "#10b981", "whatsapp_number": ""}

class WhatsappConfigSchema(BaseModel):
    whatsapp_number: str

@app.post("/api/settings/whatsapp")
def update_whatsapp(data: WhatsappConfigSchema, api_key: str = Depends(get_api_key)):
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), "branding.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            bdata = json.load(f)
    except:
        bdata = {}
    
    bdata["whatsapp_number"] = data.whatsapp_number
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bdata, f, indent=2)
    return {"status": "ok"}

class ConfigKeyValueSchema(BaseModel):
    key: str
    value: str

@app.get("/api/config")
def get_config(api_key: str = Depends(get_api_key)):
    import json
    import os
    try:
        path = os.path.join(os.path.dirname(__file__), "branding.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

@app.post("/api/config")
def update_config(data: ConfigKeyValueSchema, api_key: str = Depends(get_api_key)):
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), "branding.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            bdata = json.load(f)
    except:
        bdata = {}
    
    bdata[data.key] = data.value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bdata, f, indent=2)
    return {"status": "ok"}
@app.get("/dashboard_data")
def get_dashboard_data(api_key: str = Depends(get_api_key)):
    summary = db.sales_summary_today()
    insights = []
    if summary['items']:
        top_item = summary['items'][0]['product_name']
        insights.append(f"Tu producto estrella hoy es '{top_item}'. Â¡AsegÃºrate de preparar suficiente inventario para maÃ±ana!")
    if summary['total'] > 500000:
        insights.append("Â¡Excelente trabajo! Has superado la barrera de medio millÃ³n en ventas hoy. El negocio va en crecimiento.")
    elif summary['total'] == 0:
        insights.append("AÃºn no hay ventas registradas. Â¡Aprovecha para organizar el local y estar listo!")
    else:
        insights.append("Las ventas fluyen con normalidad. Sugiero lanzar una promociÃ³n de bebida para aumentar el ticket promedio.")
    summary['ai_insights'] = insights
    return summary

    return {"status": "ok"}

@app.websocket("/ws/kitchen")
async def websocket_endpoint(websocket: WebSocket, token: str = None):
    payload = verify_token(token) if token else None
    if not payload:
        await websocket.close(code=1008, reason="Invalid Token")
        return
    await manager.connect_kitchen(websocket)
    try:

@app.websocket("/ws/cfd")
async def websocket_cfd(websocket: WebSocket, api_key: str = None):
    payload = verify_token(token) if token else None
    if not payload:
        await websocket.close(code=1008, reason="Invalid Token")
        return
    await manager.connect_cfd(websocket)
    try:
    except WebSocketDisconnect:
        manager.disconnect_cfd(websocket)

# --- WEB POS & ADMIN ENDPOINTS ---

class UserSchema(BaseModel):
    username: str
    role: str
    pin: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    cedula: Optional[str] = None
    phone: Optional[str] = None
    tip_amount: float = 0.0
    active: int = 1
    daily_wage: float = 0.0

@app.get("/api/users")
def get_users(api_key: str = Depends(get_api_key)):
    users = db.all('SELECT * FROM users ORDER BY role, username')
    return [dict(u) for u in users]

@app.post("/api/users")
def create_user(user: UserSchema, api_key: str = Depends(get_api_key)):
    from app.security import hash_password
    pw_hash = hash_password("1234")
    db.execute('INSERT INTO users (username, role, password_hash, pin, active, first_name, last_name, cedula, phone, daily_wage) VALUES (?,?,?,?,?,?,?,?,?,?)',
               (user.username, user.role, pw_hash, user.pin, user.active, user.first_name, user.last_name, user.cedula, user.phone, user.daily_wage))
    return {"status": "ok"}

class CustomerOrderItem(BaseModel):
    product_id: int
    qty: int
    notes: Optional[str] = ""

class CustomerOrderSchema(BaseModel):
    table_id: int
    items: List[CustomerOrderItem]
    is_donation: bool = False

@app.get("/api/customer/menu", response_model=List[ProductResponse])
def get_customer_menu():
    """Public endpoint for customers scanning the QR code"""
    try:
        productos = db.all("SELECT id, name, price_cop, category_id FROM products WHERE active=1")
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

class DeliveryOrderSchema(BaseModel):
    name: str
    phone: str
    address: str
    payment_method: str
    items: List[CustomerOrderItem]

@app.post("/api/delivery/order")
async def place_delivery_order(data: DeliveryOrderSchema):
    """Customer submits an order from their phone for home delivery"""
    try:
        table_name = f"Domicilio: {data.name} - Tel: {data.phone} - Dir: {data.address}"
        
        # Delivery orders are always new orders
        order_id = db.insert(
            "INSERT INTO orders (status, table_name, payment_method, total_cop) VALUES ('open', ?, ?, 0)", 
            (table_name, data.payment_method)
        )
            
        # AÃ±adimos los productos
        for item in data.items:
            product = db.one("SELECT name, price_cop FROM products WHERE id=?", (item.product_id,))
            if product:
                total = product['price_cop'] * item.qty
                db.execute(
                    """INSERT INTO order_items (order_id, product_id, product_name, qty, price_cop, total_cop, notes) 
                       VALUES (?, ?, ?, ?, ?, ?, ?)""", 
                    (order_id, item.product_id, product['name'], item.qty, product['price_cop'], total, item.notes)
                )
                
        # Recalculamos el total
        subtotal_row = db.one("SELECT SUM(total_cop) as sub FROM order_items WHERE order_id=?", (order_id,))
        total_val = subtotal_row['sub'] if subtotal_row['sub'] else 0
        db.execute("UPDATE orders SET total_cop=? WHERE id=?", (total_val, order_id))
        
        await manager.broadcast_kitchen("update_kitchen")
        return {"status": "success", "order_id": order_id}
    except Exception as e:
        logger.error(f"Error procesando orden a domicilio: {e}")
        raise HTTPException(status_code=500, detail=f"Error al procesar: {str(e)}")

# --- ATTENDANCE & PRODUCTION ENDPOINTS ---

class AttendanceSchema(BaseModel):
    pin: str

@app.post("/api/attendance/log")
def log_attendance(data: AttendanceSchema, api_key: str = Depends(get_api_key)):
    user = db.one("SELECT * FROM users WHERE pin=?", (data.pin,))
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Determinar si es entrada o salida (busca el Ãºltimo registro)
    last_log = db.one("SELECT log_type FROM attendance_logs WHERE user_id=? ORDER BY id DESC LIMIT 1", (user['id'],))
    new_type = 'out' if last_log and last_log['log_type'] == 'in' else 'in'
    
    timestamp = datetime.datetime.now().isoformat()
    db.execute("INSERT INTO attendance_logs (user_id, log_type, timestamp) VALUES (?,?,?)", (user['id'], new_type, timestamp))
    return {"status": "ok", "type": new_type, "user": user['first_name'] or user['username']}

class ProdStartSchema(BaseModel):
    pin: str
    process_name: str

@app.post("/api/production/start")
def start_production(data: ProdStartSchema, api_key: str = Depends(get_api_key)):
    user = db.one("SELECT * FROM users WHERE pin=?", (data.pin,))
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    timestamp = datetime.datetime.now().isoformat()
    db.execute("INSERT INTO production_logs (user_id, process_name, start_time, status) VALUES (?,?,?,?)",
               (user['id'], data.process_name, timestamp, 'in_progress'))
    return {"status": "ok"}

class ProdEndSchema(BaseModel):
    pin: str
    qty: int

@app.post("/api/production/end")
def end_production(data: ProdEndSchema, api_key: str = Depends(get_api_key)):
    user = db.one("SELECT * FROM users WHERE pin=?", (data.pin,))
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    log = db.one("SELECT id FROM production_logs WHERE user_id=? AND status='in_progress' ORDER BY id DESC LIMIT 1", (user['id'],))
    if not log:
        raise HTTPException(status_code=400, detail="No hay procesos iniciados")
        
    timestamp = datetime.datetime.now().isoformat()
    db.execute("UPDATE production_logs SET end_time=?, qty=?, status='completed' WHERE id=?", (timestamp, data.qty, log['id']))
    return {"status": "ok"}

@app.get("/api/production/stats")
def get_production_stats(api_key: str = Depends(get_api_key)):
    # Tiempos promedio
    logs = db.all("SELECT * FROM production_logs WHERE status='completed'")
    processes = {}
    users_stats = {}
    
    for l in logs:
        try:
            t1 = datetime.datetime.fromisoformat(l['start_time'])
            t2 = datetime.datetime.fromisoformat(l['end_time'])
            diff_mins = (t2 - t1).total_seconds() / 60.0
            
            pname = l['process_name']
            if pname not in processes: processes[pname] = []
            processes[pname].append(diff_mins)
            
            uid = l['user_id']
            if uid not in users_stats: users_stats[uid] = 0
            users_stats[uid] += l['qty']
        except:
            pass
            
    avg_times = {k: sum(v)/len(v) for k,v in processes.items()}
    
    # Leaderboard
    leaderboard = []
    for uid, qty in users_stats.items():
        u = db.one("SELECT username, first_name FROM users WHERE id=?", (uid,))
        name = u['first_name'] or u['username'] if u else f"User {uid}"
        leaderboard.append({"name": name, "qty": qty})
        
    leaderboard.sort(key=lambda x: x['qty'], reverse=True)
    
    # Attendance report today
    today = datetime.date.today().isoformat()
    att = db.all("SELECT a.*, u.first_name, u.username FROM attendance_logs a JOIN users u ON u.id=a.user_id WHERE substr(a.timestamp,1,10)=?", (today,))
    
    return {"avg_times": avg_times, "leaderboard": leaderboard, "attendance": [dict(a) for a in att]}

class ProductSchema(BaseModel):
    name: str
    price_cop: float
    category_id: int = 1

@app.get("/api/customers/{phone}")
def get_customer(phone: str, api_key: str = Depends(get_api_key)):
    customer = db.one('SELECT * FROM customers WHERE phone=?', (phone,))
    if customer:
        return dict(customer)
    return {"points": 0, "name": ""}

@app.get("/api/products")
def get_products(api_key: str = Depends(get_api_key)):
    products = db.all('SELECT * FROM products ORDER BY name')
    return [dict(p) for p in products]

@app.post("/api/products")
def add_product(prod: ProductSchema, api_key: str = Depends(get_api_key)):
    db.execute('INSERT INTO products (name, price_cop, category_id) VALUES (?,?,?)',
               (prod.name, prod.price_cop, prod.category_id))
    return {"status": "ok"}

class PaymentSchema(BaseModel):
    order_id: int
    method: str
    phone: Optional[str] = None
    tip_amount: float = 0.0
    points_used: int = 0

@app.post("/api/pos/pay")
def process_payment(data: PaymentSchema, api_key: str = Depends(get_api_key)):
    if data.phone:
        order = db.one("SELECT total_cop FROM orders WHERE id=?", (data.order_id,))
        if order:
            points_earned = int(order['total_cop'] / 100)
            db.execute("INSERT INTO customers (phone, points) VALUES (?, ?) ON CONFLICT(phone) DO UPDATE SET points = points + ?", 
                       (data.phone, points_earned, points_earned))
            
            if data.points_used > 0:
                # Deduct points used
                db.execute("UPDATE customers SET points = points - ? WHERE phone=?", (data.points_used, data.phone))
                # Optionally reduce order total_cop (simple discount)
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

@app.get("/api/pos/orders")
def get_open_orders(api_key: str = Depends(get_api_key)):
    orders = db.all("SELECT o.*, t.id as table_number, t.name as table_name FROM orders o JOIN tables t ON t.current_order_id = o.id WHERE o.status='open'")
    res = []
    for o in orders:
        items = db.all("SELECT * FROM order_items WHERE order_id=?", (o['id'],))
        odict = dict(o)
        odict['items'] = [dict(i) for i in items]
        res.append(odict)
    return res

# (Mount moved to bottom of file)
@app.post("/api/sync_receive")
def sync_receive(data: dict):
    """Endpoint MODO MAESTRO: Recibe ventas de las sucursales y las guarda en su propia DB"""
        time.sleep(60)

def cloud_sync_worker():
    """Hilo MODO SUCURSAL: EnvÃ­a ventas a la Nube cada 5 mins si hay internet."""
    import json, os
    while True:
        try:
            branch_id = branding.get("branch_id", "SUC-01")
            
            if master_url and master_url.startswith("http"):
                # Busca Ã³rdenes cerradas que no se hayan sincronizado (Simulado aquÃ­ recogiendo las de hoy)
                from datetime import date
                today = date.today().isoformat()
                unsynced = db.all("SELECT * FROM orders WHERE status='closed' AND substr(closed_at,1,10)=?", (today,))
threading.Thread(target=run_scheduler, daemon=True).start()
threading.Thread(target=cloud_sync_worker, daemon=True).start()

frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
uploads_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", "uploads")
os.makedirs(os.path.join(uploads_path, "ads"), exist_ok=True)

from fastapi import File, UploadFile, Form
import shutil

@app.post("/api/ads")
def create_ad(
    api_key: str = Depends(get_api_key),
    file: UploadFile = File(...),
    price_text: str = Form(""),
    is_promo: int = Form(0),
    duration: int = Form(10)
):
    # Save the file
    file_location = os.path.join(uploads_path, "ads", file.filename)
    with open(file_location, "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)
    
    image_url = f"/uploads/ads/{file.filename}"
    
    db.execute('INSERT INTO ads (image_url, price_text, is_promo, duration) VALUES (?,?,?,?)',
               (image_url, price_text, is_promo, duration))
    return {"status": "ok"}

@app.get("/api/ads")
def get_ads():
    # Public endpoint for the menu board
    ads = db.all("SELECT * FROM ads ORDER BY id DESC")
    return [dict(a) for a in ads]

@app.delete("/api/ads/{ad_id}")
def delete_ad(ad_id: int, api_key: str = Depends(get_api_key)):
    ad = db.one("SELECT image_url FROM ads WHERE id=?", (ad_id,))
    if ad:
        filepath = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", ad['image_url'].lstrip('/'))
        if os.path.exists(filepath):
            os.remove(filepath)
        db.execute("DELETE FROM ads WHERE id=?", (ad_id,))
    return {"status": "ok"}

if os.path.exists(uploads_path):
    app.mount("/uploads", StaticFiles(directory=uploads_path), name="uploads")

if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

if __name__ == "__main__":
    # La direcciÃ³n '0.0.0.0' es vital para que los celulares en la misma red Wi-Fi puedan conectarse.
    # El servidor escucharÃ¡ peticiones en el puerto 8000.
    uvicorn.run(app, host="0.0.0.0", port=8000)
from pydantic import BaseModel
from typing import List, Optional

class PurchaseItemSchema(BaseModel):
    inventory_item_id: int
    qty: float
    cost: float

class PurchaseSchema(BaseModel):
    supplier: str
    details: str
    items: List[PurchaseItemSchema]

class RecipeItemSchema(BaseModel):
    inventory_item_id: int
    qty_needed: float

class RecipeSchema(BaseModel):
    items: List[RecipeItemSchema]

@app.get('/api/products/{product_id}/recipe')
def get_product_recipe(product_id: int, api_key: str = Depends(get_api_key)):
    recipe_rows = db.all('SELECT inventory_item_id, qty_needed FROM recipe_items WHERE product_id=?', (product_id,))
    return [dict(r) for r in recipe_rows]

@app.post('/api/products/{product_id}/recipe')
def set_product_recipe(product_id: int, recipe: RecipeSchema, api_key: str = Depends(get_api_key)):
    # Clear existing recipe
    db.execute('DELETE FROM recipe_items WHERE product_id=?', (product_id,))
    for item in recipe.items:
        db.execute('INSERT INTO recipe_items (product_id, inventory_item_id, qty_needed) VALUES (?,?,?)',
                   (product_id, item.inventory_item_id, item.qty_needed))
    return {'status': 'ok'}

@app.post('/api/purchases')
def create_purchase(data: PurchaseSchema, api_key: str = Depends(get_api_key)):
    from datetime import datetime
    total_cost = sum(i.qty * i.cost for i in data.items)
    purchase_id = db.insert('INSERT INTO purchases (date, supplier, total_cost, details) VALUES (?,?,?,?)',
                            (datetime.now().isoformat(), data.supplier, total_cost, data.details))
    for item in data.items:
        db.execute('INSERT INTO purchase_items (purchase_id, inventory_item_id, qty, cost) VALUES (?,?,?,?)',
                   (purchase_id, item.inventory_item_id, item.qty, item.cost))
        db.execute('UPDATE inventory_items SET stock_current = stock_current + ? WHERE id = ?',
                   (item.qty, item.inventory_item_id))
    return {'status': 'ok'}

@app.get('/api/shift/status')
def get_shift_status():
    # Only one open shift at a time globally for simplicity
    shift = db.one("SELECT * FROM cash_shifts WHERE status='open' ORDER BY id DESC LIMIT 1")
    if shift:
        return {"status": "open", "base_cash": shift["base_cash"], "opened_at": shift["opened_at"]}
    return {"status": "closed"}

class ShiftOpenRequest(BaseModel):
    base_cash: float

@app.post('/api/shift/open')
def open_shift(req: ShiftOpenRequest, api_key: dict = Depends(get_api_key)):
    from datetime import datetime
    # Check if already open
    shift = db.one("SELECT id FROM cash_shifts WHERE status='open' ORDER BY id DESC LIMIT 1")
    if shift:
        raise HTTPException(status_code=400, detail="Ya hay un turno abierto")
        
    db.execute("INSERT INTO cash_shifts (cashier_id, opened_at, base_cash, status) VALUES (?,?,?,?)",
               (api_key.get('id', 0), datetime.now().isoformat(), req.base_cash, 'open'))
    return {"status": "ok"}

class ShiftCloseRequest(BaseModel):
    actual_cash: float

@app.post('/api/shift/close')
def close_shift(req: ShiftCloseRequest, api_key: dict = Depends(get_api_key)):
    from datetime import datetime, date
    
    # 0. Find open shift
    shift = db.one("SELECT * FROM cash_shifts WHERE status='open' ORDER BY id DESC LIMIT 1")
    if not shift:
        raise HTTPException(status_code=400, detail="No hay ningún turno abierto")
        
    today = date.today().isoformat()
    # 1. Total ventas en efectivo
    cash_sales = db.all('SELECT SUM(total_cop) as t FROM orders WHERE status=''closed'' AND payment_method=''efectivo'' AND substr(closed_at,1,10)=?', (today,))
    total_cash_sales = cash_sales[0]['t'] or 0.0

    # 2. Total propinas de hoy
    tips = db.all('SELECT SUM(tip_amount_cop) as t FROM orders WHERE status=''closed'' AND substr(closed_at,1,10)=?', (today,))
    total_tips = tips[0]['t'] or 0.0

    # 3. Asistencias de hoy
    att = db.all('SELECT DISTINCT user_id FROM attendance_logs WHERE log_type=''entrada'' AND substr(timestamp,1,10)=?', (today,))
    user_ids = [r['user_id'] for r in att]
    
    total_payroll = 0.0
    for uid in user_ids:
        u = db.one('SELECT daily_wage FROM users WHERE id=?', (uid,))
        if u:
            total_payroll += (u['daily_wage'] or 0.0)

    # 3.5 Egresos de hoy
    expenses_data = db.all('SELECT SUM(amount) as t FROM expenses WHERE shift_id=?', (shift['id'],))
    total_expenses = expenses_data[0]['t'] or 0.0

    # 4. Cálculos
    base_cash = shift['base_cash'] or 0.0
    tips_distributed = total_tips
    payroll_distributed = total_payroll
    expected_cash = base_cash + total_cash_sales - tips_distributed - payroll_distributed - total_expenses
    difference = req.actual_cash - expected_cash

    db.execute('UPDATE cash_shifts SET closed_at=?, expected_cash=?, actual_cash=?, tips_distributed=?, payroll_distributed=?, difference=?, status=? WHERE id=?',
               (datetime.now().isoformat(), expected_cash, req.actual_cash, tips_distributed, payroll_distributed, difference, 'closed', shift['id']))
    
    # 5. AUTO-BACKUP
    import shutil
    import os
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"taqueria_{timestamp_str}.db"
    backup_path = app.paths.BACKUP_DIR / backup_filename
    
    # Force DB sync
    db._conn.commit()
    
    try:
        shutil.copy2(str(app.paths.DB_PATH), str(backup_path))
    except Exception as e:
        print("Error during backup:", e)

    return {
        'status': 'ok',
        'expected_cash': expected_cash,
        'difference': difference,
        'backup': backup_filename,
        'total_cash_sales': total_cash_sales,
        'total_tips': total_tips,
        'total_payroll': total_payroll,
        'total_expenses': total_expenses,
        'base_cash': base_cash
    }

class ExpenseSchema(BaseModel):
    description: str
    amount: float

@app.post('/api/expenses')
def add_expense(req: ExpenseSchema, api_key: dict = Depends(get_api_key)):
    from datetime import datetime
    shift = db.one("SELECT id FROM cash_shifts WHERE status='open' ORDER BY id DESC LIMIT 1")
    shift_id = shift['id'] if shift else None
    
    db.execute("INSERT INTO expenses (description, amount, date, cashier_id, shift_id) VALUES (?,?,?,?,?)",
               (req.description, req.amount, datetime.now().isoformat(), api_key.get('id', 0), shift_id))
    return {"status": "ok"}

@app.get('/api/backups')
def list_backups(api_key: dict = Depends(get_api_key)):
    import os
    if api_key.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Acceso denegado")
    
    backups = []
    if app.paths.BACKUP_DIR.exists():
        for f in os.listdir(app.paths.BACKUP_DIR):
            if f.endswith('.db') or f.endswith('.zip'):
                path = app.paths.BACKUP_DIR / f
                size = os.path.getsize(path) / 1024 # KB
                backups.append({"filename": f, "size_kb": round(size, 2)})
    return sorted(backups, key=lambda x: x['filename'], reverse=True)

from fastapi.responses import FileResponse
@app.get('/api/backups/{filename}')
def download_backup(filename: str, api_key: dict = Depends(get_api_key)):
    if api_key.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Acceso denegado")
    
    path = app.paths.BACKUP_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Backup no encontrado")
    
    return FileResponse(path, filename=filename, media_type='application/octet-stream')

class VerifyPinSchema(BaseModel):
    pin: str

@app.post('/api/auth/verify_admin_pin')
def verify_admin_pin(req: VerifyPinSchema):
    # En una implementación real, se busca un user con role=admin y pin=req.pin
    # Simplificación: Asumiremos un PIN maestro '9999' para admin, 
    # o verificamos en base de datos si el pin pertenece a algún usuario 'admin'.
    admin = db.one("SELECT id FROM users WHERE role='admin' AND pin=?", (req.pin,))
    if admin or req.pin == '9999': # Fallback maestro
        return {"status": "ok", "valid": True}
    return {"status": "error", "valid": False}


@app.get("/api/reports")
def get_reports(start_date: str, end_date: str, api_key: dict = Depends(get_api_key)):
    orders = db.all("SELECT total_cop, payment_method, substr(closed_at,1,10) as date FROM orders WHERE status='closed' AND substr(closed_at,1,10) BETWEEN ? AND ?", (start_date, end_date))
    return orders

@app.get("/api/inventory")
def get_inventory(api_key: dict = Depends(get_api_key)):
    items = db.all("SELECT * FROM inventory_items")
    return items

class MinStockSchema(BaseModel):
    min_stock: float

@app.put("/api/inventory/{item_id}/min_stock")
def update_min_stock(item_id: int, data: MinStockSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE inventory_items SET stock_min=? WHERE id=?", (data.min_stock, item_id))
    return {"status": "ok"}

class ItemNotesSchema(BaseModel):
    notes: str

@app.patch("/api/pos/orders/{order_id}/items/{item_id}/notes")
def update_item_notes(order_id: int, item_id: int, data: ItemNotesSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE order_items SET notes=? WHERE id=? AND order_id=?", (data.notes, item_id, order_id))
    return {"status": "ok"}

class ItemStatusSchema(BaseModel):
    status: str

@app.patch("/api/pos/orders/{order_id}/items/{item_id}/status")
async def update_item_status(order_id: int, item_id: int, data: ItemStatusSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE order_items SET status=? WHERE id=? AND order_id=?", (data.status, item_id, order_id))
    await manager.broadcast_kitchen("update_kitchen")
    return {"status": "ok"}

class KitchenStatusSchema(BaseModel):
    kitchen_status: str

@app.patch("/api/pos/orders/{order_id}/kitchen_status")
async def update_kitchen_status(order_id: int, data: KitchenStatusSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE orders SET kitchen_status=? WHERE id=?", (data.kitchen_status, order_id))
    await manager.broadcast_kitchen("update_kitchen")
    if data.kitchen_status == 'ready':
        await manager.broadcast_kitchen("update_customer_screen") # Optional: Si usaran la misma connection manager
    return {"status": "ok"}

class AddStockSchema(BaseModel):
    amount: float

@app.post("/api/inventory/{item_id}/add_stock")
def add_inventory_stock(item_id: int, data: AddStockSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE inventory_items SET stock_current = stock_current + ? WHERE id=?", (data.amount, item_id))
    db.log("admin", "ADD_STOCK", f"Añadido {data.amount} al item {item_id}")
    return {"status": "ok"}

class WasteSchema(BaseModel):
    amount: float
    reason: str

@app.post("/api/inventory/{item_id}/waste")
def register_waste(item_id: int, data: WasteSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE inventory_items SET stock_current = stock_current - ? WHERE id=?", (data.amount, item_id))
    db.execute("INSERT INTO waste_logs (inventory_item_id, qty, reason, user_id) VALUES (?,?,?,?)",
               (item_id, data.amount, data.reason, api_key.get('id', 0)))
    db.log("admin", "WASTE", f"Merma de {data.amount} en item {item_id} por {data.reason}")
    return {"status": "ok"}

@app.get("/api/inventory/predict")
def predict_purchases(api_key: dict = Depends(get_api_key)):
    # Simple ML heuristic: Calculate daily consumption of each inventory item based on closed orders in the last 7 days.
    # We join orders -> order_items -> recipes -> inventory_items.
    # Note: SQLite datetime('now', '-7 days') works nicely.
    
    query = """
    SELECT 
        i.id, i.name, i.stock_current, i.unit,
        SUM(r.qty * oi.qty) as consumed_7_days
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    JOIN recipes r ON r.product_id = oi.product_id
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
def get_users(api_key: dict = Depends(get_api_key)):
    return [dict(r) for r in db.all("SELECT id, username, role, pin, active, daily_wage FROM users")]

class UserCreateSchema(BaseModel):
    username: str
    password: str
    role: str
    pin: str
    daily_wage: float

@app.post("/api/users")
def create_user(data: UserCreateSchema, api_key: dict = Depends(get_api_key)):
    from app.auth import get_password_hash
    hash_pw = get_password_hash(data.password)
    db.execute("INSERT INTO users (username, password_hash, role, pin, active, daily_wage) VALUES (?,?,?,?,1,?)",
               (data.username, hash_pw, data.role, data.pin, data.daily_wage))
    return {"status": "ok"}

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
    return {"status": "ok"}

@app.get("/api/reports/sales_trend")
def get_sales_trend(api_key: dict = Depends(get_api_key)):
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

# --- DELIVERY / REPARTIDORES ---
@app.get("/api/delivery/pending")
def get_pending_deliveries(api_key: dict = Depends(get_api_key)):
    # Trae los que están listos o en proceso, con tipo Domicilio
    driver_id = api_key.get('id')
    rows = db.all("""
        SELECT o.* 
        FROM orders o 
        WHERE o.table_name LIKE 'Domicilio%' 
          AND o.status = 'open'
          AND (o.driver_id IS NULL OR o.driver_id = ?)
    """, (driver_id,))
    
    # Enrich with items
    for r in rows:
        r['items'] = [dict(i) for i in db.all("SELECT * FROM order_items WHERE order_id=?", (r['id'],))]
    return [dict(r) for r in rows]

@app.post("/api/delivery/assign/{order_id}")
    
    path = app.paths.BACKUP_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Backup no encontrado")
    
    return FileResponse(path, filename=filename, media_type='application/octet-stream')

class VerifyPinSchema(BaseModel):
    pin: str

@app.post('/api/auth/verify_admin_pin')
def verify_admin_pin(req: VerifyPinSchema):
    # En una implementación real, se busca un user con role=admin y pin=req.pin
    # Simplificación: Asumiremos un PIN maestro '9999' para admin, 
    # o verificamos en base de datos si el pin pertenece a algún usuario 'admin'.
    admin = db.one("SELECT id FROM users WHERE role='admin' AND pin=?", (req.pin,))
    if admin or req.pin == '9999': # Fallback maestro
        return {"status": "ok", "valid": True}
    return {"status": "error", "valid": False}


@app.get("/api/reports")
def get_reports(start_date: str, end_date: str, api_key: dict = Depends(get_api_key)):
    orders = db.all("SELECT total_cop, payment_method, substr(closed_at,1,10) as date FROM orders WHERE status='closed' AND substr(closed_at,1,10) BETWEEN ? AND ?", (start_date, end_date))
    return orders

@app.get("/api/inventory")
def get_inventory(api_key: dict = Depends(get_api_key)):
    items = db.all("SELECT * FROM inventory_items")
    return items

class MinStockSchema(BaseModel):
    min_stock: float

@app.put("/api/inventory/{item_id}/min_stock")
def update_min_stock(item_id: int, data: MinStockSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE inventory_items SET stock_min=? WHERE id=?", (data.min_stock, item_id))
    return {"status": "ok"}

class ItemNotesSchema(BaseModel):
    notes: str

@app.patch("/api/pos/orders/{order_id}/items/{item_id}/notes")
def update_item_notes(order_id: int, item_id: int, data: ItemNotesSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE order_items SET notes=? WHERE id=? AND order_id=?", (data.notes, item_id, order_id))
    return {"status": "ok"}

class ItemStatusSchema(BaseModel):
    status: str

@app.patch("/api/pos/orders/{order_id}/items/{item_id}/status")
async def update_item_status(order_id: int, item_id: int, data: ItemStatusSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE order_items SET status=? WHERE id=? AND order_id=?", (data.status, item_id, order_id))
    await manager.broadcast_kitchen("update_kitchen")
    return {"status": "ok"}

class KitchenStatusSchema(BaseModel):
    kitchen_status: str

@app.patch("/api/pos/orders/{order_id}/kitchen_status")
async def update_kitchen_status(order_id: int, data: KitchenStatusSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE orders SET kitchen_status=? WHERE id=?", (data.kitchen_status, order_id))
    await manager.broadcast_kitchen("update_kitchen")
    if data.kitchen_status == 'ready':
        await manager.broadcast_kitchen("update_customer_screen") # Optional: Si usaran la misma connection manager
    return {"status": "ok"}

class AddStockSchema(BaseModel):
    amount: float

@app.post("/api/inventory/{item_id}/add_stock")
def add_inventory_stock(item_id: int, data: AddStockSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE inventory_items SET stock_current = stock_current + ? WHERE id=?", (data.amount, item_id))
    db.log("admin", "ADD_STOCK", f"Añadido {data.amount} al item {item_id}")
    return {"status": "ok"}

class WasteSchema(BaseModel):
    amount: float
    reason: str

@app.post("/api/inventory/{item_id}/waste")
def register_waste(item_id: int, data: WasteSchema, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE inventory_items SET stock_current = stock_current - ? WHERE id=?", (data.amount, item_id))
    db.execute("INSERT INTO waste_logs (inventory_item_id, qty, reason, user_id) VALUES (?,?,?,?)",
               (item_id, data.amount, data.reason, api_key.get('id', 0)))
    db.log("admin", "WASTE", f"Merma de {data.amount} en item {item_id} por {data.reason}")
    return {"status": "ok"}

@app.get("/api/inventory/predict")
def predict_purchases(api_key: dict = Depends(get_api_key)):
    # Simple ML heuristic: Calculate daily consumption of each inventory item based on closed orders in the last 7 days.
    # We join orders -> order_items -> recipes -> inventory_items.
    # Note: SQLite datetime('now', '-7 days') works nicely.
    
    query = """
    SELECT 
        i.id, i.name, i.stock_current, i.unit,
        SUM(r.qty * oi.qty) as consumed_7_days
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    JOIN recipes r ON r.product_id = oi.product_id
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
def get_users(api_key: dict = Depends(get_api_key)):
    return [dict(r) for r in db.all("SELECT id, username, role, pin, active, daily_wage FROM users")]

class UserCreateSchema(BaseModel):
    username: str
    password: str
    role: str
    pin: str
    daily_wage: float

@app.post("/api/users")
def create_user(data: UserCreateSchema, api_key: dict = Depends(get_api_key)):
    from app.auth import get_password_hash
    hash_pw = get_password_hash(data.password)
    db.execute("INSERT INTO users (username, password_hash, role, pin, active, daily_wage) VALUES (?,?,?,?,1,?)",
               (data.username, hash_pw, data.role, data.pin, data.daily_wage))
    return {"status": "ok"}

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, api_key: dict = Depends(get_api_key)):
    db.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
    return {"status": "ok"}

@app.get("/api/reports/sales_trend")
def get_sales_trend(api_key: dict = Depends(get_api_key)):
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

# --- DELIVERY / REPARTIDORES ---
@app.get("/api/delivery/pending")
def get_pending_deliveries(api_key: dict = Depends(get_api_key)):
    # Trae los que están listos o en proceso, con tipo Domicilio
    driver_id = api_key.get('id')
    rows = db.all("""
        SELECT o.* 
        FROM orders o 
        WHERE o.table_name LIKE 'Domicilio%' 
          AND o.status = 'open'
          AND (o.driver_id IS NULL OR o.driver_id = ?)
    """, (driver_id,))
    
    # Enrich with items
    for r in rows:
        r['items'] = [dict(i) for i in db.all("SELECT * FROM order_items WHERE order_id=?", (r['id'],))]
    return [dict(r) for r in rows]

@app.post("/api/delivery/assign/{order_id}")
def assign_delivery(order_id: int, api_key: dict = Depends(get_api_key)):
    driver_id = api_key.get('id')
    db.execute("UPDATE orders SET driver_id = ?, kitchen_status = 'on_the_way' WHERE id = ?", (driver_id, order_id))
    return {"status": "ok"}

@app.post("/api/delivery/complete/{order_id}")
def complete_delivery(order_id: int, api_key: dict = Depends(get_api_key)):
    driver_id = api_key.get('id')
    # Se marca como entregado. El cobro debió hacerse o se hace después.
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
def generate_dian_invoice(data: DianCustomerSchema, api_key: dict = Depends(get_api_key)):
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
