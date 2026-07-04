import os

with open('api.py', 'r', encoding='utf-8') as f:
    content = f.read()

imports = '''import os
from fastapi import FastAPI, HTTPException, Security, Depends, WebSocket, WebSocketDisconnect
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from app.db import db
import uvicorn
from dotenv import load_dotenv
import threading
import schedule
import time
import zipfile
import shutil
import datetime
import logging
import requests

logging.basicConfig(filename='taqueria_server.log', level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("API")

load_dotenv()

# Inicialización de la API
app = FastAPI(title="Taquería Pro API")

# Ciberseguridad: Cargar clave desde .env y limitar CORS
API_KEY = os.getenv("API_KEY", "123456")
api_key_header = APIKeyHeader(name="x-api-key")

'''

with open('api.py', 'w', encoding='utf-8') as f:
    f.write(imports + content)
