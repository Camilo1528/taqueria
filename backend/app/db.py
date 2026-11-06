from __future__ import annotations
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

from app.paths import DB_PATH, ensure_dirs

load_dotenv()
ensure_dirs()

class DB:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA journal_mode=WAL')
        return conn

    def close_order_with_inventory(self, order_id: int, method: str) -> tuple[bool, str]:
        """Procesa stock y pago en una transacción atómica para evitar descuadres."""
        with self.connect() as con:
            con.execute("BEGIN TRANSACTION")
            try:
                # 0. Solo se cobran órdenes abiertas (evita doble cobro y doble descuento de inventario)
                order = con.execute('SELECT status FROM orders WHERE id=?', (order_id,)).fetchone()
                if not order:
                    con.rollback()
                    return False, "La orden no existe"
                if order['status'] != 'open':
                    con.rollback()
                    return False, "La orden ya fue cerrada"
                # 1. Descontar Inventario según la Receta
                items = con.execute('SELECT product_id, qty FROM order_items WHERE order_id=?', (order_id,)).fetchall()
                for item in items:
                    recipe = con.execute('SELECT inventory_item_id, qty_needed FROM recipe_items WHERE product_id=?', (item['product_id'],)).fetchall()
                    for r in recipe:
                        con.execute('UPDATE inventory_items SET stock_current = stock_current - ? WHERE id = ?', 
                                   (r['qty_needed'] * item['qty'], r['inventory_item_id']))
                
                # 2. Registrar el pago y cerrar la orden
                con.execute("UPDATE orders SET status='closed', closed_at=?, payment_method=? WHERE id=?", 
                           (datetime.now().isoformat(timespec='seconds'), method, order_id))
                
                # 3. Liberar la mesa
                con.execute("UPDATE tables SET is_open=0, current_order_id=NULL WHERE current_order_id=?", (order_id,))
                
                con.commit()
                return True, "Venta procesada con éxito"
            except Exception as e:
                con.rollback()
                return False, f"Error de Inventario: {str(e)}"

    def log(self, username: str | None, action: str, details: str = '') -> None:
        with self.connect() as con:
            con.execute('INSERT INTO audit_log (username,action,details) VALUES (?,?,?)', (username, action, details))
            con.commit()

    def all(self, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(query, params).fetchall()

    def one(self, query: str, params: tuple = ()) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(query, params).fetchone()

    def execute(self, query: str, params: tuple = ()) -> None:
        with self.connect() as con:
            con.execute(query, params)
            con.commit()

    def insert(self, query: str, params: tuple = ()) -> int:
        with self.connect() as con:
            cur = con.execute(query, params)
            con.commit()
            return cur.lastrowid

    def sales_summary_today(self) -> dict[str, Any]:
        today = date.today().isoformat()
        rows = self.all("SELECT payment_method, total_cop FROM orders WHERE status='closed' AND branch_id IS NULL AND substr(closed_at,1,10)=?", (today,))
        items = self.all("SELECT product_name, SUM(qty) qty FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.status='closed' AND o.branch_id IS NULL AND substr(o.closed_at,1,10)=? GROUP BY product_name ORDER BY qty DESC", (today,))
        total = sum(r['total_cop'] for r in rows)
        by_payment = {}
        for r in rows:
            m = r['payment_method'] or 'sin_definir'
            by_payment[m] = by_payment.get(m, 0) + r['total_cop']
        
        att = self.all("SELECT u.username, u.role, a.log_type, a.timestamp FROM attendance_logs a JOIN users u ON u.id = a.user_id WHERE substr(a.timestamp,1,10)=? ORDER BY a.timestamp DESC", (today,))
        
        expenses = self.all("SELECT SUM(amount) as t FROM expenses WHERE substr(date,1,10)=?", (today,))
        total_expenses = expenses[0]['t'] or 0.0

        return {'total': total, 'orders': len(rows), 'by_payment': by_payment, 'items': items, 'low_stock': self.all('SELECT * FROM inventory_items WHERE stock_current <= stock_min AND COALESCE(active,1)=1'), 'attendance': [dict(a) for a in att], 'total_expenses': total_expenses}

    def authenticate_user(self, username: str, password: str, verify_fn) -> tuple[bool, str, sqlite3.Row | None]:
        user = self.one('SELECT * FROM users WHERE username=? AND active=1', (username,))
        if not user: return False, 'Usuario no existe', None
        if not verify_fn(password, user['password_hash']): return False, 'Credenciales inválidas', None
        return True, 'OK', user

    def authenticate_pin(self, pin: str) -> tuple[bool, str, sqlite3.Row | None]:
        user = self.one("SELECT * FROM users WHERE pin=? AND active=1", (pin,))
        if not user: return False, 'PIN inválido', None
        return True, 'OK', user

    def ensure_schema(self) -> None:
        """Crea las tablas base (instalación nueva) y agrega columnas que bases antiguas no tienen."""
        with self.connect() as con:
            con.executescript(BASE_SCHEMA)
            con.commit()
        self._ensure_first_admin()
        wanted = {
            'products': [('image_url', 'TEXT'), ('is_reward', 'INTEGER DEFAULT 0')],
            'orders': [('is_delivery', 'INTEGER DEFAULT 0'), ('customer_name', 'TEXT'),
                       ('delivery_fee_cop', 'REAL DEFAULT 0'), ('delivery_zone', 'TEXT'),
                       ('customer_phone', 'TEXT'), ('delivery_address', 'TEXT'), ('notes', 'TEXT')],
            'users': [('birth_date', 'TEXT')],
            'vouchers': [('balance_cop', 'REAL DEFAULT 0')],
            'inventory_items': [('stock_max', 'REAL DEFAULT 0'), ('unit', "TEXT DEFAULT 'und'"), ('active', 'INTEGER DEFAULT 1')],
        }
        with self.connect() as con:
            con.execute('CREATE TABLE IF NOT EXISTS loyalty_customers (cedula TEXT PRIMARY KEY, name TEXT, points INTEGER DEFAULT 0)')
            for table, cols in wanted.items():
                existing = {r['name'] for r in con.execute(f'PRAGMA table_info({table})')}
                if not existing:
                    continue  # la tabla no existe en esta base
                for name, decl in cols:
                    if name not in existing:
                        con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')
                        if table == 'vouchers' and name == 'balance_cop':
                            con.execute('UPDATE vouchers SET balance_cop = value_cop WHERE is_redeemed = 0')
            con.commit()

    def _ensure_first_admin(self) -> None:
        """Instalación nueva: crea un administrador para poder entrar. El PIN sale de ADMIN_PIN
        o se genera al azar y se deja en data/primer_acceso.txt (bórralo después de entrar)."""
        if self.one("SELECT id FROM users WHERE active=1 AND role='admin' LIMIT 1"):
            return
        if self.one("SELECT id FROM users LIMIT 1"):
            return  # ya hay usuarios: no tocar una base existente
        import os
        import secrets
        pin = os.getenv("ADMIN_PIN") or "".join(secrets.choice("0123456789") for _ in range(6))
        self.execute("INSERT INTO users (username, password_hash, role, pin, active, first_name) VALUES ('admin', '', 'admin', ?, 1, 'Administrador')",
                     (pin,))
        if not os.getenv("ADMIN_PIN"):
            (DB_PATH.parent / "primer_acceso.txt").write_text(
                f"Primer acceso a Taquería Pro\nUsuario: admin\nPIN: {pin}\n\nCambia este PIN en Empleados y borra este archivo.\n",
                encoding="utf-8")


# Tablas base de una instalación nueva (el esquema de las bases existentes no cambia).
BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, role TEXT, pin TEXT, active INTEGER,
    first_name TEXT, last_name TEXT, cedula TEXT, phone TEXT, daily_wage REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, price_cop REAL, category_id INTEGER, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS tables (id INTEGER PRIMARY KEY, name TEXT, is_open INTEGER DEFAULT 0, current_order_id INTEGER);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT, closed_at TEXT, payment_method TEXT, total_cop REAL,
    table_name TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, tip_amount_cop REAL DEFAULT 0, kitchen_status TEXT DEFAULT 'pending',
    driver_id INTEGER DEFAULT NULL);
