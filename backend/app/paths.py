from __future__ import annotations
import sys
from pathlib import Path

def base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

ROOT = base_dir()
DATA_DIR = ROOT / 'data'
QR_DIR = ROOT / 'qr_output'
QR_TABLES_DIR = QR_DIR / 'mesas'
QR_PROMOS_DIR = QR_DIR / 'promociones'
BACKUP_DIR = ROOT / 'backups'
TICKET_DIR = ROOT / 'tickets'
DB_PATH = DATA_DIR / 'taqueria.db'

def ensure_dirs() -> None:
    for p in [DATA_DIR, QR_DIR, QR_TABLES_DIR, QR_PROMOS_DIR, BACKUP_DIR, TICKET_DIR]:
        p.mkdir(parents=True, exist_ok=True)