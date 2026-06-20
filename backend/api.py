import os
from fastapi import FastAPI, HTTPException, Security, Depends, WebSocket, WebSocketDisconnect
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
import shutil
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

class ProductResponse(BaseModel):
    id: int
    name: str
    price_cop: float
    category_id: Optional[int] = None

class TableResponse(BaseModel):
    id: int
    table_number: int
    is_open: int
    current_order_id: Optional[int] = None

@app.get("/menu", response_model=List[ProductResponse])
def get_menu(api_key: str = Depends(get_api_key)):
    """Retorna los productos activos para que el mesero los vea en su dispositivo."""
    try:
        # Consulta directamente la base de datos configurada en app/db.py
        productos = db.all("SELECT id, name, price_cop, category_id FROM products WHERE active=1")
        return [dict(p) for p in productos]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tables/status", response_model=List[TableResponse])
def get_tables_status(api_key: str = Depends(get_api_key)):
    """Permite al mesero visualizar el estado de las mesas en tiempo real."""
    mesas = db.all("SELECT id, table_number, is_open, current_order_id FROM tables")
    return [dict(m) for m in mesas]

@app.post("/add_to_order")
async def add_to_order(item: OrderItem, api_key: str = Depends(get_api_key)):
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
def get_kitchen_data(api_key: str = Depends(get_api_key)):
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
        return {"business_name": "Restaurante", "theme_color": "#10b981"}

@app.get("/dashboard_data")
def get_dashboard_data(api_key: str = Depends(get_api_key)):
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

# Servir los archivos del frontend
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

@app.post("/api/sync_receive")
def sync_receive(data: dict):
    """Endpoint MODO MAESTRO: Recibe ventas de las sucursales y las guarda en su propia DB"""
    try:
        branch_id = data.get("branch_id")
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

if __name__ == "__main__":
    # La dirección '0.0.0.0' es vital para que los celulares en la misma red Wi-Fi puedan conectarse.
    # El servidor escuchará peticiones en el puerto 8000.
    uvicorn.run(app, host="0.0.0.0", port=8000)