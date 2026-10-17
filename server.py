"""EcoGuard · servidor central (Flask + Socket.IO) para Render.com."""
import os
import hmac
import hashlib
import secrets
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
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "ecoguard.db")
REC_DIR = os.path.join(DATA_DIR, "grabaciones")
os.makedirs(REC_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

ZONA = ZoneInfo(os.environ.get("TZ_NAME") or "America/Mexico_City")
NTFY_URL = (os.environ.get("NTFY_URL") or "").strip()
MAX_GRABACIONES = int(os.environ.get("MAX_GRABACIONES_POR_CAMARA") or "15")
ACTIVO_SEG = 5.0
LAT_DEF, LON_DEF = 19.4326, -99.1332

# Palabras cortas y fáciles de recordar para generar IDs y PIN
PALABRAS = [
    "sol", "luna", "mango", "tigre", "rio", "nube", "pino", "roca", "fresa", "monte",
    "perla", "faro", "lirio", "coral", "brisa", "cedro", "jaguar", "volcan", "ceiba", "aguila",
    "nopal", "maiz", "trueno", "olivo", "oso", "lobo", "gato", "perro", "pato", "cabra",
    "zorro", "conejo", "nido", "hoja", "flor", "piedra", "lago", "mar", "selva", "bosque",
    "cielo", "viento", "lluvia", "arena", "tuna", "chile", "cafe", "limon", "uva", "pera",
    "eco", "rayo", "astro", "cometa", "vela", "puma", "colibri", "delfin",
]

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "cambia-esto"
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
ZONAS = {}                 # (lat, lon) redondeados -> nombre de la zona
ZONAS_PENDIENTES = set()
ZONAS_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Base de datos (SQLite)
# ---------------------------------------------------------------------------
ESQUEMA = """
CREATE TABLE IF NOT EXISTS camaras (
    cam_id TEXT PRIMARY KEY,
    pin_hash TEXT NOT NULL,
    creada TEXT NOT NULL
);
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


def hash_pin(pin):
    return hmac.new(app.config["SECRET_KEY"].encode(), pin.encode(), hashlib.sha256).hexdigest()


def autorizado(cam, token):
    if not cam or not token:
        return False
    fila = run_db("SELECT pin_hash FROM camaras WHERE cam_id=?", (cam,), True)
    if not fila:
        return False
    return hmac.compare_digest(fila[0]["pin_hash"], hash_pin(str(token).strip().lower()))


def lista_camaras():
    return [f["cam_id"] for f in run_db("SELECT cam_id FROM camaras ORDER BY creada", (), True)]


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
    sql = ("INSERT INTO nodos (cam_id, lat, lon, actualizado) VALUES (?,?,?,?) "
           "ON CONFLICT(cam_id) DO UPDATE SET lat=excluded.lat, lon=excluded.lon, "
           "actualizado=excluded.actualizado")
    run_db(sql, (cam, lat, lon, ahora_iso()))


# ---------------------------------------------------------------------------
# Nombre de zona a partir de coordenadas (OpenStreetMap Nominatim)
# ---------------------------------------------------------------------------
def nombre_zona(lat, lon):
    """Devuelve el nombre de la zona. Si aún no existe, consulta en segundo plano."""
    clave = (round(lat, 3), round(lon, 3))
    if clave in ZONAS:
        return ZONAS[clave]
    with ZONAS_LOCK:
        if clave in ZONAS_PENDIENTES:
            return "Buscando zona…"
        ZONAS_PENDIENTES.add(clave)
    threading.Thread(target=_consultar_zona, args=(clave,), daemon=True).start()
    return "Buscando zona…"


def _consultar_zona(clave):
    lat, lon = clave
    try:
        r = http.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 14, "accept-language": "es"},
            headers={"User-Agent": "EcoGuard/1.0 (proyecto educativo)"},
            timeout=6,
        )
        if r.ok:
            datos = r.json()
            a = datos.get("address", {})
            claves = ("neighbourhood", "suburb", "city_district", "city", "town", "village", "municipality")
            partes = [a[k] for k in claves if a.get(k)]
            nombre = ", ".join(dict.fromkeys(partes[:3])) or datos.get("display_name", "Zona desconocida")
            ZONAS[clave] = nombre
    except Exception as e:
        print("Error consultando zona:", e)  # no se guarda: se reintenta en la siguiente consulta
    finally:
        with ZONAS_LOCK:
            ZONAS_PENDIENTES.discard(clave)


# ---------------------------------------------------------------------------
# Generación de ID y PIN memorables
# ---------------------------------------------------------------------------
def palabra():
    return secrets.choice(PALABRAS)


def generar_id():
    return f"cam-{palabra()}-{secrets.randbelow(90) + 10}"


def generar_pin():
    return f"{palabra()}-{palabra()}-{palabra()}-{secrets.randbelow(90) + 10}"


def enviar_push(titulo, texto):
    try:
        http.post(NTFY_URL, data=texto.encode("utf-8"),
                  headers={"Title": titulo, "Priority": "urgent", "Tags": "rotating_light"},
                  timeout=5)
    except Exception as e:
        print("Error enviando notificación:", e)


def registrar_evento(cam, tipo, razon, valor=None):
    lat, lon = ubicacion(cam)
    fecha = ahora_iso()
    sql = "INSERT INTO eventos (cam_id, tipo, razon, valor, lat, lon, fecha) VALUES (?,?,?,?,?,?,?)"
    eid = run_db(sql, (cam, tipo, razon, valor, lat, lon, fecha))
    alerta = {"id": eid, "cam_id": cam, "tipo": tipo, "razon": razon,
              "valor": valor, "lat": lat, "lon": lon, "fecha": fecha}
    socketio.emit("alerta", alerta)
    if tipo == "robo" and NTFY_URL:
        threading.Thread(target=enviar_push,
                         args=("ALERTA EcoGuard", f"Camara {cam}: {razon}. Hora: {fecha}"),
                         daemon=True).start()
    return alerta


def sala(cam):
    return f"cam_{cam}"


def contar_frame(cam):
    s = fps_stats.setdefault(cam, {"n": 0, "t0": time.time(), "fps": 0})
    s["n"] += 1
    ahora = time.time()
    if ahora - s["t0"] >= 1.0:
        s["fps"] = round(s["n"] / (ahora - s["t0"]), 1)
        s["n"], s["t0"] = 0, ahora


# ---------------------------------------------------------------------------
# Socket.IO
# ---------------------------------------------------------------------------
@socketio.on("registrar_camara")
def on_registrar(data):
    cam = str(data.get("cam_id", "")).strip()
    token = str(data.get("token_seguridad", ""))
    if autorizado(cam, token):
        join_room(sala(cam))
        socketio.emit("registro_ok", {"cam_id": cam}, to=request.sid)
        print(f"Cámara conectada: {cam}")
    else:
        socketio.emit("registro_error", {"motivo": "ID o PIN incorrecto"}, to=request.sid)


@socketio.on("video_frame")
def on_frame(data):
    cam = str(data.get("cam_id", ""))
    if not autorizado(cam, data.get("token")):
        return {"ok": False}
    cuadro = data.get("frame")
    if isinstance(cuadro, (bytes, bytearray)):
        with condicion:
            frames[cam] = bytes(cuadro)
            last_seen[cam] = time.time()
            condicion.notify_all()
        contar_frame(cam)
    return {"ok": True}


@socketio.on("audio_chunk")
def on_audio(data):
    cam = str(data.get("cam_id", ""))
    if not autorizado(cam, data.get("token")):
        return
    chunk = data.get("chunk")
    if not isinstance(chunk, (bytes, bytearray)):
        return
    with condicion:
        prev = audio_estado.get(cam, {})
        seq = prev.get("seq", 0) + 1
        if data.get("header") or not prev:
            audio_estado[cam] = {"header": bytes(chunk), "seq": seq,
                                 "chunks": collections.deque(maxlen=60), "ts": time.time()}
        else:
            prev["seq"] = seq
            prev["chunks"].append((seq, bytes(chunk)))
            prev["ts"] = time.time()
        condicion.notify_all()


@socketio.on("hablar_chunk")
def on_hablar(data):
    """Reenvía la voz del operador (dashboard) al teléfono de la cámara."""
    cam = str(data.get("cam_id", ""))
    if not autorizado(cam, data.get("token")):
        return
    chunk = data.get("chunk")
    if not isinstance(chunk, (bytes, bytearray)):
        return
    socketio.emit("audio_entrante", {"chunk": bytes(chunk), "sr": data.get("sr", 48000)},
                  to=sala(cam))


@socketio.on("recording_segment")
def on_segmento(data):
    cam = str(data.get("cam_id", ""))
    if not autorizado(cam, data.get("token")):
        return {"ok": False, "error": "No autorizado"}
    video = data.get("video")
    if not isinstance(video, (bytes, bytearray)):
        return {"ok": False, "error": "Datos inválidos"}
    carpeta = os.path.join(REC_DIR, cam)
    os.makedirs(carpeta, exist_ok=True)
    nombre = f"{cam}_{int(time.time())}.webm"
    ruta = os.path.join(carpeta, nombre)
    with open(ruta, "wb") as f:
        f.write(video)
    sql = "INSERT INTO grabaciones (cam_id, archivo, inicio, duracion, bytes) VALUES (?,?,?,?,?)"
    run_db(sql, (cam, f"{cam}/{nombre}", data.get("inicio"),
                 float(data.get("duracion") or 0), len(video)))
    podar_grabaciones(cam)
    return {"ok": True}


def podar_grabaciones(cam):
    sql = "SELECT id, archivo FROM grabaciones WHERE cam_id=? ORDER BY id DESC LIMIT -1 OFFSET ?"
    viejas = run_db(sql, (cam, MAX_GRABACIONES), True)
    for g in viejas:
        try:
            os.remove(os.path.join(REC_DIR, g["archivo"]))
        except OSError:
            pass
        run_db("DELETE FROM grabaciones WHERE id=?", (g["id"],))


@socketio.on("telemetria")
def on_telemetria(data):
    cam = str(data.get("cam_id", ""))
    if not autorizado(cam, data.get("token")):
        return
    previo = telemetry.get(cam, {})
    campos = ("lat", "lon", "precision", "velocidad", "rumbo", "bat", "cargando", "orient",
              "movimiento", "luz", "red", "audio_db", "grabando", "fps", "calidad")
    nuevo = {**previo, **{k: data.get(k) for k in campos}}
    telemetry[cam] = nuevo
    if nuevo.get("lat") is not None and nuevo.get("lon") is not None:
        guardar_ubicacion(cam, nuevo["lat"], nuevo["lon"])


@socketio.on("evento_sonido")
def on_sonido(data):
    cam = str(data.get("cam_id", ""))
    if not autorizado(cam, data.get("token")) or not puede_registrar(cam, "sonido", 8):
        return
    db = float(data.get("db", 0))
    base = data.get("linea_base")
    razon = f"Pico elevado de sonido ({db:.0f} dB"
    razon += f", base {base:.0f} dB)" if base is not None else ")"
    registrar_evento(cam, "sonido", razon, db)


@socketio.on("evento_movimiento")
def on_movimiento(data):
    cam = str(data.get("cam_id", ""))
    if not autorizado(cam, data.get("token")) or not puede_registrar(cam, "robo", 15):
        return
    mag = float(data.get("magnitud", 0))
    registrar_evento(cam, "robo",
                     f"Movimiento brusco del teléfono ({mag:.1f} m/s²): posible intento de robo",
                     mag)


# ---------------------------------------------------------------------------
# Streams HTTP
# ---------------------------------------------------------------------------
def generar_mjpeg(cam):
    ultimo = None
    while True:
        with condicion:
            condicion.wait(1.0)
            cuadro = frames.get(cam)
            vivo = time.time() - last_seen.get(cam, 0) < ACTIVO_SEG
        if cuadro is not None and cuadro is not ultimo:
            ultimo = cuadro
            yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                   + str(len(cuadro)).encode() + b"\r\n\r\n" + cuadro + b"\r\n")
        elif ultimo is not None and not vivo:
            break


def generar_audio(cam):
    with condicion:
        while not audio_estado.get(cam, {}).get("header"):
            condicion.wait(1.0)
        st = audio_estado[cam]
        ultimo = st["seq"]
        cabecera = st["header"]
    yield cabecera
    while True:
        with condicion:
            condicion.wait(1.0)
            st = audio_estado.get(cam)
            if not st or time.time() - st["ts"] > 10:
                break
            pendientes = [c for s, c in st["chunks"] if s > ultimo]
            if pendientes:
                ultimo = st["seq"]
        for c in pendientes:
            yield c


@app.route("/video_feed/<cam_id>/<token>")
def video_feed(cam_id, token):
    if not autorizado(cam_id, token):
        return "Acceso denegado", 403
    return Response(generar_mjpeg(cam_id),
                    mimetype="multipart/x-mixed-replace; boundary=frame",
                    headers={"Cache-Control": "no-cache"})


@app.route("/audio_feed/<cam_id>/<token>")
def audio_feed(cam_id, token):
    if not autorizado(cam_id, token):
        return "Acceso denegado", 403
    return Response(generar_audio(cam_id), mimetype="audio/webm",
                    headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------------------
# Rutas web
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    if os.path.exists(os.path.join(STATIC_DIR, "cliente.html")):
        return send_from_directory(STATIC_DIR, "cliente.html")
    return jsonify(servicio="EcoGuard", estado="en línea", camaras=len(lista_camaras()))


@app.route("/cliente")
def cliente():
    return send_from_directory(STATIC_DIR, "cliente.html")


@app.route("/mapa")
def mapa_publico():
    return send_from_directory(STATIC_DIR, "mapa.html")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.after_request
def cabeceras_cors(resp):
    if request.path.startswith("/api/"):
        resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/api/camaras", methods=["POST"])
def crear_camara():
    for _ in range(10):
        cam, pin = generar_id(), generar_pin()
        try:
            run_db("INSERT INTO camaras (cam_id, pin_hash, creada) VALUES (?,?,?)",
                   (cam, hash_pin(pin), ahora_iso()))
        except sqlite3.IntegrityError:
            continue
        return jsonify(cam_id=cam, pin=pin), 201
    return jsonify(error="No se pudo generar la cámara"), 500


def datos_nodos():
    ts = time.time()
    nodos = []
    for cam in lista_camaras():
        t = telemetry.get(cam, {})
        lat, lon = ubicacion(cam)
        visto = last_seen.get(cam)
        nodos.append({
            "id": cam,
            "nombre": f"Nodo {cam}",
            "zona": nombre_zona(lat, lon),
            "lat": lat,
            "lon": lon,
            "precision_m": t.get("precision"),
            "activo": bool(visto and ts - visto < ACTIVO_SEG),
            "bateria": f"{t['bat']}%" if t.get("bat") is not None else "N/D",
            "cargando": t.get("cargando", False),
            "velocidad": t.get("velocidad"),
            "rumbo": t.get("rumbo"),
            "movimiento": t.get("movimiento"),
            "orientacion": t.get("orient"),
            "luz": t.get("luz"),
            "red": t.get("red"),
            "ultimo_db": t.get("audio_db"),
            "grabando": t.get("grabando", False),
            "fps": fps_stats.get(cam, {}).get("fps", 0),
            "calidad": t.get("calidad"),
            "ultima_vez": (datetime.fromtimestamp(visto, ZONA).isoformat(timespec="seconds")
                           if visto else None),