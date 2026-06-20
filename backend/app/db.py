from __future__ import annotations
import os
import shutil
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

from app.paths import BACKUP_DIR, DB_PATH, ensure_dirs
from app.security import future_minutes, generate_code, hash_password

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

    def sales_summary_today(self) -> dict[str, Any]:
        today = date.today().isoformat()
        rows = self.all("SELECT payment_method, total_cop FROM orders WHERE status='closed' AND substr(closed_at,1,10)=?", (today,))
        items = self.all("SELECT product_name, SUM(qty) qty FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.status='closed' AND substr(o.closed_at,1,10)=? GROUP BY product_name ORDER BY qty DESC", (today,))
        total = sum(r['total_cop'] for r in rows)
        by_payment = {}
        for r in rows:
            m = r['payment_method'] or 'sin_definir'
            by_payment[m] = by_payment.get(m, 0) + r['total_cop']
        return {'total': total, 'orders': len(rows), 'by_payment': by_payment, 'items': items, 'low_stock': self.all('SELECT * FROM inventory_items WHERE stock_current <= stock_min')}

    def authenticate_user(self, username: str, password: str, verify_fn) -> tuple[bool, str, sqlite3.Row | None]:
        user = self.one('SELECT * FROM users WHERE username=? AND active=1', (username,))
        if not user: return False, 'Usuario no existe', None
        if not verify_fn(password, user['password_hash']): return False, 'Credenciales inválidas', None
        return True, 'OK', user

    def authenticate_pin(self, pin: str) -> tuple[bool, str, sqlite3.Row | None]:
        user = self.one("SELECT * FROM users WHERE role='cajero' AND pin=? AND active=1", (pin,))
        if not user: return False, 'PIN inválido', None
        return True, 'OK', user

db = DB(DB_PATH)