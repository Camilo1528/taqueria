"""Fidelización, bonos (tarjetas de regalo / cumpleaños) y donaciones.

Reglas del negocio:
- Fidelización: 1 punto por compra. Con 10 puntos el cliente canjea un producto de recompensa,
  que se agrega GRATIS a la orden que se está cobrando (y se descuentan los 10 puntos).
- El cliente se identifica por cédula O por teléfono (se guardan ambos y se busca por cualquiera).
- Tarjeta de regalo vendida: es dinero que entra a la caja el día de la venta.
- Bono de cumpleaños / cortesía: es consumo en el local; no entra ni sale dinero de la caja.
- Pagar con bono descuenta el saldo y lo liga a la orden (voucher_amount_cop / voucher_code).
- Donación: la orden se cierra con método "donacion" ($0), descuenta inventario y queda en contabilidad.
"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import db

POINTS_FOR_REWARD = 10


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_rewards_schema() -> None:
    wanted = {
        "loyalty_customers": [("phone", "TEXT"), ("name", "TEXT"), ("created_at", "TEXT")],
        "vouchers": [("sold_method", "TEXT"), ("sold_by", "INTEGER"), ("shift_id", "INTEGER"),
                     ("sold_at", "TEXT"), ("description", "TEXT")],
        "orders": [("voucher_amount_cop", "REAL DEFAULT 0"), ("voucher_code", "TEXT"),
                   ("loyalty_customer", "TEXT")],
    }
    with db.connect() as con:
        con.execute("CREATE TABLE IF NOT EXISTS loyalty_customers (cedula TEXT PRIMARY KEY, name TEXT, points INTEGER DEFAULT 0)")
        for table, cols in wanted.items():
            existing = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            if not existing:
                continue
            for name, decl in cols:
                if name not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        con.commit()


# ---------------- Clientes de fidelización ----------------
def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def looks_like_phone(ident: str) -> bool:
    # Celulares en Colombia: 10 dígitos que empiezan por 3
    return len(ident) == 10 and ident.startswith("3")


def find_customer(ident: str | None):
    ident = _digits(ident)
    if not ident:
        return None
    return db.one("SELECT * FROM loyalty_customers WHERE cedula=? OR phone=? ORDER BY points DESC LIMIT 1", (ident, ident))


def get_or_create_customer(ident: str, name: str | None = None):
    ident = _digits(ident)
    c = find_customer(ident)
    if c:
        if name and not c["name"]:
            db.execute("UPDATE loyalty_customers SET name=? WHERE cedula=?", (name, c["cedula"]))
        return find_customer(ident)
    # La llave interna es "cedula"; si nos dieron un celular lo guardamos también como teléfono
    phone = ident if looks_like_phone(ident) else None
    db.execute("INSERT INTO loyalty_customers (cedula, phone, name, points, created_at) VALUES (?,?,?,0,?)",
               (ident, phone, name, _now()))
    return find_customer(ident)


def _customer_out(c) -> dict:
    if not c:
        return {"found": False, "points": 0, "can_redeem": False, "points_needed": POINTS_FOR_REWARD}
    pts = c["points"] or 0
    return {"found": True, "cedula": c["cedula"], "phone": c["phone"], "name": c["name"], "points": pts,
            "can_redeem": pts >= POINTS_FOR_REWARD, "points_needed": max(0, POINTS_FOR_REWARD - pts)}


def apply_loyalty(order_id: int, ident: str, redeemed_product_id: int | None) -> dict:
    """Se llama al cobrar (antes de cerrar la orden). Suma 1 punto o canjea la recompensa."""
    c = get_or_create_customer(ident)
    db.execute("UPDATE orders SET loyalty_customer=? WHERE id=?", (c["cedula"], order_id))
    if redeemed_product_id:
        product = db.one("SELECT id, name, price_cop FROM products WHERE id=? AND is_reward=1 AND active=1",
                         (redeemed_product_id,))
        if not product:
            raise HTTPException(status_code=400, detail="Ese producto no está disponible como recompensa")
        with db.connect() as con:
            cur = con.execute("UPDATE loyalty_customers SET points = points - ? WHERE cedula=? AND points >= ?",
                              (POINTS_FOR_REWARD, c["cedula"], POINTS_FOR_REWARD))
            con.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=400, detail=f"El cliente no tiene puntos suficientes (necesita {POINTS_FOR_REWARD})")
        db.execute("INSERT INTO order_items (order_id, product_id, product_name, qty, price_cop, total_cop, notes, status) "
                   "VALUES (?,?,?,1,0,0,?, 'ready')",
                   (order_id, product["id"], product["name"], f"⭐ Recompensa por {POINTS_FOR_REWARD} compras"))
        return {"redeemed": product["name"], "points": (c["points"] or 0) - POINTS_FOR_REWARD}
    db.execute("UPDATE loyalty_customers SET points = points + 1 WHERE cedula=?", (c["cedula"],))
    return {"redeemed": None, "points": (c["points"] or 0) + 1}


# ---------------- Esquemas ----------------
class CustomerSchema(BaseModel):
    cedula: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=20)
    name: str | None = Field(default=None, max_length=80)


class PayVoucherSchema(BaseModel):
    order_id: int
    code: str = Field(min_length=3, max_length=40)


class SellGiftCardSchema(BaseModel):
    value_cop: float = Field(gt=0, le=5_000_000)
    payment_method: str = "efectivo"
    description: str | None = Field(default="", max_length=120)


GIFT_SALE_METHODS = {"efectivo", "tarjeta", "transferencia", "nequi", "daviplata"}


def build_router(get_current_user, require_manager) -> APIRouter:
    router = APIRouter()

    # ----- Clientes -----
    @router.get("/api/loyalty/lookup/{ident}")
    def lookup_customer(ident: str, user: dict = Depends(get_current_user)):
        return _customer_out(find_customer(ident))

    @router.post("/api/loyalty/customers")
    def upsert_customer(data: CustomerSchema, user: dict = Depends(get_current_user)):
        ced, tel = _digits(data.cedula), _digits(data.phone)
        if not ced and not tel:
            raise HTTPException(status_code=400, detail="Escribe la cédula o el teléfono del cliente")
        c = find_customer(ced) or find_customer(tel)
        if c:
            db.execute("UPDATE loyalty_customers SET phone=COALESCE(NULLIF(?,''), phone), name=COALESCE(NULLIF(?,''), name) "
                       "WHERE cedula=?", (tel, (data.name or "").strip(), c["cedula"]))
            if ced and c["cedula"] != ced and looks_like_phone(c["cedula"]):
                # Se registró primero con el celular; ahora llega la cédula real
                if not db.one("SELECT cedula FROM loyalty_customers WHERE cedula=?", (ced,)):
                    db.execute("UPDATE loyalty_customers SET cedula=? WHERE cedula=?", (ced, c["cedula"]))
            c = find_customer(ced or tel)
        else:
            key = ced or tel
            db.execute("INSERT INTO loyalty_customers (cedula, phone, name, points, created_at) VALUES (?,?,?,0,?)",
                       (key, tel or None, (data.name or "").strip() or None, _now()))
            c = find_customer(key)
        return _customer_out(c)

    # ----- Pagar con bono / tarjeta de regalo -----
    @router.post("/api/pos/pay_voucher")
    def pay_with_voucher(data: PayVoucherSchema, user: dict = Depends(get_current_user)):
        code = data.code.strip().upper()
        order = db.one("SELECT * FROM orders WHERE id=?", (data.order_id,))
        if not order or order["status"] != "open":
            raise HTTPException(status_code=400, detail="La orden no existe o ya fue cobrada")
        v = db.one("SELECT * FROM vouchers WHERE upper(id)=?", (code,))
        if not v:
            raise HTTPException(status_code=404, detail="Bono no encontrado. Revisa el código")
        if v["type"] == "RECOMPENSA":
            raise HTTPException(status_code=400, detail="Ese código es de fidelización; el premio se canjea con la cédula del cliente")
        balance = v["balance_cop"] or 0
        if v["is_redeemed"] or balance <= 0:
            raise HTTPException(status_code=400, detail="Este bono ya no tiene saldo")
        due = (order["total_cop"] or 0) + (order["delivery_fee_cop"] or 0) - (order["voucher_amount_cop"] or 0)
        if due <= 0:
            raise HTTPException(status_code=400, detail="La orden ya está cubierta")
        use = min(balance, due)
        with db.connect() as con:
            cur = con.execute("UPDATE vouchers SET balance_cop = balance_cop - ?, is_redeemed = CASE WHEN balance_cop - ? <= 0 THEN 1 ELSE 0 END "
                              "WHERE id=? AND balance_cop >= ?", (use, use, v["id"], use))
            if cur.rowcount == 0:
                con.rollback()
                raise HTTPException(status_code=409, detail="El saldo del bono cambió; intenta de nuevo")
            con.execute("UPDATE orders SET voucher_amount_cop = COALESCE(voucher_amount_cop,0) + ?, "
                        "voucher_code = TRIM(COALESCE(voucher_code || ' ', '') || ?) WHERE id=?", (use, v["id"], order["id"]))
            con.commit()
        remaining = due - use
        db.log(user.get("sub"), "voucher_used", f"{v['id']} ${use} en orden {order['id']}")
        return {"applied": use, "remaining": remaining, "voucher_balance": balance - use,
                "covered": remaining <= 0, "type": v["type"]}

    # ----- Vender tarjeta de regalo (entra dinero a la caja) -----
    @router.post("/api/vouchers/sell")
    def sell_gift_card(data: SellGiftCardSchema, user: dict = Depends(require_manager)):
        import random
        import string
        method = data.payment_method.strip().lower()
        if method not in GIFT_SALE_METHODS:
            raise HTTPException(status_code=400, detail="Método de pago no válido para vender el bono")
        shift = db.one("SELECT id FROM cash_shifts WHERE status='open' AND cashier_id=? ORDER BY id DESC LIMIT 1",
                       (user.get("id"),))
        if method == "efectivo" and not shift:
            raise HTTPException(status_code=400, detail="Abre tu turno de caja para recibir el efectivo del bono")
        code = "BONO-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        db.execute("INSERT INTO vouchers (id, type, value_cop, balance_cop, is_redeemed, created_at, identifier, "
                   "sold_method, sold_by, shift_id, sold_at, description) VALUES (?, 'GIFT_CARD', ?, ?, 0, ?, 'CUSTOMER', ?, ?, ?, ?, ?)",
                   (code, data.value_cop, data.value_cop, _now(), method, user.get("id"), shift["id"] if shift else None,
                    _now(), data.description or ""))
        db.log(user.get("sub"), "gift_card_sold", f"{code} ${data.value_cop} {method}")
        return {"code": code, "value": data.value_cop, "payment_method": method}

    return router


# ---------------- Contabilidad (usado por accounting.py) ----------------
def vouchers_sold_between(start: str, end: str, method: str | None = None) -> float:
    q = "SELECT COALESCE(SUM(value_cop),0) v FROM vouchers WHERE type='GIFT_CARD' AND sold_at >= ? AND sold_at <= ?"
    p = [start, end]
    if method:
        q += " AND sold_method=?"
        p.append(method)
    return db.one(q, tuple(p))["v"]


def rewards_day_summary(day: str) -> dict:
    sold = {r["m"]: r["v"] for r in db.all(
        "SELECT sold_method m, SUM(value_cop) v FROM vouchers WHERE type='GIFT_CARD' AND substr(sold_at,1,10)=? GROUP BY m", (day,))}
    used = db.one("SELECT COALESCE(SUM(voucher_amount_cop),0) v FROM orders WHERE status='closed' AND branch_id IS NULL AND substr(closed_at,1,10)=?",
                  (day,))["v"]
    don = db.one("""SELECT COUNT(DISTINCT o.id) n, COALESCE(SUM(oi.qty * COALESCE(p.price_cop, 0)),0) v
                    FROM orders o JOIN order_items oi ON oi.order_id=o.id LEFT JOIN products p ON p.id=oi.product_id
                    WHERE o.status='closed' AND o.branch_id IS NULL AND o.payment_method='donacion' AND substr(o.closed_at,1,10)=?""", (day,))
    rewards = db.one("""SELECT COUNT(*) n, COALESCE(SUM(COALESCE(p.price_cop,0)),0) v FROM order_items oi
                        JOIN orders o ON o.id=oi.order_id LEFT JOIN products p ON p.id=oi.product_id
                        WHERE o.status='closed' AND o.branch_id IS NULL AND substr(o.closed_at,1,10)=? AND oi.notes LIKE '⭐ Recompensa%'""", (day,))
    return {"gift_cards_sold": sold, "gift_cards_sold_total": sum(sold.values()), "vouchers_used": used,
            "donations": don["n"], "donations_value": don["v"],
            "rewards_given": rewards["n"], "rewards_value": rewards["v"]}
