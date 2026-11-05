"""Endpoints que el frontend ya usaba pero no existían en el backend.

- GET  /api/ads                    (menu_board.html, público)
- POST /api/auth/verify_admin_pin  (cashier.html, autoriza acciones sensibles)
- POST /api/delivery/order         (delivery.html, pedido público a domicilio)
- GET  /api/orders/{id}            (ticket.html)
- POST /api/production/start|end   (kitchen.html, registro de producción por PIN)
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.db import db


def ensure_extras_schema() -> None:
    with db.connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT, image_url TEXT, price_text TEXT,
            is_promo INTEGER DEFAULT 0, duration INTEGER DEFAULT 10, created_at TEXT)""")
        existing = {r["name"] for r in con.execute("PRAGMA table_info(ads)")}
        for name, decl in (("sort_order", "INTEGER DEFAULT 0"), ("active", "INTEGER DEFAULT 1"),
                           ("screen", "TEXT DEFAULT 'ambas'"), ("title", "TEXT")):
            if name not in existing:
                con.execute(f"ALTER TABLE ads ADD COLUMN {name} {decl}")
        # Migración única: las imágenes que antes se guardaban en branding.json pasan a la tabla de anuncios
        if not con.execute("SELECT 1 FROM ads LIMIT 1").fetchone():
            try:
                import json
                import os
                bpath = os.path.join(os.path.dirname(os.path.dirname(__file__)), "branding.json")
                with open(bpath, "r", encoding="utf-8-sig") as f:
                    imgs = json.load(f).get("ad_images") or []
                for i, url in enumerate(imgs):
                    con.execute("INSERT INTO ads (image_url, duration, sort_order, active, screen, created_at) "
                                "VALUES (?, 8, ?, 1, 'ambas', ?)", (url, i, _now()))
            except (OSError, ValueError):
                pass
        con.execute("""CREATE TABLE IF NOT EXISTS production_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, process_name TEXT,
            start_time TEXT, end_time TEXT, qty REAL, status TEXT)""")
        con.commit()


class PinSchema(BaseModel):
    pin: str = Field(min_length=1, max_length=8)


class DeliveryItem(BaseModel):
    product_id: int
    qty: int = Field(gt=0, le=100)


