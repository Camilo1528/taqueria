"""Integraciones reales: configuración, DIAN (interruptor), sincronización entre sedes y pagos Wompi.

Las llaves secretas se guardan en data/integrations.json (nunca en branding.json, que es público).

Sincronización (sucursal -> servidor maestro):
  - La sucursal envía sus órdenes cerradas que aún no se han enviado (orders.synced_at IS NULL),
    con la API key del maestro en el encabezado x-api-key.
  - El maestro las guarda con branch_id + remote_id (sin chocar con sus propios números de orden)
    y responde qué órdenes quedaron guardadas; solo esas se marcan como sincronizadas.
  - Las órdenes recibidas de sucursales NO entran a la caja ni a la contabilidad diaria del maestro;
    se ven en el reporte de sucursales.

Pagos Wompi (https://docs.wompi.co):
  - Checkout web: https://checkout.wompi.co/p/ con firma de integridad
    SHA256(referencia + monto_en_centavos + moneda + secreto_integridad).
  - Webhook de eventos: se verifica el checksum SHA256(valores de signature.properties + timestamp + secreto_eventos).
    Solo una transacción APPROVED, en COP y por el monto exacto cierra la orden con método "online".
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.db import db
from app.paths import DATA_DIR

logger = logging.getLogger("integrations")
CONFIG_PATH = DATA_DIR / "integrations.json"
SECRET_FIELDS = {"master_api_key", "wompi_integrity_secret", "wompi_events_secret", "dian_api_key"}

DEFAULTS = {
    "dian_enabled": False,
    "dian_provider": "",
    "dian_api_key": "",
    "master_server_url": "",
    "master_api_key": "",
    "sync_enabled": False,
    "wompi_enabled": False,
    "wompi_environment": "production",  # production | sandbox
    "wompi_public_key": "",
    "wompi_integrity_secret": "",
    "wompi_events_secret": "",
    "public_base_url": "",  # dirección pública del sistema, para volver después de pagar
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------- Configuración ----------------
def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def masked_config() -> dict:
    cfg = load_config()
    out = {}
    for k, v in cfg.items():
        if k in SECRET_FIELDS:
            out[k] = ""
            out[k + "_set"] = bool(v)
        else:
            out[k] = v
    return out


def public_flags() -> dict:
    """Lo que pueden saber las pantallas sin sesión (sin secretos)."""
    cfg = load_config()
    return {"dian_enabled": bool(cfg["dian_enabled"]),
            "online_payments": bool(cfg["wompi_enabled"] and cfg["wompi_public_key"] and cfg["wompi_integrity_secret"])}


def ensure_integrations_schema() -> None:
    with db.connect() as con:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(orders)")}
        for name, decl in (("synced_at", "TEXT"), ("branch_id", "TEXT"), ("remote_id", "INTEGER"),
                           ("payment_reference", "TEXT")):
            if name not in cols:
                con.execute(f"ALTER TABLE orders ADD COLUMN {name} {decl}")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_branch_remote ON orders(branch_id, remote_id)")
        con.execute("""CREATE TABLE IF NOT EXISTS online_payments (
            reference TEXT PRIMARY KEY, order_id INTEGER, amount_cents INTEGER, status TEXT,
            transaction_id TEXT, created_at TEXT, updated_at TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, sent INTEGER, accepted INTEGER, ok INTEGER, message TEXT)""")
        con.commit()


# ---------------- Sincronización ----------------
_sync_lock = threading.Lock()


def _branch_id() -> str:
    try:
        # utf-8-sig: tolera archivos guardados con BOM (p. ej. editados en el Bloc de notas)
        b = json.loads((Path(__file__).resolve().parent.parent / "branding.json").read_text(encoding="utf-8-sig"))
        return str(b.get("branch_id") or "SUC-01")
    except (OSError, ValueError):
        return "SUC-01"


def sync_now(batch: int = 200) -> dict:
    """Envía al maestro las órdenes cerradas propias que no se han enviado. Devuelve el resultado real."""
    cfg = load_config()
    url = (cfg["master_server_url"] or "").rstrip("/")
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "sent": 0, "accepted": 0, "message": "Falta la dirección del servidor maestro"}
    if not cfg["master_api_key"]:
        return {"ok": False, "sent": 0, "accepted": 0, "message": "Falta la API key del servidor maestro"}
    if not _sync_lock.acquire(blocking=False):
        return {"ok": False, "sent": 0, "accepted": 0, "message": "Ya hay una sincronización en curso"}
    total_sent = total_ok = 0
    try:
        while True:
            rows = db.all("SELECT * FROM orders WHERE status='closed' AND synced_at IS NULL AND branch_id IS NULL "
                          "ORDER BY id LIMIT ?", (batch,))
            if not rows:
                break
            payload = []
            for o in rows:
                d = dict(o)
                d["items"] = [dict(i) for i in db.all(
                    "SELECT product_id, product_name, qty, price_cop, total_cop, notes FROM order_items WHERE order_id=?",
                    (o["id"],))]
                payload.append(d)
            try:
                res = requests.post(f"{url}/api/sync_receive", json={"branch_id": _branch_id(), "orders": payload},
                                    headers={"x-api-key": cfg["master_api_key"]}, timeout=20)
            except requests.RequestException as e:
                msg = f"No hay conexión con el servidor maestro ({e.__class__.__name__})"
                _log_sync(total_sent, total_ok, False, msg)
                return {"ok": False, "sent": total_sent, "accepted": total_ok, "message": msg}
            if res.status_code != 200:
                try:
                    detalle = res.json().get("detail")
                except ValueError:
                    detalle = None
                msg = {401: "API key rechazada por el maestro", 403: "API key rechazada por el maestro"}.get(
                    res.status_code, f"El maestro rechazó el envío: {detalle}" if isinstance(detalle, str)
                    else f"El maestro respondió con error {res.status_code}")
                _log_sync(total_sent, total_ok, False, msg)
                return {"ok": False, "sent": total_sent, "accepted": total_ok, "message": msg}
            accepted = set(res.json().get("accepted", []))
            total_sent += len(rows)
            now = _now()
            for oid in accepted:
                db.execute("UPDATE orders SET synced_at=? WHERE id=?", (now, oid))
            total_ok += len(accepted)
            if len(accepted) < len(rows):  # algo no se aceptó: no insistir en bucle
                break
        msg = f"{total_ok} órdenes enviadas al servidor maestro" if total_ok else "Todo estaba al día"
        _log_sync(total_sent, total_ok, True, msg)
        return {"ok": True, "sent": total_sent, "accepted": total_ok, "message": msg}
    finally:
        _sync_lock.release()


def _log_sync(sent, accepted, ok, message):
    db.execute("INSERT INTO sync_log (at, sent, accepted, ok, message) VALUES (?,?,?,?,?)",
               (_now(), sent, accepted, int(ok), message))


def receive_orders(branch_id: str, orders: list) -> dict:
    """Lado MAESTRO: guarda órdenes de una sucursal sin chocar con las propias."""
    branch_id = (branch_id or "").strip()[:40]
    if not branch_id:
        raise HTTPException(status_code=400, detail="Falta branch_id")
    if branch_id == _branch_id():
        raise HTTPException(status_code=400, detail="El branch_id de la sucursal es igual al del maestro")
    accepted = []
    for o in orders[:500]:
        try:
            rid = int(o["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if db.one("SELECT id FROM orders WHERE branch_id=? AND remote_id=?", (branch_id, rid)):
            accepted.append(rid)  # ya estaba: se confirma para que la sucursal no la reenvíe
            continue
        with db.connect() as con:
            try:
                cur = con.execute(
                    "INSERT INTO orders (status, table_name, total_cop, payment_method, created_at, closed_at, tip_amount_cop, "
                    "delivery_fee_cop, voucher_amount_cop, branch_id, remote_id, synced_at) VALUES ('closed',?,?,?,?,?,?,?,?,?,?,?)",
                    (str(o.get("table_name") or "")[:80], float(o.get("total_cop") or 0), str(o.get("payment_method") or "")[:20],
                     o.get("created_at"), o.get("closed_at"), float(o.get("tip_amount_cop") or 0),
                     float(o.get("delivery_fee_cop") or 0), float(o.get("voucher_amount_cop") or 0), branch_id, rid, _now()))
                new_id = cur.lastrowid
                for it in (o.get("items") or [])[:200]:
                    con.execute("INSERT INTO order_items (order_id, product_id, product_name, qty, price_cop, total_cop, notes, status) "
                                "VALUES (?,?,?,?,?,?,?, 'ready')",
                                (new_id, it.get("product_id"), str(it.get("product_name") or "")[:120], float(it.get("qty") or 0),
                                 float(it.get("price_cop") or 0), float(it.get("total_cop") or 0), str(it.get("notes") or "")[:300]))
                con.commit()
                accepted.append(rid)
            except Exception as e:  # una orden mala no debe tumbar el lote
                con.rollback()
                logger.warning(f"Orden {rid} de {branch_id} rechazada: {e}")
    return {"status": "ok", "accepted": accepted}


def sync_worker():
    """Hilo: sincroniza cada 5 minutos si está activado."""
    while True:
        try:
            cfg = load_config()
            if cfg["sync_enabled"]:
                r = sync_now()
                if not r["ok"]:
                    logger.warning("Sync: " + r["message"])
        except Exception as e:
            logger.warning(f"Sync falló: {e}")
        time.sleep(300)


def branches_summary(day: str) -> list:
    return [dict(r) for r in db.all(
        "SELECT branch_id, COUNT(*) orders, COALESCE(SUM(total_cop),0) sales, COALESCE(SUM(tip_amount_cop),0) tips, "
        "MAX(synced_at) last_sync FROM orders WHERE branch_id IS NOT NULL AND substr(closed_at,1,10)=? "
        "GROUP BY branch_id ORDER BY branch_id", (day,))]


# ---------------- Wompi ----------------
def integrity_signature(reference: str, amount_cents: int, currency: str, secret: str) -> str:
    return hashlib.sha256(f"{reference}{amount_cents}{currency}{secret}".encode()).hexdigest()


def verify_event_checksum(event: dict, secret: str) -> bool:
    try:
        sig = event["signature"]
        data = event["data"]
        values = []
        for prop in sig["properties"]:  # p. ej. "transaction.id"
            cur = data
            for part in prop.split("."):
                cur = cur[part]
            values.append(str(cur))
        raw = "".join(values) + str(event["timestamp"]) + secret
        return hashlib.sha256(raw.encode()).hexdigest().lower() == str(sig["checksum"]).lower()
    except (KeyError, TypeError):
        return False


def order_due_cents(order) -> int:
    due = (order["total_cop"] or 0) + (order["delivery_fee_cop"] or 0) - (order["voucher_amount_cop"] or 0)
    return int(round(max(0, due) * 100))


# ---------------- Esquemas ----------------
class IntegrationsSchema(BaseModel):
    dian_enabled: bool = False
    dian_provider: str = Field(default="", max_length=60)
    dian_api_key: str | None = Field(default=None, max_length=300)
    master_server_url: str = Field(default="", max_length=200)
    master_api_key: str | None = Field(default=None, max_length=200)
    sync_enabled: bool = False
    wompi_enabled: bool = False
    wompi_environment: str = Field(default="production", pattern=r"^(production|sandbox)$")
    wompi_public_key: str = Field(default="", max_length=120)
    wompi_integrity_secret: str | None = Field(default=None, max_length=200)
    wompi_events_secret: str | None = Field(default=None, max_length=200)
    public_base_url: str = Field(default="", max_length=200)


class CheckoutSchema(BaseModel):
    order_id: int
    return_url: str | None = Field(default=None, max_length=300)


class SyncReceiveSchema(BaseModel):
    branch_id: str = Field(min_length=1, max_length=40)
    orders: list = Field(default_factory=list, max_length=500)


def build_router(get_current_user, require_admin, require_manager, get_api_key, close_order) -> APIRouter:
    router = APIRouter()

    # ----- Configuración (solo admin) -----
    @router.get("/api/integrations")
    def get_integrations(user: dict = Depends(require_admin)):
        cfg = masked_config()
        cfg["last_sync"] = (lambda r: dict(r) if r else None)(db.one("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1"))
        cfg["pending_sync"] = db.one("SELECT COUNT(*) n FROM orders WHERE status='closed' AND synced_at IS NULL AND branch_id IS NULL")["n"]
        return cfg

    @router.put("/api/integrations")
    def put_integrations(data: IntegrationsSchema, user: dict = Depends(require_admin)):
        cfg = load_config()
        new = data.model_dump()
        for k, v in new.items():
            if k in SECRET_FIELDS and not v:
                continue  # vacío = conservar el secreto guardado
            cfg[k] = v.strip() if isinstance(v, str) else v
        if cfg["master_server_url"] and not cfg["master_server_url"].startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="La dirección del maestro debe empezar por http:// o https://")
        if cfg["wompi_enabled"] and not (cfg["wompi_public_key"] and cfg["wompi_integrity_secret"] and cfg["wompi_events_secret"]):
            raise HTTPException(status_code=400, detail="Para activar Wompi se necesitan la llave pública, el secreto de integridad y el de eventos")
        if cfg["wompi_enabled"]:
            prefix = "pub_test_" if cfg["wompi_environment"] == "sandbox" else "pub_prod_"
            if not cfg["wompi_public_key"].startswith(prefix):
                raise HTTPException(status_code=400, detail=f"La llave pública de {cfg['wompi_environment']} debe empezar por {prefix}")
        save_config(cfg)
        db.log(user.get("sub"), "integrations_updated", ", ".join(sorted(k for k in new if k not in SECRET_FIELDS)))
        return masked_config()

    @router.get("/api/integrations/public")
    def get_public_flags():
        return public_flags()

    # ----- Sincronización -----
    @router.post("/api/sync/master")
    def sync_master_now(user: dict = Depends(require_admin)):
        r = sync_now()
        if not r["ok"]:
            raise HTTPException(status_code=502, detail=r["message"])
        return r

    @router.post("/api/sync_receive")
    def sync_receive(data: SyncReceiveSchema, api_key: str = Depends(get_api_key)):
        return receive_orders(data.branch_id, data.orders)

    @router.get("/api/branches/summary")
    def get_branches(day: str | None = None, user: dict = Depends(require_manager)):
        return branches_summary(day or date.today().isoformat())

    # ----- Pagos en línea (Wompi) -----
    @router.post("/api/payments/checkout")
    def create_checkout(data: CheckoutSchema, request: Request):
        cfg = load_config()
        if not public_flags()["online_payments"]:
            raise HTTPException(status_code=400, detail="El pago en línea no está activado")
        order = db.one("SELECT * FROM orders WHERE id=?", (data.order_id,))
        if not order or order["status"] != "open":
            raise HTTPException(status_code=404, detail="La orden no existe o ya fue pagada")
        cents = order_due_cents(order)
        if cents < 150000:  # Wompi exige un monto mínimo (~$1.500 COP)
            raise HTTPException(status_code=400, detail="El monto es muy bajo para pagar en línea")
        reference = f"TP-{order['id']}-{int(time.time())}"
        db.execute("INSERT INTO online_payments (reference, order_id, amount_cents, status, created_at, updated_at) "
                   "VALUES (?,?,?,'PENDING',?,?)", (reference, order["id"], cents, _now(), _now()))
        db.execute("UPDATE orders SET payment_reference=? WHERE id=?", (reference, order["id"]))
        base = (cfg["public_base_url"] or str(request.base_url)).rstrip("/")
        redirect = data.return_url if (data.return_url or "").startswith(base) else f"{base}/customer.html"
        params = {
            "public-key": cfg["wompi_public_key"],
            "currency": "COP",
            "amount-in-cents": cents,
            "reference": reference,
            "signature:integrity": integrity_signature(reference, cents, "COP", cfg["wompi_integrity_secret"]),
            "redirect-url": redirect,
        }
        return {"checkout_url": "https://checkout.wompi.co/p/?" + urlencode(params), "reference": reference,
                "amount": cents / 100}

    @router.post("/api/payments/wompi/webhook")
    async def wompi_webhook(request: Request):
        cfg = load_config()
        try:
            event = await request.json()
        except ValueError:
            raise HTTPException(status_code=400, detail="JSON inválido")
        if not cfg["wompi_events_secret"] or not verify_event_checksum(event, cfg["wompi_events_secret"]):
            logger.warning("Webhook Wompi con firma inválida")
            raise HTTPException(status_code=401, detail="Firma inválida")
        if event.get("event") != "transaction.updated":
            return {"status": "ignored"}
        tx = event["data"]["transaction"]
        pay = db.one("SELECT * FROM online_payments WHERE reference=?", (tx.get("reference"),))
        if not pay:
            return {"status": "unknown_reference"}
        status = str(tx.get("status"))
        db.execute("UPDATE online_payments SET status=?, transaction_id=?, updated_at=? WHERE reference=?",
                   (status, str(tx.get("id")), _now(), pay["reference"]))
        if status == "APPROVED":
            order = db.one("SELECT * FROM orders WHERE id=?", (pay["order_id"],))
            if (tx.get("currency") != "COP" or int(tx.get("amount_in_cents") or 0) != pay["amount_cents"]):
                logger.error(f"Pago {pay['reference']} con monto/moneda distintos; no se cierra la orden")
                return {"status": "amount_mismatch"}
            if order and order["status"] == "open":
                ok, msg = close_order(order["id"], "online")
                if not ok:
                    logger.error(f"No se pudo cerrar la orden {order['id']} pagada en línea: {msg}")
        return {"status": "ok"}

    @router.get("/api/payments/status/{order_id}")
    def payment_status(order_id: int):
        order = db.one("SELECT status, payment_method FROM orders WHERE id=?", (order_id,))
        if not order:
            raise HTTPException(status_code=404, detail="Orden no encontrada")
        pay = db.one("SELECT status FROM online_payments WHERE order_id=? ORDER BY created_at DESC LIMIT 1", (order_id,))
        return {"paid": order["status"] == "closed", "method": order["payment_method"],
                "online_status": pay["status"] if pay else None}

    return router
