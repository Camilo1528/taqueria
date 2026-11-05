"""Turnos de caja, validación contable diaria y cierre de mes.

Modelo de efectivo de un turno:
    esperado = base + ventas en efectivo (sin lo pagado con bonos) + propinas y domicilios cobrados en efectivo
               + tarjetas de regalo vendidas en efectivo
               - propinas pagadas al personal - domicilios pagados a domiciliarios - egresos del turno
    diferencia (descuadre) = efectivo contado - esperado
"""
from __future__ import annotations

import calendar
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import db

TOLERANCIA_COP = 1.0  # diferencias menores se consideran cuadradas (redondeos)


def ensure_accounting_schema() -> None:
    with db.connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS cash_shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cashier_id INTEGER, opened_at TEXT, closed_at TEXT,
            base_cash REAL, expected_cash REAL, actual_cash REAL, tips_distributed REAL,
            payroll_distributed REAL, difference REAL, status TEXT DEFAULT 'closed')""")
        con.execute("""CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY, description TEXT, amount REAL, date TEXT, cashier_id INTEGER, shift_id INTEGER)""")
        con.execute("""CREATE TABLE IF NOT EXISTS accounting_closings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_type TEXT NOT NULL,          -- 'day' | 'month'
            period TEXT NOT NULL,               -- 'YYYY-MM-DD' | 'YYYY-MM'
            total_sales REAL, total_tips REAL, total_expenses REAL, difference REAL,
            notes TEXT, validated_by TEXT, validated_at TEXT,
            UNIQUE(period_type, period))""")
        con.commit()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _shift_cash(opened_at: str, closed_at: str) -> dict:
    """Movimientos de efectivo entre dos instantes."""
    q = "FROM orders WHERE status='closed' AND branch_id IS NULL AND closed_at >= ? AND closed_at <= ?"
    p = (opened_at, closed_at)
    # Lo que se pagó con bono no es efectivo: se descuenta primero de los productos y luego del domicilio
    cash_sales = db.one(f"SELECT COALESCE(SUM(total_cop - MIN(COALESCE(voucher_amount_cop,0), total_cop)),0) v {q} "
                        "AND payment_method='efectivo'", p)["v"]
    cash_tips = db.one(f"SELECT COALESCE(SUM(tip_amount_cop),0) v {q} AND payment_method='efectivo'", p)["v"]
    all_tips = db.one(f"SELECT COALESCE(SUM(tip_amount_cop),0) v {q}", p)["v"]
    # Domicilios: el cliente paga el envío y ese dinero se le entrega al domiciliario
    cash_fees = db.one(f"SELECT COALESCE(SUM(COALESCE(delivery_fee_cop,0) - MIN(COALESCE(delivery_fee_cop,0), "
                       f"MAX(0, COALESCE(voucher_amount_cop,0) - total_cop))),0) v {q} AND payment_method='efectivo'", p)["v"]
    from app.rewards import vouchers_sold_between
    gift_cash = vouchers_sold_between(opened_at, closed_at, "efectivo")
    all_fees = db.one(f"SELECT COALESCE(SUM(delivery_fee_cop),0) v {q}", p)["v"]
    expenses = db.one("SELECT COALESCE(SUM(amount),0) v FROM expenses WHERE date >= ? AND date <= ?", p)["v"]
    return {"total_cash_sales": cash_sales, "cash_tips": cash_tips, "total_tips": all_tips,
            "cash_delivery_fees": cash_fees, "total_delivery_fees": all_fees, "gift_cards_cash": gift_cash,
            "total_expenses": expenses, "total_payroll": 0}


def daily_report(day: str) -> dict:
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="Fecha inválida, usa AAAA-MM-DD")

    # Ventas por método: la parte pagada con bono se muestra aparte como "bono"
    by_method = {r["m"]: r["v"] for r in db.all(
        "SELECT COALESCE(payment_method,'sin_definir') m, "
        "SUM(total_cop - MIN(COALESCE(voucher_amount_cop,0), total_cop)) v FROM orders "
        "WHERE status='closed' AND branch_id IS NULL AND substr(closed_at,1,10)=? AND COALESCE(payment_method,'') != 'bono' GROUP BY m", (day,))}
    paid_voucher = db.one("SELECT COALESCE(SUM(MIN(COALESCE(voucher_amount_cop,0), total_cop)),0) v FROM orders "
                          "WHERE status='closed' AND branch_id IS NULL AND substr(closed_at,1,10)=?", (day,))["v"]
    if paid_voucher:
        by_method["bono"] = paid_voucher
    tips = db.one("SELECT COALESCE(SUM(tip_amount_cop),0) v, COUNT(*) n FROM orders "
                  "WHERE status='closed' AND branch_id IS NULL AND substr(closed_at,1,10)=?", (day,))
    expenses = db.one("SELECT COALESCE(SUM(amount),0) v FROM expenses WHERE substr(date,1,10)=?", (day,))["v"]
    drivers = [dict(r) for r in db.all(
        "SELECT COALESCE(u.username, 'Sin asignar') driver, COUNT(*) deliveries, SUM(o.delivery_fee_cop) fees "
        "FROM orders o LEFT JOIN users u ON u.id=o.driver_id "
        "WHERE o.status='closed' AND o.branch_id IS NULL AND substr(o.closed_at,1,10)=? AND o.delivery_fee_cop > 0 "
        "GROUP BY driver ORDER BY driver", (day,))]
    shifts = [dict(s) for s in db.all(
        "SELECT s.*, u.username cashier FROM cash_shifts s LEFT JOIN users u ON u.id=s.cashier_id "
        "WHERE substr(s.opened_at,1,10)=? ORDER BY s.opened_at", (day,))]
    open_orders = db.one("SELECT COUNT(*) n FROM orders WHERE status='open' AND substr(created_at,1,10)=?", (day,))["n"]

    difference = sum((s["difference"] or 0) for s in shifts if s["status"] == "closed")
    alerts = []
    for s in shifts:
        if s["status"] == "closed" and abs(s["difference"] or 0) > TOLERANCIA_COP:
            tipo = "sobrante" if s["difference"] > 0 else "faltante"
            monto = f"{abs(s['difference']):,.0f}".replace(",", ".")
            alerts.append(f"Turno #{s['id']} ({s['cashier'] or 'sin cajero'}): {tipo} de ${monto}")
    if any(s["status"] == "open" for s in shifts):
        alerts.append("Hay turnos de caja sin cerrar")
    if open_orders:
        alerts.append(f"{open_orders} órdenes del día siguen abiertas")
    if by_method.get("efectivo") and not shifts:
        alerts.append("Hubo ventas en efectivo pero no se abrió turno de caja (no se puede cuadrar)")

    closing = db.one("SELECT * FROM accounting_closings WHERE period_type='day' AND period=?", (day,))
    return {
        "date": day,
        "total_sales": sum(by_method.values()),
        "sales_by_method": by_method,
        "orders": tips["n"],
        "total_tips": tips["v"],
        "total_delivery_fees": sum(d["fees"] or 0 for d in drivers),
        "delivery_by_driver": drivers,
        **__import__("app.rewards", fromlist=["rewards_day_summary"]).rewards_day_summary(day),
        "total_expenses": expenses,
        "shifts": shifts,
        "difference": difference,
        "balanced": abs(difference) <= TOLERANCIA_COP and not alerts,
        "alerts": alerts,
        "validated": dict(closing) if closing else None,
    }


def monthly_report(month: str) -> dict:
    try:
        y, m = (int(x) for x in month.split("-"))
        last = calendar.monthrange(y, m)[1]
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Mes inválido, usa AAAA-MM")

    days = []
    for d in range(1, last + 1):
        day = f"{y:04d}-{m:02d}-{d:02d}"
        r = daily_report(day)
        if r["orders"] or r["shifts"] or r["total_expenses"]:
            days.append({k: r[k] for k in ("date", "total_sales", "total_tips", "total_expenses",
                                           "difference", "balanced", "alerts")}
                        | {"validated": bool(r["validated"])})

    pending = [d["date"] for d in days if not d["validated"]]
    closing = db.one("SELECT * FROM accounting_closings WHERE period_type='month' AND period=?", (month,))
    return {
        "month": month,
        "days": days,
        "total_sales": sum(d["total_sales"] for d in days),
        "total_tips": sum(d["total_tips"] for d in days),
        "total_expenses": sum(d["total_expenses"] for d in days),
        "difference": sum(d["difference"] for d in days),
        "days_with_difference": [d["date"] for d in days if abs(d["difference"]) > TOLERANCIA_COP],
        "pending_days": pending,
        "can_close": bool(days) and not pending and not closing,
        "closed": dict(closing) if closing else None,
    }


class OpenShift(BaseModel):
    base_cash: float


class CloseShift(BaseModel):
    actual_cash: float


class ValidateSchema(BaseModel):
    notes: str = ""


class ExpenseSchema(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0)


def build_router(get_current_user, require_manager) -> APIRouter:
    router = APIRouter()

    # ---------- Turnos de caja (usados por cashier.html) ----------
    def _open_shift(user_id):
        return db.one("SELECT * FROM cash_shifts WHERE status='open' AND cashier_id=? ORDER BY id DESC LIMIT 1", (user_id,))

    @router.get("/api/shift/status")
    def shift_status(user: dict = Depends(get_current_user)):
        s = _open_shift(user.get("id"))
        return {"status": "open", **dict(s)} if s else {"status": "closed"}

    @router.post("/api/shift/open")
    def shift_open(data: OpenShift, user: dict = Depends(get_current_user)):
        if data.base_cash < 0:
            raise HTTPException(status_code=400, detail="La base no puede ser negativa")
        if _open_shift(user.get("id")):
            raise HTTPException(status_code=400, detail="Ya tienes un turno abierto")
        sid = db.insert("INSERT INTO cash_shifts (cashier_id, opened_at, base_cash, status) VALUES (?,?,?, 'open')",
                        (user.get("id"), _now(), data.base_cash))
        db.log(user.get("sub"), "shift_open", f"turno {sid} base {data.base_cash}")
        return {"status": "ok", "shift_id": sid}

    @router.post("/api/shift/close")
    def shift_close(data: CloseShift, user: dict = Depends(get_current_user)):
        s = _open_shift(user.get("id"))
        if not s:
            raise HTTPException(status_code=400, detail="No tienes un turno abierto")
        closed_at = _now()
        mv = _shift_cash(s["opened_at"], closed_at)
        expected = ((s["base_cash"] or 0) + mv["total_cash_sales"] + mv["cash_tips"] + mv["cash_delivery_fees"]
                    + mv["gift_cards_cash"]
                    - mv["total_tips"] - mv["total_delivery_fees"] - mv["total_expenses"])
        diff = data.actual_cash - expected
        db.execute("UPDATE cash_shifts SET closed_at=?, expected_cash=?, actual_cash=?, tips_distributed=?, "
                   "payroll_distributed=0, difference=?, status='closed' WHERE id=?",
                   (closed_at, expected, data.actual_cash, mv["total_tips"], diff, s["id"]))
        db.log(user.get("sub"), "shift_close", f"turno {s['id']} diferencia {diff}")
        return {"status": "ok", "shift_id": s["id"], "base_cash": s["base_cash"], **mv,
                "expected_cash": expected, "actual_cash": data.actual_cash, "difference": diff}

    # ---------- Gastos / salidas de caja (cashier.html) ----------
    @router.post("/api/expenses")
    def create_expense(data: ExpenseSchema, user: dict = Depends(get_current_user)):
        s = _open_shift(user.get("id"))
        if not s:
            raise HTTPException(status_code=400, detail="Abre un turno de caja antes de registrar gastos")
        eid = db.insert("INSERT INTO expenses (description, amount, date, cashier_id, shift_id) VALUES (?,?,?,?,?)",
                        (data.description.strip(), data.amount, _now(), user.get("id"), s["id"]))
        db.log(user.get("sub"), "expense", f"{data.description} ${data.amount}")
        return {"status": "ok", "expense_id": eid}

    @router.get("/api/expenses")
    def list_expenses(day: str | None = None, user: dict = Depends(require_manager)):
        day = day or date.today().isoformat()
        return [dict(r) for r in db.all(
            "SELECT e.*, u.username cashier FROM expenses e LEFT JOIN users u ON u.id=e.cashier_id "
            "WHERE substr(e.date,1,10)=? ORDER BY e.date", (day,))]

    # ---------- Contabilidad ----------
    @router.get("/api/accounting/daily")
    def get_daily(day: str | None = None, user: dict = Depends(require_manager)):
        return daily_report(day or date.today().isoformat())

    @router.post("/api/accounting/daily/{day}/validate")
    def validate_day(day: str, data: ValidateSchema, user: dict = Depends(require_manager)):
        r = daily_report(day)
        if r["validated"]:
            raise HTTPException(status_code=400, detail="Este día ya fue validado")
        if any(s["status"] == "open" for s in r["shifts"]):
            raise HTTPException(status_code=400, detail="Cierra todos los turnos de caja antes de validar el día")
        if not r["balanced"] and not data.notes.strip():
            raise HTTPException(status_code=400, detail="Hay descuadres: escribe una observación para validar el día")
        db.execute("INSERT INTO accounting_closings (period_type, period, total_sales, total_tips, total_expenses, "
                   "difference, notes, validated_by, validated_at) VALUES ('day',?,?,?,?,?,?,?,?)",
                   (day, r["total_sales"], r["total_tips"], r["total_expenses"], r["difference"],
                    data.notes, user.get("sub"), _now()))
        db.log(user.get("sub"), "day_validated", day)
        return daily_report(day)

    @router.get("/api/accounting/monthly")
    def get_monthly(month: str | None = None, user: dict = Depends(require_manager)):
        return monthly_report(month or date.today().strftime("%Y-%m"))

    @router.post("/api/accounting/monthly/{month}/close")
    def close_month(month: str, data: ValidateSchema, user: dict = Depends(require_manager)):
        r = monthly_report(month)
        if r["closed"]:
            raise HTTPException(status_code=400, detail="Este mes ya está cerrado")
        if r["pending_days"]:
            raise HTTPException(status_code=400, detail="Faltan días por validar: " + ", ".join(r["pending_days"]))
        if not r["days"]:
            raise HTTPException(status_code=400, detail="No hay movimientos en este mes")
        db.execute("INSERT INTO accounting_closings (period_type, period, total_sales, total_tips, total_expenses, "
                   "difference, notes, validated_by, validated_at) VALUES ('month',?,?,?,?,?,?,?,?)",
                   (month, r["total_sales"], r["total_tips"], r["total_expenses"], r["difference"],
                    data.notes, user.get("sub"), _now()))
        db.log(user.get("sub"), "month_closed", month)
        return monthly_report(month)

    return router
