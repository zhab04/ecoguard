"""EcoGuard · servidor central (Flask + Socket.IO) para Render.com."""
import os
import hmac
import time
import sqlite3
import threading
import collections
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import eventlet
eventlet.monkey_patch()

from flask import Flask, Response, jsonify, request, send_file, send_from_directory, abort
from flask_socketio import SocketIO, join_room
import requests as http

# ---------------------------------------------------------------------------
# Configuración (variables de entorno en Render)
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "ecoguard.db")
REC_DIR = os.path.join(DATA_DIR, "grabaciones")
os.makedirs(REC_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

ZONA = ZoneInfo(os.environ.get("TZ_NAME", "America/Mexico_City"))
NTFY_URL = os.environ.get("NTFY_URL", "").strip()
MAX_GRABACIONES = int(os.environ.get("MAX_GRABACIONES_POR_CAMARA", "15"))
ACTIVO_SEG = 5.0
LAT_DEF, LON_DEF = 19.2780, -99.0080

def parsear_camaras(raw):
    cams = {}
    for item in raw.split(","):
        if ":" in item:
            cid, pin = item.split(":", 1)
            cams[cid.strip()] = pin.strip()
    return cams

CAMERAS = parsear_camaras(os.environ.get("CAMERAS", "123:SEC-99,CAM-101:SEC-99,CAM-102:SEC-99"))

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cambia-esto")
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet",
    max_http_buffer_size=16 * 1024 * 1024,
    ping_timeout=30,
)

# ---------------------------------------------------------------------------
# Estado en memoria
# ---------------------------------------------------------------------------
condicion = threading.Condition()
frames = {}
last_seen = {}
fps_stats = {}
telemetry = {}
audio_estado = {}
ultimo_evento = {}

# ---------------------------------------------------------------------------
# Base de datos (SQLite)
# ---------------------------------------------------------------------------
ESQUEMA = """
CREATE TABLE IF NOT EXISTS nodos (
    cam_id TEXT PRIMARY KEY,
    lat REAL, lon REAL, actualizado TEXT
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cam_id TEXT NOT NULL,
    tipo TEXT NOT NULL,
    razon TEXT NOT NULL,
    valor REAL,
    lat REAL, lon REAL,
    fecha TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eventos_cam ON eventos(cam_id, fecha);
CREATE TABLE IF NOT EXISTS grabaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cam_id TEXT NOT NULL,
    archivo TEXT NOT NULL,
    inicio TEXT,
    duracion REAL,
    bytes INTEGER
);
"""
_db_lock = threading.Lock()
_conn = None

def run_db(sql, params=(), fetch=False):
    global _conn
    with _db_lock:
        if _conn is None:
            os.makedirs(DATA_DIR, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(ESQUEMA)
        cur = _conn.execute(sql, params)
        _conn.commit()
        if fetch:
            return [dict(r) for r in cur.fetchall()]
        return cur.lastrowid

def ahora_iso():
    return datetime.now(ZONA).isoformat(timespec="seconds")

def autorizado(cam, token):
    esperado = CAMERAS.get(cam)
    if esperado is None or token is None:
        return False
    return hmac.compare_digest(esperado.encode(), str(token).encode())

def puede_registrar(cam, tipo, cooldown):
    clave = (cam, tipo)
    t = time.time()
    if t - ultimo_evento.get(clave, 0) < cooldown:
        return False
    ultimo_evento[clave] = t
    return True

def ubicacion(cam):
    t = telemetry.get(cam, {})
    if t.get("lat") is not None:
        return t["lat"], t["lon"]
    fila = run_db("SELECT lat, lon FROM nodos WHERE cam_id=?", (cam,), True)
    if fila and fila[0]["lat"] is not None:
        return fila[0]["lat"], fila[0]["lon"]
    return LAT_DEF, LON_DEF

def guardar_ubicacion(cam, lat, lon):
    run_db(
        "INSERT INTO nodos (cam_id, lat, lon, actualizado) VALUES (?,