import os
from datetime import datetime
from pathlib import Path
import os
import logging

logger = logging.getLogger(__name__)

try:
    import win32print
    import win32api
except ImportError:
    win32print = None
    win32api = None

def cop(val: float | int) -> str:
    """Formatea un número a moneda colombiana (COP)"""
    try:
        return f"${int(val):,}".replace(",", ".")
    except (ValueError, TypeError):
        return "$0"

def print_file_to_default_printer(filepath: str):
    """Envía un archivo a la impresora predeterminada en Windows."""
    if win32print and win32api:
        try:
            printer_name = win32print.GetDefaultPrinter()
            win32api.ShellExecute(0, "print", filepath, f'/d:"{printer_name}"', ".", 0)
        except Exception as e:
            logger.error(f"Error al imprimir el ticket en hardware: {e}")

def write_ticket(order_id: int, table_num: str, items: list, total: float, payment_method: str) -> None:
    """Simula la impresión de un ticket de compra guardándolo en un archivo."""
    os.makedirs('tickets', exist_ok=True)
    filename = f"tickets/ticket_{order_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("="*30 + "\n")
        f.write("       TAQUERÍA PRO       \n")
        f.write("="*30 + "\n")
        f.write(f"Orden: #{order_id}\n")
        f.write(f"Mesa: {table_num}\n")
        f.write(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
        f.write("-" * 30 + "\n")
        for item in items:
            f.write(f"{item['qty']}x {item['product_name'][:15].ljust(15)} {cop(item['total_cop']):>8}\n")
        f.write("-" * 30 + "\n")
        f.write(f"TOTAL:           {cop(total):>13}\n")
        f.write(f"Pago:            {payment_method.upper():>13}\n")
        f.write("="*30 + "\n")
        f.write("  ¡Gracias por su compra! \n")
        
    print_file_to_default_printer(os.path.abspath(filename))
