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
eventlet.monkey_patch()  # debe ir antes de importar el resto

from flask import Flask, Response, jsonify, request, send_file, send_from_directory, abort
from flask_socketio import SocketIO, join_room
import requests as http

# ---------------------------------------------------------------------------
# Configuración (variables de entorno en Render)
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "ecoguard.db")
REC_DIR = os.path.join(DATA_DIR, "grabaciones")
os.makedirs(REC_DIR, exist_ok=True)

ZONA = ZoneInfo(os.environ.get("TZ_NAME", "America/Mexico_City"))
NTFY_URL = os.environ.get("NTFY_URL", "").strip()          # ej. https://ntfy.sh/mi-topico
MAX_GRABACIONES = int(os.environ.get("MAX_GRABACIONES_POR_CAMARA", "200"))
ACTIVO_SEG = 5.0
LAT_DEF, LON_DEF = 19.2780, -99.0080                       # posición de respaldo

# CAMERAS="123:PIN1,CAM-101:PIN2"  (ID:PIN separados por coma)
def parsear_camaras(raw):
    cams = {}
    for item in raw.split(","):
        if ":" in item:
            cid, pin = item.split(":", 1)
            cams[cid.strip()] = pin.strip()
    return cams

CAMERAS = parsear_camaras(os.environ.get("CAMERAS", "123:SEC-99,CAM-101:SEC-99,CAM-102:SEC-99"))

app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cambia-esto")
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet",
    max_http_buffer_size=16 * 1024 * 1024,   # para segmentos de video
    ping_timeout=30,
)

# ---------------------------------------------------------------------------
# Estado en memoria
# ---------------------------------------------------------------------------
condicion = threading.Condition()
frames = {}            # cam -> bytes JPEG (último cuadro)
last_seen = {}         # cam -> timestamp del último cuadro
fps_stats = {}         # cam -> {"n", "t0", "fps"}
telemetry = {}         # cam -> último reporte de sensores
audio_estado = {}      # cam -> {"header", "seq", "chunks", "ts"}
ultimo_evento = {}     # (cam, tipo) -> timestamp (cooldown)

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
    tipo TEXT NOT NULL,            -- 'sonido' | 'robo'
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
        "INSERT INTO nodos (cam_id, lat, lon, actualizado) VALUES (?,?,?,?) "
        "ON CONFLICT(cam_id) DO UPDATE SET lat=excluded.lat, lon=excluded.lon, "
        "actualizado=excluded.actualizado",
        (cam, lat, lon, ahora_iso()),
    )


def enviar_push(titulo, texto):
    try:
        http.post(NTFY_URL, data=texto.encode("utf-8"),
                  headers={"Title": titulo, "Priority": "urgent", "Tags": "rotating_light"},
                  timeout=5)
    except Exception as e:  # no detener el servidor por una notificación
        print("Error enviando notificación:", e)


def registrar_evento(cam, tipo, razon, valor=None):
    lat, lon = ubicacion(cam)
    fecha = ahora_iso()
    eid = run_db(
        "INSERT INTO eventos (cam_id, tipo, razon, valor, lat, lon, fecha) VALUES (?,?,?,?,?,?,?)",
        (cam, tipo, razon, valor, lat, lon, fecha),
    )
    alerta = {"id": eid, "cam_id": cam, "tipo": tipo, "razon": razon,
              "valor": valor, "lat": lat, "lon": lon, "fecha": fecha}
    socketio.emit("alerta", alerta)
    if tipo == "robo" and NTFY_URL:
        threading.Thread(
            target=enviar_push,
            args=("ALERTA EcoGuard", f"Camara {cam}: {razon}. Hora: {fecha}"),
            daemon=True,
        ).start()
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
# Socket.IO: dispositivos (teléfonos)
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
            # El primer fragmento de MediaRecorder contiene la cabecera del contenedor
            audio_estado[cam] = {"header": bytes(chunk), "seq": seq,
                                 "chunks": collections.deque(maxlen=60), "ts": time.time()}
        else:
            prev["seq"] = seq
            prev["chunks"].append((seq, bytes(chunk)))
            prev["ts"] = time.time()
        condicion.notify_all()


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
    run_db(
        "INSERT INTO grabaciones (cam_id, archivo, inicio, duracion, bytes) VALUES (?,?,?,?,?)",
        (cam, f"{cam}/{nombre}", data.get("inicio"), float(data.get("duracion") or 0), len(video)),
    )
    podar_grabaciones(cam)
    return {"ok": True}


