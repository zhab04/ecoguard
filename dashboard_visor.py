import html
import json
import os

import folium
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

st.set_page_config(page_title="EcoGuard", layout="wide", page_icon="🛡️",
                   initial_sidebar_state="collapsed")

SERVER_URL = (os.environ.get("ECOGUARD_SERVER_URL") or "http://localhost:5000").rstrip("/")
TIMEOUT = 6
RADIO = "18px"

PALETA_OSCURA = {
    "bg": "#000000", "bg2": "#0B100C", "bg3": "#141C16", "line": "#1F2B22",
    "text": "#EDF7F0", "muted": "#8FA397", "accent": "#00E676", "accent2": "#00C853",
    "danger": "#FF5252", "sel": "#1B2A1F",
    "glass": "rgba(11,16,12,0.62)", "glass2": "rgba(20,28,22,0.55)", "glass3": "rgba(0,0,0,0.35)",
}
PALETA_CLARA = {
    "bg": "#F3F8F4", "bg2": "#FFFFFF", "bg3": "#E8F2EB", "line": "#D2E4D7",
    "text": "#0B1A10", "muted": "#5B6F62", "accent": "#00C853", "accent2": "#00A843",
    "danger": "#E53935", "sel": "#DDF4E4",
    "glass": "rgba(255,255,255,0.66)", "glass2": "rgba(232,242,235,0.6)", "glass3": "rgba(255,255,255,0.4)",
}

# Mapas sin clave: Esri (base + etiquetas de calles y colonias)
MAPA_OSCURO = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
)
MAPA_CLARO = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
)
ATRIBUCION_MAPA = "Mapa &copy; Esri y colaboradores"

LOGO_SVG = """
<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#00E676" stroke-width="1.8" aria-hidden="true">
  <path d="M12 2.5 L19.5 5.5 V11 C19.5 15.8 16.4 19.8 12 21.5 C7.6 19.8 4.5 15.8 4.5 11 V5.5 Z"/>
  <circle cx="12" cy="11" r="3.6"/><circle cx="12" cy="11" r="1.2" fill="#00E676" stroke="none"/>
</svg>"""


def paleta_actual():
    return PALETA_CLARA if st.session_state.get("claro", False) else PALETA_OSCURA


def css_tema(p):
    variables = "".join(f"--{k}:{v};" for k, v in p.items())
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
:root {{ {variables} --radio: {RADIO}; }}
html, body, [class*="css"], .stApp, p, label, input, button, textarea {{
  font-family: 'Roboto', system-ui, sans-serif !important;
}}
.stApp {{
  background:
    radial-gradient(1200px 600px at 10% -10%, rgba(0,230,118,.10), transparent 60%),
    radial-gradient(900px 500px at 110% 10%, rgba(0,200,83,.07), transparent 60%),
    var(--bg);
  color: var(--text);
}}
.stApp p, .stApp label, .stApp li, .stApp h1, .stApp h2, .stApp h3, .stApp h4 {{ color: var(--text); }}
header[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="collapsedControl"] {{ display: none !important; }}
.block-container {{ padding-top: 1rem; padding-bottom: 6rem; max-width: 1150px; }}
[data-testid="stHorizontalBlock"] {{ gap: .75rem !important; align-items: stretch; }}
[data-testid="stVerticalBlock"] {{ gap: .75rem; }}
h2 {{ font-size: 1.9rem !important; font-weight: 700 !important; margin: 0 !important; letter-spacing: -.3px; }}

/* Encabezado */
.logo {{ display: flex; align-items: center; gap: 10px; font-size: 1.5rem; font-weight: 700; color: var(--text); }}
.subtitle {{ color: var(--muted); font-size: 1rem; margin: 4px 0 12px; }}

