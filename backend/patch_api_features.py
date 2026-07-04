import sqlite3
import os
from pathlib import Path

db_path = Path("c:/Users/Camilo/Desktop/taqueria/backend/data/taqueria.db")
conn = sqlite3.connect(db_path)
conn.execute('''
CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    res_date TEXT NOT NULL,
    res_time TEXT NOT NULL,
    guests INTEGER NOT NULL,
    status TEXT DEFAULT 'pending'
)
''')
conn.commit()
conn.close()

with open('api.py', 'r', encoding='utf-8') as f:
    api_code = f.read()

endpoints = """
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
def get_reservations(api_key: dict = Depends(get_api_key)):
    rows = db.all("SELECT * FROM reservations ORDER BY res_date ASC, res_time ASC")
    return [dict(r) for r in rows]

@app.post("/api/reservations/{res_id}/status")
def update_reservation(res_id: int, data: dict, api_key: dict = Depends(get_api_key)):
    status = data.get("status", "pending")
    db.execute("UPDATE reservations SET status=? WHERE id=?", (status, res_id))
    return {"status": "ok"}

# --- ONLINE PAYMENTS ---
@app.post("/api/customer/pay/{order_id}")
def customer_online_pay(order_id: int):
    # Simulates MercadoPago / Wompi successful callback
    db.close_order_with_inventory(order_id, "online")
    return {"status": "ok"}

"""

# Inject before `# --- DELIVERY / REPARTIDORES ---`
if "# --- DELIVERY / REPARTIDORES ---" in api_code and "# --- RESERVATIONS ---" not in api_code:
    api_code = api_code.replace("# --- DELIVERY / REPARTIDORES ---", endpoints + "\n# --- DELIVERY / REPARTIDORES ---")

# Let's also patch the kitchen broadcast for WhatsApp simulation in the close_order or order_items status change
# Actually, the WhatsApp simulation can be triggered when kitchen_status changes.
# In `api.py`, there is `api/delivery/assign` and `api/delivery/complete`.

whatsapp_patch_1 = """
    driver_id = api_key.get('id')
    logger.info(f"📱 WHATSAPP AL CLIENTE: 'Tu pedido (Orden #{order_id}) va en camino con tu domiciliario. ¡Espéralo pronto!'")
    db.execute("UPDATE orders SET driver_id = ?, kitchen_status = 'on_the_way' WHERE id = ?", (driver_id, order_id))
"""
api_code = api_code.replace("""
    driver_id = api_key.get('id')
    db.execute("UPDATE orders SET driver_id = ?, kitchen_status = 'on_the_way' WHERE id = ?", (driver_id, order_id))
""", whatsapp_patch_1)

whatsapp_patch_2 = """
    # Se marca como entregado. El cobro debió hacerse o se hace después.
    logger.info(f"📱 WHATSAPP AL CLIENTE: 'Tu pedido (Orden #{order_id}) ha sido entregado. ¡Que lo disfrutes!'")
    db.execute("UPDATE orders SET kitchen_status = 'delivered' WHERE id = ? AND driver_id = ?", (order_id, driver_id))
"""
api_code = api_code.replace("""
    # Se marca como entregado. El cobro debió hacerse o se hace después.
    db.execute("UPDATE orders SET kitchen_status = 'delivered' WHERE id = ? AND driver_id = ?", (order_id, driver_id))
""", whatsapp_patch_2)

with open('api.py', 'w', encoding='utf-8') as f:
    f.write(api_code)

print("Backend API Updated")