class PublicDeliveryOrder(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(pattern=r"^[0-9+ ]{7,15}$")
    address: str = Field(min_length=3, max_length=200)
    payment_method: str
    items: List[DeliveryItem] = Field(min_length=1, max_length=50)
    zone: str | None = Field(default=None, max_length=80)
    reference: str | None = Field(default=None, max_length=200)  # punto de referencia / indicaciones


class ProductionStart(BaseModel):
    pin: str = Field(min_length=1, max_length=8)
    process_name: str = Field(min_length=1, max_length=80)


class ProductionEnd(BaseModel):
    pin: str = Field(min_length=1, max_length=8)
    qty: float = Field(gt=0)


class AdSchema(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    image_url: str = Field(min_length=1, max_length=300, pattern=r"^/uploads/[\w\-]+\.(png|jpe?g|webp|gif)$")
    price_text: str | None = Field(default=None, max_length=60)
    is_promo: bool = False
    duration: int = Field(default=8, ge=3, le=60)
    active: bool = True
    screen: str = Field(default="ambas", pattern=r"^(tv|caja|ambas)$")


class AdOrderSchema(BaseModel):
    ids: List[int] = Field(max_length=200)


DELIVERY_PAYMENTS = {"efectivo", "transferencia", "nequi", "daviplata", "tarjeta"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_router(get_current_user, check_rate_limit: Callable, register_fail: Callable, broadcast_kitchen,
                 get_zones: Callable = lambda: [], require_manager=None) -> APIRouter:
    router = APIRouter()
    require_manager = require_manager or get_current_user

    def _ip(request: Request) -> str:
        return request.client.host if request.client else "?"

    def _user_by_pin(pin: str, request: Request):
        ip = _ip(request)
        check_rate_limit(ip)
        user = db.one("SELECT * FROM users WHERE pin=? AND active=1", (pin,))
        if not user:
            register_fail(ip)
        return user

    @router.get("/api/ads")
    def list_ads(screen: str | None = None, all: bool = False):
        """Público. screen=tv (menú en TV) o screen=caja (pantalla del cliente en caja)."""
        q = "SELECT id, title, image_url, price_text, is_promo, duration, sort_order, active, screen FROM ads WHERE 1=1"
        p: list = []
        if not all:
            q += " AND active=1"
        if screen in ("tv", "caja"):
            q += " AND screen IN (?, 'ambas')"
            p.append(screen)
        return [dict(r) for r in db.all(q + " ORDER BY sort_order, id", tuple(p))]

    @router.post("/api/ads")
    def create_ad(data: AdSchema, user: dict = Depends(require_manager)):
        nxt = db.one("SELECT COALESCE(MAX(sort_order), -1) + 1 n FROM ads")["n"]
        aid = db.insert("INSERT INTO ads (title, image_url, price_text, is_promo, duration, sort_order, active, screen, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (data.title, data.image_url, data.price_text, int(data.is_promo), data.duration, nxt,
                         int(data.active), data.screen, _now()))
        return {"status": "ok", "id": aid}

    @router.put("/api/ads/{ad_id}")
    def update_ad(ad_id: int, data: AdSchema, user: dict = Depends(require_manager)):
        if not db.one("SELECT id FROM ads WHERE id=?", (ad_id,)):
            raise HTTPException(status_code=404, detail="Anuncio no encontrado")
        db.execute("UPDATE ads SET title=?, image_url=?, price_text=?, is_promo=?, duration=?, active=?, screen=? WHERE id=?",
                   (data.title, data.image_url, data.price_text, int(data.is_promo), data.duration, int(data.active),
                    data.screen, ad_id))
        return {"status": "ok"}

    @router.delete("/api/ads/{ad_id}")
    def delete_ad(ad_id: int, user: dict = Depends(require_manager)):
        db.execute("DELETE FROM ads WHERE id=?", (ad_id,))
        return {"status": "ok"}

    @router.post("/api/ads/reorder")
    def reorder_ads(data: AdOrderSchema, user: dict = Depends(require_manager)):
        for i, aid in enumerate(data.ids):
            db.execute("UPDATE ads SET sort_order=? WHERE id=?", (i, aid))
        return {"status": "ok"}

    @router.post("/api/auth/verify_admin_pin")
    def verify_admin_pin(data: PinSchema, request: Request):
        user = _user_by_pin(data.pin, request)
        valid = bool(user and user["role"] == "admin")
        if user and not valid:
            register_fail(_ip(request))
        if valid:
            db.log(user["username"], "admin_pin_ok", "Autorización en caja")
        return {"valid": valid}

    @router.post("/api/delivery/order")
    async def public_delivery_order(data: PublicDeliveryOrder):
        method = data.payment_method.strip().lower()
        if method not in DELIVERY_PAYMENTS:
            raise HTTPException(status_code=400, detail="Método de pago no válido")
        products = {}
        for it in data.items:
            p = db.one("SELECT id, name, price_cop FROM products WHERE id=? AND active=1", (it.product_id,))
            if not p:
                raise HTTPException(status_code=400, detail=f"Producto {it.product_id} no disponible")
            products[it.product_id] = p
        # El valor del envío sale de la zona elegida (la caja puede ajustarlo después)
        zone = next((z for z in get_zones() if z["name"] == data.zone), None)
        fee = zone["fee"] if zone else 0
        notes = f"Pago al recibir: {method}"
        if data.reference:
            notes += f" · Indicaciones: {data.reference.strip()}"
        order_id = db.insert(
            "INSERT INTO orders (status, table_name, total_cop, is_delivery, customer_name, customer_phone, "
            "delivery_address, notes, created_at, delivery_fee_cop, delivery_zone) "
            "VALUES ('open', ?, 0, 1, ?, ?, ?, ?, ?, ?, ?)",
            (f"Domicilio - {data.name}", data.name, data.phone, data.address, notes, _now(), fee,
             zone["name"] if zone else None))
        total = 0
        for it in data.items:
            p = products[it.product_id]
            line = p["price_cop"] * it.qty
            total += line
            db.execute("INSERT INTO order_items (order_id, product_id, product_name, qty, price_cop, total_cop, status) "
                       "VALUES (?,?,?,?,?,?, 'pending')", (order_id, p["id"], p["name"], it.qty, p["price_cop"], line))
        db.execute("UPDATE orders SET total_cop=? WHERE id=?", (total, order_id))
        await broadcast_kitchen("update_kitchen")
        return {"status": "ok", "order_id": order_id, "total": total, "delivery_fee": fee,
                "total_con_envio": total + fee}

    @router.get("/api/orders/{order_id}")
    def get_order(order_id: int, user: dict = Depends(get_current_user)):
        o = db.one("SELECT * FROM orders WHERE id=?", (order_id,))
        if not o:
            raise HTTPException(status_code=404, detail="Orden no encontrada")
        res = dict(o)
        res["items"] = [dict(i) for i in db.all("SELECT * FROM order_items WHERE order_id=?", (order_id,))]
        return res

    @router.post("/api/production/start")
    def production_start(data: ProductionStart, request: Request):
        user = _user_by_pin(data.pin, request)
        if not user:
            raise HTTPException(status_code=401, detail="PIN inválido")
        if db.one("SELECT id FROM production_logs WHERE user_id=? AND status='in_progress'", (user["id"],)):
            raise HTTPException(status_code=400, detail="Ya tienes un proceso en curso; finalízalo primero")
        pid = db.insert("INSERT INTO production_logs (user_id, process_name, start_time, status) VALUES (?,?,?, 'in_progress')",
                        (user["id"], data.process_name, _now()))
        return {"status": "ok", "production_id": pid}

    @router.post("/api/production/end")
    def production_end(data: ProductionEnd, request: Request):
        user = _user_by_pin(data.pin, request)
        if not user:
            raise HTTPException(status_code=401, detail="PIN inválido")
        row = db.one("SELECT id FROM production_logs WHERE user_id=? AND status='in_progress' ORDER BY id DESC LIMIT 1",
                     (user["id"],))
        if not row:
            raise HTTPException(status_code=400, detail="No hay un proceso en curso")
        db.execute("UPDATE production_logs SET end_time=?, qty=?, status='done' WHERE id=?", (_now(), data.qty, row["id"]))
        return {"status": "ok"}

    return router