/* Tarjetas: bordes alineados, fondo translúcido con desenfoque */
[data-testid="stVerticalBlockBorderWrapper"] {{
  background: var(--glass) !important;
  -webkit-backdrop-filter: blur(14px) saturate(120%);
  backdrop-filter: blur(14px) saturate(120%);
  border: 1px solid var(--line) !important;
  border-radius: var(--radio) !important;
  box-shadow: 0 10px 30px rgba(0,0,0,.20), inset 0 1px 0 rgba(255,255,255,.04);
  animation: fadeUp .45s ease both;
  padding: 0 !important;
  overflow: hidden;
}}
[data-testid="stVerticalBlockBorderWrapper"] > div {{ padding: 14px 16px !important; }}
[data-testid="stVerticalBlockBorderWrapper"] > div > div {{ gap: .6rem; }}
@keyframes fadeUp {{ from {{ opacity: 0; transform: translateY(12px); }} to {{ opacity: 1; transform: none; }} }}
@keyframes pulso {{ 0%, 100% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: .3; transform: scale(.6); }} }}

/* Navegación superior en pastillas translúcidas */
div[role="radiogroup"] {{
  display: flex; flex-wrap: wrap; gap: 6px; background: var(--glass);
  -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px);
  border: 1px solid var(--line); border-radius: 999px; padding: 5px; margin-bottom: 12px;
}}
div[role="radiogroup"] label {{
  border-radius: 999px !important; padding: 8px 14px !important; margin: 0 !important;
  transition: background .25s ease, transform .15s ease; cursor: pointer;
}}
div[role="radiogroup"] label:hover {{ background: var(--glass2); }}
div[role="radiogroup"] label:active {{ transform: scale(.96); }}
div[role="radiogroup"] label > div:first-child {{ display: none !important; }}
div[role="radiogroup"] label p {{ font-weight: 600 !important; font-size: .95rem !important; color: var(--muted) !important; }}
div[role="radiogroup"] label:has(input:checked) {{ background: var(--accent); }}
div[role="radiogroup"] label:has(input:checked) p {{ color: #000 !important; }}

/* Botones */
.stButton > button {{
  background: var(--accent); color: #000; border: 0; border-radius: 999px; font-weight: 700;
  width: 100%; padding: .55rem 1rem; transition: transform .15s ease, filter .2s ease;
}}
.stButton > button:hover {{ filter: brightness(1.08); color: #000; }}
.stButton > button:active {{ transform: scale(.97); }}
.stButton > button:disabled {{ opacity: .45; }}

/* Campos y sliders */
.stTextInput input {{
  background: var(--glass2) !important; border: 1px solid var(--line) !important; border-radius: 14px !important;
  color: var(--text) !important; padding: .65rem .9rem !important; font-size: 1.02rem !important;
}}
.stTextInput input:focus {{ border-color: var(--accent) !important; box-shadow: 0 0 0 3px rgba(0,230,118,.18) !important; }}
[data-testid="stWidgetLabel"] p {{ color: var(--muted) !important; }}
[data-testid="stSlider"] [role="slider"] {{ background: var(--accent) !important; box-shadow: 0 0 0 4px rgba(0,230,118,.18); }}
[data-testid="stSlider"] div[data-baseweb="slider"] > div > div:nth-child(2) {{ background: var(--accent) !important; }}
[data-testid="stSelectbox"] div[data-baseweb="select"] > div {{
  background: var(--glass2) !important; border-color: var(--line) !important; border-radius: 14px !important;
}}
[data-testid="stToggle"] label p {{ color: var(--text) !important; font-weight: 600; }}

/* Expansor y captions */
[data-testid="stExpander"] {{
  background: var(--glass2) !important; border: 1px solid var(--line) !important; border-radius: 14px !important;
}}
[data-testid="stExpander"] summary p {{ color: var(--muted) !important; }}
[data-testid="stCaptionContainer"] p {{ color: var(--muted) !important; }}
hr {{ border-color: var(--line) !important; }}
[data-testid="stDataFrame"] {{ border-radius: 14px; overflow: hidden; border: 1px solid var(--line); }}
[data-testid="stVideo"] video {{ border-radius: 14px; }}

/* Etiquetas de estado */
.live {{
  display: inline-flex; align-items: center; gap: 6px; background: var(--accent); color: #000;
  font-weight: 700; font-size: .78rem; padding: 4px 10px; border-radius: 999px; margin-top: 8px;
}}
.live::before {{ content: ""; width: 7px; height: 7px; border-radius: 50%; background: #000; animation: pulso 1.3s infinite; }}
.off {{
  display: inline-flex; align-items: center; background: var(--glass3); color: var(--muted);
  border: 1px solid var(--line); font-weight: 600; font-size: .78rem; padding: 4px 10px; border-radius: 999px; margin-top: 8px;
}}
.titulo-cam {{ font-size: 1.15rem; font-weight: 700; margin-top: 10px; color: var(--text); }}
.zona {{ color: var(--muted); font-size: .92rem; margin-top: 2px; }}

/* Video: la miniatura ocupa el mismo ancho que el marco y usa el mismo radio */
.thumb {{
  position: relative; width: 100%; aspect-ratio: 16 / 9; background: rgba(5,8,5,.55);
  border-radius: 14px; overflow: hidden; border: 1px solid var(--line);
}}
.thumb img {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }}
.thumb .sin {{
  position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 8px; color: #8FA397; font-size: 1.02rem;
}}

/* Indicadores */
.kpis {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 4px 0 10px; }}
.kpi {{
  background: var(--glass2); border: 1px solid var(--line); border-radius: 14px; padding: 10px 12px;
  -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
  transition: transform .2s ease, background .2s ease;
}}
.kpi:hover {{ transform: translateY(-2px); background: var(--glass); }}
.kpi small {{ display: block; color: var(--muted); font-size: .76rem; }}
.kpi b {{ display: block; color: var(--accent); font-size: 1.3rem; margin-top: 2px; }}

/* Leyenda */
.leyenda {{ display: flex; flex-wrap: wrap; gap: 12px; color: var(--muted); font-size: .85rem; margin: 6px 0; }}
.leyenda i {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }}

/* Lista animada */
.al {{ display: flex; flex-direction: column; gap: 6px; }}
.al-item {{
  background: var(--glass2); border: 1px solid var(--line); border-radius: 14px; padding: 11px 14px;
  display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;
  -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
  opacity: 0; transform: translateX(-18px); animation: entra .4s ease forwards;
  animation-delay: calc(var(--i) * 60ms); transition: background .2s ease, transform .2s ease;
}}
.al-item:hover {{ background: var(--sel); transform: translateX(3px); }}
@keyframes entra {{ to {{ opacity: 1; transform: none; }} }}
.al-titulo {{ font-weight: 600; color: var(--text); }}
.al-desc {{ color: var(--muted); font-size: .88rem; margin-top: 2px; }}
.al-meta {{ color: var(--muted); font-size: .8rem; white-space: nowrap; }}
.vacio {{
  text-align: center; color: var(--muted); padding: 26px 10px; border: 1px dashed var(--line);
  border-radius: 14px; background: var(--glass3);
}}
.aviso {{
  background: var(--glass3); border: 1px dashed var(--line); border-radius: 14px; padding: 20px;
  text-align: center; color: var(--muted);
}}

@media (prefers-reduced-motion: reduce) {{
  [data-testid="stVerticalBlockBorderWrapper"], .al-item {{ animation: none !important; opacity: 1 !important; transform: none !important; }}
}}
</style>
"""


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


def esc(texto):
    return html.escape(str(texto if texto is not None else "N/D"))


def thumb_html(url=None, texto="Sin señal"):
    img = f'<img src="{url}" onerror="this.style.display=\'none\'" />' if url else ""
    return (f'<div class="thumb"><div class="sin"><div style="font-size:2.2rem">📡</div>'
            f'<div>{texto}</div></div>{img}</div>')


def badge(activo):
    return '<span class="live">EN VIVO</span>' if activo else '<span class="off">Sin conexión</span>'


def kpis(pares):
    celdas = "".join(f'<div class="kpi"><small>{esc(k)}</small><b>{esc(v)}</b></div>' for k, v in pares)
    return f'<div class="kpis">{celdas}</div>'


def lista_html(items, vacio):
    if not items:
        return f'<div class="vacio">{esc(vacio)}</div>'
    filas = "".join(
        f'<div class="al-item" style="--i:{i}"><div><div class="al-titulo">{esc(it["title"])}</div>'
        f'<div class="al-desc">{esc(it["description"])}</div></div>'
        f'<div class="al-meta">{esc(it["meta"])}</div></div>'
        for i, it in enumerate(items)
    )
    return f'<div class="al">{filas}</div>'


def hora_de(fecha):
    return (fecha or "")[11:16] or "N/D"


# ---------------------------------------------------------------------------
# Plantillas de componentes HTML (audio y hablar), con colores del tema
# ---------------------------------------------------------------------------
PLANTILLA_AUDIO = """
<div style="font-family:Roboto,sans-serif;color:__TEXT__;background:__GLASS__;border:1px solid __LINE__;
            border-radius:14px;padding:10px 12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;
            backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);box-sizing:border-box">
  <audio id="a" src="__URL__" autoplay></audio>
  <button id="b" style="background:__ACCENT__;color:#000;border:0;border-radius:999px;padding:8px 14px;
          font-weight:700;cursor:pointer">🔇 Silenciar</button>
  <span style="color:__MUTED__;font-size:13px">🔊</span>
  <input id="v" type="range" min="0" max="100" value="100" style="flex:1;min-width:120px;accent-color:__ACCENT__">
  <span id="vt" style="color:__MUTED__;font-size:13px;min-width:38px;text-align:right">100%</span>
</div>
<script>
const a = document.getElementById('a'), b = document.getElementById('b');
const v = document.getElementById('v'), vt = document.getElementById('vt');
v.oninput = () => { a.volume = v.value / 100; vt.textContent = v.value + '%'; };
b.onclick = () => { a.muted = !a.muted; b.textContent = a.muted ? '🔊 Activar' : '🔇 Silenciar';
                    if (a.paused) a.play(); };
a.play().catch(() => {});
</script>
"""

PLANTILLA_HABLAR = """
<div style="font-family:Roboto,sans-serif;background:__GLASS__;border:1px solid __LINE__;
            border-radius:14px;padding:10px;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);box-sizing:border-box">
  <button id="h" style="width:100%;background:__ACCENT__;color:#000;border:0;border-radius:999px;
          padding:11px;font-weight:700;font-size:15px;cursor:pointer;user-select:none;touch-action:none">
    🎙️ Mantén presionado para hablar</button>
  <div id="s" style="color:__MUTED__;font-size:13px;margin-top:6px">Micrófono apagado</div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
<script>
const SERVER = __SERVER__, CAM = __CAM__, PIN = __PIN__;
const COLOR_ACTIVO = '__DANGER__', COLOR_NORMAL = '__ACCENT__';
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
    btn.style.background = COLOR_ACTIVO;
    est.textContent = "🔴 Hablando al teléfono…";
  } catch (err) {
    est.textContent = "No se pudo usar el micrófono: " + err.message;
  }
}

