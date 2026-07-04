missing_code = """
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
    new_notes = f"{order['notes'] or ''}\\n[DIAN CUFE: {invoice_result['cufe']}]\\n[FEV: {invoice_result['invoice_number']}]"
    db.execute("UPDATE orders SET notes = ? WHERE id = ?", (new_notes, data.order_id))
    
    return invoice_result

import os
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
uploads_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", "uploads")
if os.path.exists(uploads_path):
    app.mount("/uploads", StaticFiles(directory=uploads_path), name="uploads")

if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
"""

with open("api.py", "a", encoding="utf-8") as f:
    f.write(missing_code)
