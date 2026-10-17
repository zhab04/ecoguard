import json
import os

import folium
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

st.set_page_config(page_title="EcoGuard", layout="wide", page_icon="🛡️")

SERVER_URL = (os.environ.get("ECOGUARD_SERVER_URL") or "http://localhost:5000").rstrip("/")
TIMEOUT = 6

# Mapa sin clave: Esri World Dark Gray (base oscura) + etiquetas de calles y colonias
TILES_BASE = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
TILES_ETIQUETAS = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
ATRIBUCION_MAPA = "Mapa &copy; Esri y colaboradores"

THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
:root { --bg:#000; --bg-2:#0B100C; --bg-3:#141C16; --line:#1F2B22; --text:#EDF7F0; --muted:#8FA397; --accent:#00E676; }
html, body, [class*="css"], .stApp, p, label, input, button { font-family:'Roboto',system-ui,sans-serif !important; }
.stApp { background:var(--bg); color:var(--text); font-size:18px; }
header[data-testid="stHeader"] { background:var(--bg); }
.block-container { padding-top:2rem; padding-bottom:4rem; max-width:1400px; }
[data-testid="stSidebar"] { background:var(--bg); border-right:1px solid var(--line); }
[data-testid="stSidebar"] .stRadio > label { display:none; }
[data-testid="stSidebar"] .stRadio label { padding:12px 14px; border-radius:10px; width:100%; cursor:pointer; }
[data-testid="stSidebar"] .stRadio label:hover { background:var(--bg-3); }
[data-testid="stSidebar"] .stRadio label p { font-size:1.1rem; font-weight:500; color:var(--text); }
.logo { display:flex; align-items:center; gap:12px; font-size:1.9rem; font-weight:700; margin:0 0 1.5rem .5rem; }
h1,h2,h3 { color:var(--text) !important; font-weight:700 !important; }
h2 { font-size:2.1rem !important; margin-bottom:.25rem !important; }
.subtitle { color:var(--muted); font-size:1.1rem; margin-bottom:1.8rem; }
.stTextInput input { background:var(--bg-3) !important; border:1px solid var(--line) !important; border-radius:10px !important; color:var(--text) !important; font-size:1.1rem !important; }
.stButton > button { background:var(--accent); color:#000; border:none; border-radius:999px; font-weight:700; width:100%; }
.stButton > button:hover { background:#00C853; color:#000; }
[data-testid="stMetricValue"] { color:var(--accent) !important; }
[data-testid="stExpander"] { background:var(--bg-2); border:1px solid var(--line) !important; border-radius:12px; }
.thumb { position:relative; width:100%; aspect-ratio:16/9; background:var(--bg-2); border:1px solid var(--line); border-radius:12px; overflow:hidden; }
.thumb img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.thumb-empty { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:8px; color:var(--muted); font-size:1.2rem; }
.badge { display:inline-block; padding:3px 10px; border-radius:6px; font-size:.95rem; font-weight:700; margin-top:10px; }
.badge-live { background:var(--accent); color:#000; }
.badge-off { background:var(--bg-3); color:var(--muted); }
.card-title { font-size:1.3rem; font-weight:600; margin-top:12px; }
.card-sub { color:var(--muted); font-size:1.05rem; margin-top:4px; }
.empty-box { background:var(--bg-2); border:1px solid var(--line); border-radius:12px; padding:40px; text-align:center; color:var(--muted); font-size:1.2rem; }
.spacer { height:14px; }
hr { border-color:var(--line) !important; margin:2rem 0 !important; }
</style>
"""
st.markdown(THEME_CSS, unsafe_allow_html=True)

LOGO_SVG = """
<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#00E676" stroke-width="1.8" aria-hidden="true">
  <path d="M12 2.5 L19.5 5.5 V11 C19.5 15.8 16.4 19.8 12 21.5 C7.6 19.8 4.5 15.8 4.5 11 V5.5 Z"/>
  <circle cx="12" cy="11" r="3.6"/><circle cx="12" cy="11" r="1.2" fill="#00E676" stroke="none"/>
</svg>"""


# ---------------------------------------------------------------------------
# Utilidades de API y HTML
# ---------------------------------------------------------------------------
def api_get(ruta, **params):
    try:
        r = requests.get(f"{SERVER_URL}{ruta}",
                         params={k: v for k, v in params.items() if v not in (None, "")},
                         timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def api_post(ruta, payload):
    try:
        r = requests.post(f"{SERVER_URL}{ruta}", json=payload, timeout=TIMEOUT)
        datos = r.json() if r.content else {}
        return r.ok, datos.get("error", "Orden enviada")
    except (requests.RequestException, ValueError):
        return False, "No se pudo contactar al servidor"


def thumb_html(url=None, texto="Sin señal"):
    img = f'<img src="{url}" onerror="this.style.display=\'none\'" />' if url else ""
    return (f'<div class="thumb"><div class="thumb-empty"><div style="font-size:2.2rem">📡</div>'
            f'<div>{texto}</div></div>{img}</div>')


def card_meta(titulo, activo, sub=""):
    badge = ('<span class="badge badge-live">EN VIVO</span>' if activo
             else '<span class="badge badge-off">Sin conexión</span>')
    return f'<div class="card-title">{titulo}</div><div class="card-sub">{sub}</div>{badge}'


PLANTILLA_AUDIO = """
<div style="font-family:Roboto,sans-serif;color:#EDF7F0;background:#0B100C;border:1px solid #1F2B22;
            border-radius:12px;padding:14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap">
  <audio id="a" src="__URL__" autoplay></audio>
  <button id="b" style="background:#00E676;color:#000;border:0;border-radius:999px;padding:10px 18px;
          font-weight:700;cursor:pointer">🔇 Silenciar</button>
  <span style="color:#8FA397;font-size:14px">Audio en vivo · si no suena, pulsa play en el reproductor.</span>
</div>
<script>
const a = document.getElementById('a'), b = document.getElementById('b');
b.onclick = () => { a.muted = !a.muted; b.textContent = a.muted ? '🔊 Activar sonido' : '🔇 Silenciar';
                    if (a.paused) a.play(); };
a.play().catch(() => {});
</script>
"""


def reproductor_audio(cam, pin):
    components.html(PLANTILLA_AUDIO.replace("__URL__", f"{SERVER_URL}/audio_feed/{cam}/{pin}"), height=90)


PLANTILLA_HABLAR = """
<div style="font-family:Roboto,sans-serif;background:#0B100C;border:1px solid #1F2B22;
            border-radius:12px;padding:12px">
  <button id="h" style="width:100%;background:#00E676;color:#000;border:0;border-radius:999px;
          padding:12px;font-weight:700;font-size:16px;cursor:pointer;user-select:none;touch-action:none">
    🎙️ Mantén presionado para hablar</button>
  <div id="s" style="color:#8FA397;font-size:13px;margin-top:6px">Micrófono apagado</div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
<script>
const SERVER = __SERVER__, CAM = __CAM__, PIN = __PIN__;
const btn = document.getElementById('h'), est = document.getElementById('s');
const sock = io(SERVER, { transports: ["websocket", "polling"] });
let ctx = null, proc = null, stream = null, hablando = false;

async function preparar() {
  if (ctx) return;
  stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  ctx = new (window.AudioContext || window.webkitAudioContext)();
  const src = ctx.createMediaStreamSource(stream);
  proc = ctx.createScriptProcessor(4096, 1, 1);
  const silencio = ctx.createGain();
  silencio.gain.value = 0;
  proc.onaudioprocess = e => {
    if (!hablando) return;
    const f = e.inputBuffer.getChannelData(0);
    const i16 = new Int16Array(f.length);
    for (let i = 0; i < f.length; i++) {
      const s = Math.max(-1, Math.min(1, f[i]));
      i16[i] = s < 0 ? s * 32768 : s * 32767;
    }
    sock.emit("hablar_chunk", { cam_id: CAM, token: PIN, chunk: i16.buffer, sr: ctx.sampleRate });
  };
  src.connect(proc);
  proc.connect(silencio);
  silencio.connect(ctx.destination);
}

async function iniciar(e) {
  e.preventDefault();
  try {
    await preparar();
    if (ctx.state === "suspended") await ctx.resume();
    hablando = true;
    btn.style.background = "#FF5252";
    est.textContent = "🔴 Hablando al teléfono…";
  } catch (err) {
    est.textContent = "No se pudo usar el micrófono: " + err.message;
  }
}

function parar() {
  if (!hablando) return;
  hablando = false;
  btn.style.background = "#00E676";
  est.textContent = "Micrófono apagado";
}

btn.addEventListener("pointerdown", iniciar);
["pointerup", "pointerleave", "pointercancel"].forEach(ev => btn.addEventListener(ev, parar));
</script>
"""


def boton_hablar(cam, pin):
    html = (PLANTILLA_HABLAR.replace("__SERVER__", json.dumps(SERVER_URL))
                            .replace("__CAM__", json.dumps(cam))
                            .replace("__PIN__", json.dumps(pin)))
    components.html(html, height=110)


def accion(cam, pin, accion_id, texto):
    ok, msg = api_post("/api/comando", {"cam_id": cam, "pin": pin, "accion": accion_id})
    (st.toast if ok else st.error)(texto if ok else msg)


# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------
st.sidebar.markdown(f'<div class="logo">{LOGO_SVG}<span>EcoGuard</span></div>', unsafe_allow_html=True)
modo = st.sidebar.radio(
    "Navegación",
    ["Crear cámara", "Cámara individual", "Cuadrícula de cámaras", "Mapa de nodos", "Análisis de datos"],
    label_visibility="collapsed",
)


@st.fragment(run_every="5s")
def alertas_en_vivo():
    """Muestra una notificación en pantalla cada vez que llega un evento nuevo."""
    eventos = api_get("/api/eventos", limit=5) or []
    if not eventos:
        return
    ultimo = eventos[0]["id"]
    if "ultimo_evento" not in st.session_state:
        st.session_state.ultimo_evento = ultimo
        return
    if ultimo > st.session_state.ultimo_evento:
        for e in eventos:
            if e["id"] > st.session_state.ultimo_evento:
                icono = "🚨" if e["tipo"] == "robo" else "🔊"
                st.toast(f"{icono} Cámara {e['cam_id']}: {e['razon']}")
        st.session_state.ultimo_evento = ultimo


with st.sidebar:
    alertas_en_vivo()


# ---------------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------------
def vista_registro():
    st.markdown('<h2>Crear cámara</h2>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Genera un ID y un PIN nuevos para un teléfono.</div>',
                unsafe_allow_html=True)

    if st.button("Generar ID y PIN", key="generar_camara"):
        try:
            r = requests.post(f"{SERVER_URL}/api/camaras", timeout=TIMEOUT)
            datos = r.json()
            if r.ok:
                st.session_state.camara_nueva = datos
            else:
                st.session_state.camara_nueva = None
                st.error(datos.get("error", "No se pudo crear la cámara"))
        except (requests.RequestException, ValueError):
            st.error("No se pudo contactar al servidor.")

    nueva = st.session_state.get("camara_nueva")
    if nueva:
        st.success("Cámara creada. Guarda este PIN ahora: no se volverá a mostrar.")
        st.markdown("**ID de la cámara**")
        st.code(nueva["cam_id"])
        st.markdown("**PIN**")
        st.code(nueva["pin"])
        st.markdown('<div class="empty-box">Escribe este ID y PIN en la página /cliente del teléfono, '
                    'y en Cámara individual del dashboard.</div>', unsafe_allow_html=True)


def vista_individual():
    st.markdown('<h2>Cámara individual</h2>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Video, audio, sensores y grabaciones de una cámara.</div>',
                unsafe_allow_html=True)

    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        cam_id = st.text_input("ID de la cámara", key="ind_cam_id")
    with c2:
        token = st.text_input("PIN", type="password", key="ind_token")
    with c3:
        st.markdown('<div class="spacer"></div>', unsafe_allow_html=True)
        if st.button("Conectar", key="ind_connect"):
            st.session_state.ind_activa = (cam_id.strip().lower(), token.strip().lower())

    activa = st.session_state.get("ind_activa")
    if not activa or not activa[0] or not activa[1]:
        st.markdown('<div class="empty-box">Ingresa el ID y el PIN para ver la transmisión.</div>',
                    unsafe_allow_html=True)
        return

    cam, pin = activa
    nodos = api_get("/api/estado_nodos")
    if nodos is None:
        st.error("No se pudo contactar al servidor.")
        return
    nodo = next((n for n in nodos if n["id"] == cam), None)
    if nodo is None:
        st.error("Esa cámara no existe. Créala en la sección Crear cámara.")
        return

    if not nodo["activo"]:
        st.info("La cámara no está transmitiendo. En el teléfono abre /cliente, "
                "escribe el mismo ID y PIN, y pulsa Iniciar nodo.")

    video_col, info_col = st.columns([3, 2], gap="large")
    with video_col:
        st.markdown(thumb_html(f"{SERVER_URL}/video_feed/{cam}/{pin}", "Buscando señal…"),
                    unsafe_allow_html=True)
        st.markdown(card_meta(f"Cámara {cam}", nodo["activo"], nodo["zona"]), unsafe_allow_html=True)
        st.markdown("<div class='spacer'></div>", unsafe_allow_html=True)
        reproductor_audio(cam, pin)
        st.markdown("<div class='spacer'></div>", unsafe_allow_html=True)
        boton_hablar(cam, pin)

    with info_col:
        m1, m2 = st.columns(2)
        m1.metric("Batería", nodo["bateria"])
        m2.metric("FPS de video", nodo["fps"])
        m1.metric("Sonido", f"{nodo['ultimo_db']} dB" if nodo["ultimo_db"] is not None else "N/D")
        m2.metric("Movimiento", f"{nodo['movimiento']} m/s²" if nodo["movimiento"] is not None else "N/D")
        st.caption(f"Zona: {nodo['zona']} · Velocidad GPS: {nodo['velocidad'] or 'N/D'} km/h · "
                   f"Red: {nodo['red'] or 'N/D'} · Última señal: {nodo['ultima_vez'] or 'N/D'}")

        st.markdown("#### Controles")
        b1, b2 = st.columns(2)
        if b1.button("● Grabar fragmentos", key="rec_on"):
            accion(cam, pin, "start_recording", "Grabación iniciada")
        if b2.button("■ Detener grabación", key="rec_off"):
            accion(cam, pin, "stop_recording", "Grabación detenida")
        b3, b4 = st.columns(2)
        if b3.button("Silenciar micrófono", key="mute_on"):
            accion(cam, pin, "mute_audio", "Audio del teléfono silenciado")
        if b4.button("Activar micrófono", key="mute_off"):
            accion(cam, pin, "unmute_audio", "Audio del teléfono activado")
        b5, b6 = st.columns(2)
        if b5.button("Calidad alta", key="q_alta"):
            accion(cam, pin, "calidad_alta", "Calidad alta")
        if b6.button("Calidad baja (ahorro)", key="q_baja"):
            accion(cam, pin, "calidad_baja", "Calidad baja")

    st.markdown("---")
    st.markdown("#### Fragmentos grabados")
    grabaciones = api_get("/api/grabaciones", cam_id=cam) or []
    if not grabaciones:
        st.markdown('<div class="empty-box">Aún no hay fragmentos grabados.</div>', unsafe_allow_html=True)
    for g in grabaciones[:6]:
        st.caption(f"{g['inicio']} · {(g['duracion'] or 0):.0f} s")
        st.video(f"{SERVER_URL}{g['ruta']}/{pin}")


def vista_cuadricula():
    st.markdown('<h2>Cuadrícula de cámaras</h2>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Monitorea hasta nueve cámaras. Cambia el ID y el PIN de cada espacio.</div>',
                unsafe_allow_html=True)

    nodos = api_get("/api/estado_nodos") or []
    por_id = {n["id"]: n for n in nodos}
    ids_servidor = list(por_id.keys())

    for i in range(9):
        st.session_state.setdefault(f"id_{i}", ids_servidor[i] if i < len(ids_servidor) else "")
        st.session_state.setdefault(f"pin_{i}", "")
        st.session_state.setdefault(f"conn_{i}", False)

    for fila in range(3):
        cols = st.columns(3, gap="large")
        for c in range(3):
            i = fila * 3 + c
            with cols[c]:
                cam = st.session_state[f"id_{i}"].strip().lower()
                pin = st.session_state[f"pin_{i}"].strip().lower()
                nodo = por_id.get(cam)
                conectada = st.session_state[f"conn_{i}"]

                if conectada and cam and pin:
                    st.markdown(thumb_html(f"{SERVER_URL}/video_feed/{cam}/{pin}"), unsafe_allow_html=True)
                else:
                    st.markdown(thumb_html(None, "Sin conexión"), unsafe_allow_html=True)

                titulo = f"Cámara {cam}" if cam else f"Espacio {i + 1}"
                sub = nodo["zona"] if nodo else "Sin cámara asignada"
                st.markdown(card_meta(titulo, bool(nodo and nodo["activo"] and conectada), sub),
                            unsafe_allow_html=True)

                with st.expander("Configurar"):
                    st.text_input("ID de la cámara", key=f"id_{i}")
                    st.text_input("PIN", type="password", key=f"pin_{i}")
                    if cam and not nodo:
                        st.caption("⚠️ Este ID no existe en el servidor.")

                if st.button("Desconectar" if conectada else "Conectar", key=f"btn_{i}", disabled=not cam):
                    st.session_state[f"conn_{i}"] = not conectada
                    st.rerun()
        st.markdown('<hr/>', unsafe_allow_html=True)


@st.fragment(run_every="5s")
def vista_mapa():
    st.markdown('<h2>Mapa de nodos</h2>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Estado, zona y eventos recientes de cada cámara. '
                'Se actualiza cada 5 segundos sin mover tu vista.</div>', unsafe_allow_html=True)
    st.markdown(f"Mapa público para compartir: [{SERVER_URL}/mapa]({SERVER_URL}/mapa)")

    nodos = api_get("/api/estado_nodos")
    if nodos is None:
        st.error("No se pudo contactar al servidor. Revisa que el servicio de Render esté activo.")
        return
    if not nodos:
        st.info("No hay cámaras creadas. Ve a Crear cámara.")
        return

    eventos = api_get("/api/eventos", horas=24, limit=200) or []

    # Vista actual del mapa: se conserva lo que el usuario movió o acercó.
    # Solo la primera vez se calcula el centro a partir de los nodos.
    if "mapa_vista" not in st.session_state:
        centro = [sum(n["lat"] for n in nodos) / len(nodos), sum(n["lon"] for n in nodos) / len(nodos)]
        st.session_state.mapa_vista = {"centro": centro, "zoom": 14 if len(nodos) > 1 else 16}

    vista = st.session_state.mapa_vista
    mapa = folium.Map(location=vista["centro"], zoom_start=vista["zoom"],
                      tiles=TILES_BASE, attr=ATRIBUCION_MAPA)
    folium.TileLayer(tiles=TILES_ETIQUETAS, attr=ATRIBUCION_MAPA, name="Etiquetas").add_to(mapa)

    for n in nodos:
        estado_txt = "EN VIVO" if n["activo"] else "Sin conexión"
        color_hex = "#00C853" if n["activo"] else "#9E9E9E"
        if n.get("precision_m"):
            folium.Circle(location=[n["lat"], n["lon"]], radius=n["precision_m"],
                          color=color_hex, fill=True, fill_opacity=0.08, weight=1).add_to(mapa)
        popup = f"""
        <div style="font-family:Roboto,Arial,sans-serif;width:240px;color:#000;font-size:15px">
          <div style="font-size:18px;font-weight:700;margin-bottom:6px">{n['id']}</div>
          <div>Zona: <b>{n['zona']}</b></div>
          <div>Estado: <b style="color:{color_hex}">{estado_txt}</b></div>
          <div>Batería: {n['bateria']} {'⚡' if n['cargando'] else ''}</div>
          <div>Velocidad: {n['velocidad'] or 'N/D'} km/h</div>
          <div>Sonido: {n['ultimo_db'] if n['ultimo_db'] is not None else 'N/D'} dB</div>
          <div>FPS: {n['fps']} · Grabando: {'sí' if n['grabando'] else 'no'}</div>
          <div>GPS: {n['lat']:.5f}, {n['lon']:.5f}</div>
          <div>Última señal: {n['ultima_vez'] or 'N/D'}</div>
        </div>"""
        folium.Marker(
            location=[n["lat"], n["lon"]],
            popup=folium.Popup(popup, max_width=280),
            tooltip=f"{n['id']} · {n['zona']} · {estado_txt}",
            icon=folium.Icon(color="green" if n["activo"] else "gray", icon="video-camera", prefix="fa"),
        ).add_to(mapa)

    for e in eventos:
        if e["lat"] is None:
            continue
        color = "#FF5252" if e["tipo"] == "robo" else "#FFB300"
        folium.CircleMarker(
            location=[e["lat"], e["lon"]], radius=9, color=color, fill=True, fill_opacity=0.8,
            tooltip=f"{e['fecha'][11:16]} · Cámara {e['cam_id']} · {e['razon']}",
        ).add_to(mapa)

    # Guardamos la vista que el usuario deja cada vez que mueve o acerca el mapa
    salida = st_folium(mapa, height=540, use_container_width=True,
                       returned_objects=["center", "zoom"], key="mapa")
    if salida and salida.get("center") and salida.get("zoom"):
        st.session_state.mapa_vista = {
            "centro": [salida["center"]["lat"], salida["center"]["lng"]],
            "zoom": salida["zoom"],
        }

    st.caption("🟢 cámara activa · ⚫ sin conexión · 🔴 posible robo (24 h) · 🟠 pico de sonido (24 h)")

    tabla = pd.DataFrame(nodos)[["id", "zona", "activo", "bateria", "velocidad", "fps", "ultimo_db", "ultima_vez"]]
    tabla["activo"] = tabla["activo"].map({True: "EN VIVO", False: "Sin conexión"})
    tabla.columns = ["Cámara", "Zona", "Estado", "Batería", "Velocidad km/h", "FPS", "Sonido dB", "Última señal"]
    st.dataframe(tabla, hide_index=True, use_container_width=True)


def vista_analisis():
    st.markdown('<h2>Análisis de datos</h2>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Eventos registrados por hora del día.</div>', unsafe_allow_html=True)

    nodos = api_get("/api/estado_nodos") or []
    ids = [n["id"] for n in nodos]
    if not ids:
        st.markdown('<div class="empty-box">No hay cámaras creadas todavía.</div>', unsafe_allow_html=True)
        return
    seleccion = st.selectbox("Cámara", ["Todas"] + ids)
    cam = None if seleccion == "Todas" else seleccion

    est = api_get("/api/estadisticas", cam_id=cam) or {"por_hora": [], "por_tipo": []}
    base = pd.DataFrame({"hora": [f"{h:02d}" for h in range(24)]})
    datos = pd.DataFrame(est["por_hora"], columns=["hora", "total"])
    df = base.merge(datos, on="hora", how="left").fillna({"total": 0}).set_index("hora")
    st.markdown("#### Eventos por hora")
    st.bar_chart(df)

    st.markdown("#### Eventos recientes")
    eventos = api_get("/api/eventos", cam_id=cam, limit=200) or []
    if not eventos:
        st.markdown('<div class="empty-box">Sin eventos