function parar() {
  if (!hablando) return;
  hablando = false;
  btn.style.background = COLOR_NORMAL;
  est.textContent = "Micrófono apagado";
}

btn.addEventListener("pointerdown", iniciar);
["pointerup", "pointerleave", "pointercancel"].forEach(ev => btn.addEventListener(ev, parar));
</script>
"""


def render_plantilla(plantilla, reemplazos):
    for clave, valor in reemplazos.items():
        plantilla = plantilla.replace(clave, valor)
    return plantilla


def colores_iframe(p):
    return {"__TEXT__": p["text"], "__GLASS__": p["glass"], "__LINE__": p["line"],
            "__ACCENT__": p["accent"], "__MUTED__": p["muted"], "__DANGER__": p["danger"]}


def reproductor_audio(cam, pin):
    html_audio = render_plantilla(PLANTILLA_AUDIO, {
        **colores_iframe(paleta_actual()),
        "__URL__": f"{SERVER_URL}/audio_feed/{cam}/{pin}",
    })
    components.html(html_audio, height=80)


def boton_hablar(cam, pin):
    html_hablar = render_plantilla(PLANTILLA_HABLAR, {
        **colores_iframe(paleta_actual()),
        "__SERVER__": json.dumps(SERVER_URL),
        "__CAM__": json.dumps(cam),
        "__PIN__": json.dumps(pin),
    })
    components.html(html_hablar, height=104)


def accion(cam, pin, accion_id, texto):
    ok, msg = api_post("/api/comando", {"cam_id": cam, "pin": pin, "accion": accion_id})
    (st.toast if ok else st.error)(texto if ok else msg)


# ---------------------------------------------------------------------------
# Alertas en vivo (sin contenido visible)
# ---------------------------------------------------------------------------
@st.fragment(run_every="5s")
def alertas_en_vivo():
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


# ---------------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------------
def vista_crear():
    st.markdown('<h2>Crear cámara</h2>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Genera un ID y un PIN nuevos para un teléfono.</div>',
                unsafe_allow_html=True)

    with st.container(border=True):
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
            st.markdown('<div class="aviso">Escribe este ID y PIN en la página /cliente del teléfono '
                        'y en la sección Cámara.</div>', unsafe_allow_html=True)


def vista_camara():
    st.markdown('<h2>Cámara</h2>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Video en vivo, audio, controles y grabaciones.</div>',
                unsafe_allow_html=True)

    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 3, 2], vertical_alignment="bottom")
        with c1:
            cam_id = st.text_input("ID de la cámara", key="ind_cam_id", placeholder="cam-tigre-27")
        with c2:
            token = st.text_input("PIN", type="password", key="ind_token", placeholder="tigre482")
        with c3:
            if st.button("Conectar", key="ind_connect"):
                st.session_state.ind_activa = (cam_id.strip().lower(), token.strip().lower())

    activa = st.session_state.get("ind_activa")
    if not activa or not activa[0] or not activa[1]:
        st.markdown('<div class="aviso">Ingresa el ID y el PIN para ver la transmisión.</div>',
                    unsafe_allow_html=True)
        return

    cam, pin = activa
    nodos = api_get("/api/estado_nodos")
    if nodos is None:
        st.error("No se pudo contactar al servidor.")
        return
    nodo = next((n for n in nodos if n["id"] == cam), None)
    if nodo is None:
        st.error("Esa cámara no existe. Créala en la sección Crear.")
        return

    if not nodo["activo"]:
        st.info("La cámara no está transmitiendo. En el teléfono abre /cliente, escribe el ID y PIN "
                "y pulsa Iniciar nodo.")

    izquierda, derecha = st.columns([3, 2], gap="medium")
    with izquierda:
        with st.container(border=True):
            st.markdown(thumb_html(f"{SERVER_URL}/video_feed/{cam}/{pin}", "Buscando señal…"),
                        unsafe_allow_html=True)
            st.markdown(f'<div class="titulo-cam">Cámara {esc(cam)}</div>'
                        f'<div class="zona">📍 {esc(nodo["zona"])}</div>{badge(nodo["activo"])}',
                        unsafe_allow_html=True)
            reproductor_audio(cam, pin)
            boton_hablar(cam, pin)

    with derecha:
        with st.container(border=True):
            st.markdown(kpis([
                ("Batería", nodo["bateria"]),
                ("FPS de video", nodo["fps"]),
                ("Sonido", f"{nodo['ultimo_db']} dB" if nodo["ultimo_db"] is not None else "N/D"),
                ("Movimiento", f"{nodo['movimiento']} m/s²" if nodo["movimiento"] is not None else "N/D"),
            ]), unsafe_allow_html=True)
            st.caption(f"Velocidad GPS: {nodo['velocidad'] or 'N/D'} km/h · Red: {nodo['red'] or 'N/D'} · "
                       f"Última señal: {nodo['ultima_vez'] or 'N/D'}")
            st.markdown("**Controles**")
            b1, b2 = st.columns(2)
            if b1.button("● Grabar", key="rec_on"):
                accion(cam, pin, "start_recording", "Grabación iniciada")
            if b2.button("■ Detener", key="rec_off"):
                accion(cam, pin, "stop_recording", "Grabación detenida")
            b3, b4 = st.columns(2)
            if b3.button("Silenciar mic.", key="mute_on"):
                accion(cam, pin, "mute_audio", "Micrófono del teléfono silenciado")
            if b4.button("Activar mic.", key="mute_off"):
                accion(cam, pin, "unmute_audio", "Micrófono del teléfono activado")
            b5, b6 = st.columns(2)
            if b5.button("Calidad alta", key="q_alta"):
                accion(cam, pin, "calidad_alta", "Calidad alta")
            if b6.button("Ahorro", key="q_baja"):
                accion(cam, pin, "calidad_baja", "Calidad baja")

    with st.container(border=True):
        st.markdown("#### Fragmentos grabados")
        grabaciones = api_get("/api/grabaciones", cam_id=cam) or []
        items = [{
            "title": f"Fragmento {g['id']}",
            "description": f"{(g['duracion'] or 0):.0f} s · {(g['bytes'] or 0) // 1024} KB",
            "meta": hora_de(g["inicio"]),
        } for g in grabaciones[:10]]
        st.markdown(lista_html(items, "Aún no hay fragmentos grabados."), unsafe_allow_html=True)
        for g in grabaciones[:2]:
            st.video(f"{SERVER_URL}{g['ruta']}/{pin}")


def alternar_conexion(i):
    st.session_state[f"conn_{i}"] = not st.session_state[f"conn_{i}"]


def ranura_cuadricula(i, por_id):
    cam = st.session_state[f"id_{i}"].strip().lower()
    pin = st.session_state[f"pin_{i}"].strip().lower()
    nodo = por_id.get(cam)
    conectada = st.session_state[f"conn_{i}"]
    activa = bool(nodo and nodo["activo"] and conectada)

    with st.container(border=True):
        if conectada and cam and pin:
            st.markdown(thumb_html(f"{SERVER_URL}/video_feed/{cam}/{pin}"), unsafe_allow_html=True)
        else:
            st.markdown(thumb_html(None, "Sin conexión"), unsafe_allow_html=True)

        titulo = f"Cámara {esc(cam)}" if cam else f"Espacio {i + 1}"
        sub = nodo["zona"] if nodo else "Sin cámara asignada"
        st.markdown(f'<div class="titulo-cam">{titulo}</div>'
                    f'<div class="zona">📍 {esc(sub)}</div>{badge(activa)}', unsafe_allow_html=True)

        with st.expander("Configurar"):
            st.text_input("ID de la cámara", key=f"id_{i}")
            st.text_input("PIN", type="password", key=f"pin_{i}")
            if cam and not nodo:
                st.caption("⚠️ Este ID no existe en el servidor.")

        st.button("Desconectar" if conectada else "Conectar", key=f"btn_{i}",
                  disabled=not cam, on_click=alternar_conexion, args=(i,))


def vista_cuadricula():
    st.markdown('<h2>Cuadrícula</h2>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Monitorea hasta nueve cámaras a la vez.</div>', unsafe_allow_html=True)

    with st.container(border=True):
        columnas = st.slider("Columnas por fila", 1, 3, 3, key="grid_cols")

    nodos = api_get("/api/estado_nodos") or []
    por_id = {n["id"]: n for n in nodos}
    ids_servidor = list(por_id.keys())

    for i in range(9):
        st.session_state.setdefault(f"id_{i}", ids_servidor[i] if i < len(ids_servidor) else "")
        st.session_state.setdefault(f"pin_{i}", "")
        st.session_state.setdefault(f"conn_{i}", False)

    fila = None
    for i in range(9):
        if i % columnas == 0:
            fila = st.columns(columnas, gap="small")
        with fila[i % columnas]:
            ranura_cuadricula(i, por_id)


@st.fragment(run_every="5s")
def vista_mapa():
    st.markdown('<h2>Mapa</h2>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Ubicación y estado de cada cámara. Se actualiza cada 5 segundos '
                'sin mover tu vista.</div>', unsafe_allow_html=True)
    st.markdown(f"Mapa público para compartir: [{SERVER_URL}/mapa]({SERVER_URL}/mapa)")

    with st.container(border=True):
        horas = st.slider("Eventos de las últimas horas", 1, 24, 24, key="mapa_horas")

    nodos = api_get("/api/estado_nodos")
    if nodos is None:
        st.error("No se pudo contactar al servidor. Revisa que el servicio de Render esté activo.")
        return
    if not nodos:
        st.info("No hay cámaras creadas. Ve a la sección Crear.")
        return

    eventos = api_get("/api/eventos", horas=horas, limit=200) or []

    if "mapa_vista" not in st.session_state:
        centro = [sum(n["lat"] for n in nodos) / len(nodos), sum(n["lon"] for n in nodos) / len(nodos)]
        st.session_state.mapa_vista = {"centro": centro, "zoom": 14 if len(nodos) > 1 else 16}

    base_url, ref_url = MAPA_CLARO if st.session_state.get("claro", False) else MAPA_OSCURO
    vista_mapa_actual = st.session_state.mapa_vista
    mapa = folium.Map(location=vista_mapa_actual["centro"], zoom_start=vista_mapa_actual["zoom"],
                      tiles=base_url, attr=ATRIBUCION_MAPA)
    folium.TileLayer(tiles=ref_url, attr=ATRIBUCION_MAPA, name="Etiquetas",
                     overlay=True, control=False).add_to(mapa)

    for n in nodos:
        estado_txt = "EN VIVO" if n["activo"] else "Sin conexión"
        color_hex = "#00C853" if n["activo"] else "#9E9E9E"
        if n.get("precision_m"):
            folium.Circle(location=[n["lat"], n["lon"]], radius=n["precision_m"],
                          color=color_hex, fill=True, fill_opacity=0.08, weight=1).add_to(mapa)
        popup = f"""
        <div style="font-family:Roboto,Arial,sans-serif;width:240px;color:#000;font-size:15px">
          <div style="font-size:18px;font-weight:700;margin-bottom:6px">{esc(n['id'])}</div>
          <div>Zona: <b>{esc(n['zona'])}</b></div>
          <div>Estado: <b style="color:{color_hex}">{estado_txt}</b></div>
          <div>Batería: {esc(n['bateria'])} {'⚡' if n['cargando'] else ''}</div>
          <div>Velocidad: {esc(n['velocidad'] or 'N/D')} km/h</div>
          <div>Sonido: {esc(n['ultimo_db'] if n['ultimo_db'] is not None else 'N/D')} dB</div>
          <div>FPS: {esc(n['fps'])} · Grabando: {'sí' if n['grabando'] else 'no'}</div>
          <div>GPS: {n['lat']:.5f}, {n['lon']:.5f}</div>
          <div>Última señal: {esc(n['ultima_vez'] or 'N/D')}</div>
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
            tooltip=f"{hora_de(e['fecha'])} · Cámara {e['cam_id']} · {e['razon']}",
        ).add_to(mapa)

    salida = st_folium(mapa, height=520, use_container_width=True,
                       returned_objects=["center", "zoom"], key="mapa")
    if salida and salida.get("center") and salida.get("zoom"):
        st.session_state.mapa_vista = {
            "centro": [salida["center"]["lat"], salida["center"]["lng"]],
            "zoom": salida["zoom"],
        }

    st.markdown(
        '<div class="leyenda">'
        '<span><i style="background:#00C853"></i>Cámara activa</span>'
        '<span><i style="background:#9E9E9E"></i>Sin conexión</span>'
        '<span><i style="background:#FF5252"></i>Posible robo</span>'
        '<span><i style="background:#FFB300"></i>Pico de sonido</span></div>',
        unsafe_allow_html=True)

    tabla = pd.DataFrame(nodos)[["id", "zona", "activo", "bateria", "velocidad", "fps", "ultimo_db", "ultima_vez"]]
    tabla["activo"] = tabla["activo"].map({True: "EN VIVO", False: "Sin conexión"})
    tabla.columns = ["Cámara", "Zona", "Estado", "Batería", "Velocidad km/h", "FPS", "Sonido dB", "Última señal"]
    st.dataframe(tabla, hide_index=True, use_container_width=True)