CREATE TABLE IF NOT EXISTS order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, product_id INTEGER, product_name TEXT,
    qty INTEGER, price_cop REAL, total_cop REAL, notes TEXT DEFAULT '', status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS inventory_items (id INTEGER PRIMARY KEY, name TEXT, stock_current REAL, stock_min REAL, inventory_type TEXT);
CREATE TABLE IF NOT EXISTS recipe_items (product_id INTEGER, inventory_item_id INTEGER, qty_needed REAL);
CREATE TABLE IF NOT EXISTS waste_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, inventory_item_id INTEGER, qty REAL, reason TEXT,
    date TEXT DEFAULT CURRENT_TIMESTAMP, user_id INTEGER);
CREATE TABLE IF NOT EXISTS attendance_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, log_type TEXT, timestamp TEXT);
CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, details TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS vouchers (id TEXT PRIMARY KEY, type TEXT, value_cop INTEGER, items_json TEXT, identifier TEXT,
    is_redeemed INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, res_date TEXT NOT NULL,
    res_time TEXT NOT NULL, guests INTEGER NOT NULL, status TEXT DEFAULT 'pending');
CREATE INDEX IF NOT EXISTS ix_orders_status_closed ON orders(status, closed_at);
CREATE INDEX IF NOT EXISTS ix_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS ix_recipe_product ON recipe_items(product_id);
"""

db = DB(DB_PATH)
db.ensure_schema()