def podar_grabaciones(cam):
    viejas = run_db(
        "SELECT id, archivo FROM grabaciones WHERE cam_id=? ORDER BY id DESC LIMIT -1 OFFSET ?",
        (cam, MAX_GRABACIONES), True,
    )
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
    nuevo = {**previo, **{k: data.get(k) for k in (
        "lat", "lon", "precision", "velocidad", "rumbo", "bat", "cargando", "orient",
        "movimiento", "luz", "red", "audio_db", "grabando", "fps", "calidad")}}
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
    registrar_evento(
        cam, "robo",
        f"Movimiento brusco del teléfono ({mag:.1f} m/s²): posible intento de robo",
        mag,
    )


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
            break  # la cámara dejó de transmitir


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
# Rutas y API
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return jsonify(servicio="EcoGuard", estado="en línea", camaras=list(CAMERAS.keys()))


@app.route("/cliente")
def cliente():
    return send_from_directory("static", "cliente.html")


@app.route("/api/estado_nodos")
def api_estado_nodos():
    ts = time.time()
    nodos = []
    for cam in CAMERAS:
        t = telemetry.get(cam, {})
        lat, lon = ubicacion(cam)
        visto = last_seen.get(cam)
        nodos.append({
            "id": cam,
            "nombre": f"Nodo {cam}",
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
        })
    return jsonify(nodos)


@app.route("/api/eventos")
def api_eventos():
    cam = request.args.get("cam_id")
    horas = float(request.args.get("horas", 0) or 0)
    limite = min(int(request.args.get("limit", 100)), 500)
    condiciones, params = [], []
    if cam:
        condiciones.append("cam_id=?"); params.append(cam)
    if horas:
        desde = datetime.now(ZONA) - timedelta(hours=horas)
        condiciones.append("fecha>=?"); params.append(desde.isoformat(timespec="seconds"))
    where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
    filas = run_db(f"SELECT * FROM eventos {where} ORDER BY id DESC LIMIT ?",
                   (*params, limite), True)
    return jsonify(filas)


@app.route("/api/estadisticas")
def api_estadisticas():
    cam = request.args.get("cam_id")
    where, params = ("WHERE cam_id=?", (cam,)) if cam else ("", ())
    por_hora = run_db(
        f"SELECT substr(fecha,12,2) AS hora, COUNT(*) AS total FROM eventos {where} "
        "GROUP BY hora ORDER BY hora", params, True)
    por_tipo = run_db(
        f"SELECT tipo, COUNT(*) AS total FROM eventos {where} GROUP BY tipo", params, True)
    return jsonify(por_hora=[[f["hora"], f["total"]] for f in por_hora], por_tipo=por_tipo)


@app.route("/api/grabaciones")
def api_grabaciones():
    cam = request.args.get("cam_id", "")
    filas = run_db(
        "SELECT id, cam_id, inicio, duracion, bytes FROM grabaciones WHERE cam_id=? "
        "ORDER BY id DESC LIMIT 50", (cam,), True)
    for f in filas:
        f["ruta"] = f"/grabaciones/{f['id']}"
    return jsonify(filas)


@app.route("/grabaciones/<int:rid>/<token>")
def ver_grabacion(rid, token):
    fila = run_db("SELECT cam_id, archivo FROM grabaciones WHERE id=?", (rid,), True)
    if not fila or not autorizado(fila[0]["cam_id"], token):
        abort(403)
    return send_file(os.path.join(REC_DIR, fila[0]["archivo"]),
                     mimetype="video/webm", conditional=True)


ACCIONES = {"start_recording", "stop_recording", "mute_audio", "unmute_audio",
            "calidad_alta", "calidad_baja"}


@app.route("/api/comando", methods=["POST"])
def api_comando():
    datos = request.get_json(silent=True) or {}
    cam, pin = str(datos.get("cam_id", "")), str(datos.get("pin", ""))
    if not autorizado(cam, pin):
        return jsonify(error="ID o PIN incorrecto"), 403
    accion = datos.get("accion")
    if accion not in ACCIONES:
        return jsonify(error="Acción no válida"), 400
    socketio.emit("comando", {"accion": accion}, to=sala(cam))
    return jsonify(ok=True)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)