def vista_eventos():
    st.markdown('<h2>Eventos</h2>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Picos de sonido y movimientos bruscos registrados.</div>',
                unsafe_allow_html=True)

    with st.container(border=True):
        c1, c2 = st.columns(2)
        horas = c1.slider("Últimas horas", 1, 24, 24, key="ev_horas")
        cantidad = c2.slider("Cantidad máxima", 5, 100, 30, key="ev_n")

    eventos = api_get("/api/eventos", horas=horas, limit=cantidad)
    if eventos is None:
        st.error("No se pudo contactar al servidor.")
        return

    robos = sum(1 for e in eventos if e["tipo"] == "robo")
    st.markdown(kpis([("Total", len(eventos)), ("Robos", robos), ("Sonido", len(eventos) - robos)]),
                unsafe_allow_html=True)

    items = [{
        "title": ("🚨 Posible robo" if e["tipo"] == "robo" else "🔊 Pico de sonido") + f" · {e['cam_id']}",
        "description": e["razon"],
        "meta": hora_de(e["fecha"]),
    } for e in eventos]
    with st.container(border=True):
        st.markdown(lista_html(items, "Sin eventos en este periodo."), unsafe_allow_html=True)


def vista_analisis():
    st.markdown('<h2>Análisis</h2>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Eventos registrados por hora del día.</div>', unsafe_allow_html=True)

    nodos = api_get("/api/estado_nodos") or []
    ids = [n["id"] for n in nodos]
    if not ids:
        st.markdown('<div class="aviso">No hay cámaras creadas todavía.</div>', unsafe_allow_html=True)
        return

    with st.container(border=True):
        seleccion = st.selectbox("Cámara", ["Todas"] + ids, key="an_cam")
    cam = None if seleccion == "Todas" else seleccion

    est = api_get("/api/estadisticas", cam_id=cam) or {"por_hora": [], "por_tipo": []}
    tipos = {t["tipo"]: t["total"] for t in est["por_tipo"]}
    st.markdown(kpis([("Sonido", tipos.get("sonido", 0)), ("Robos", tipos.get("robo", 0)),
                      ("Cámaras", len(ids))]), unsafe_allow_html=True)

    base = pd.DataFrame({"hora": [f"{h:02d}" for h in range(24)]})
    datos = pd.DataFrame(est["por_hora"], columns=["hora", "total"])
    df = base.merge(datos, on="hora", how="left").fillna({"total": 0}).set_index("hora")
    df["total"] = df["total"].astype(int)

    with st.container(border=True):
        st.markdown("#### Eventos por hora")
        st.bar_chart(df, color=paleta_actual()["accent"])

    with st.container(border=True):
        st.markdown("#### Últimos eventos")
        eventos = api_get("/api/eventos", cam_id=cam, limit=10) or []
        items = [{
            "title": ("🚨 Posible robo" if e["tipo"] == "robo" else "🔊 Pico de sonido") + f" · {e['cam_id']}",
            "description": e["razon"],
            "meta": hora_de(e["fecha"]),
        } for e in eventos]
        st.markdown(lista_html(items, "Sin eventos registrados."), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Estructura principal
# ---------------------------------------------------------------------------
st.session_state.setdefault("claro", False)
st.markdown(css_tema(paleta_actual()), unsafe_allow_html=True)
alertas_en_vivo()

col_logo, col_tema = st.columns([3, 2])
with col_logo:
    st.markdown(f'<div class="logo">{LOGO_SVG}<span>EcoGuard</span></div>', unsafe_allow_html=True)
with col_tema:
    st.toggle("☀️ Modo claro", key="claro")

OPCIONES = ["Cámara", "Cuadrícula", "Mapa", "Eventos", "Análisis", "Crear"]
seccion = st.radio("Sección", OPCIONES, horizontal=True, label_visibility="collapsed", key="vista")

VISTAS = {
    "Cámara": vista_camara,
    "Cuadrícula": vista_cuadricula,
    "Mapa": vista_mapa,
    "Eventos": vista_eventos,
    "Análisis": vista_analisis,
    "Crear": vista_crear,
}
VISTAS[seccion]()