<<<<<<< HEAD
# EcoGuard - Red de Vigilancia Solar y Comunitaria

Proyecto desarrollado para el **Rally Latinoamericano de Innovación**.

## Ejecución local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:CAMERAS="123:SEC-99,CAM-101:SEC-99"
python server.py                      # terminal 1 (puerto 5000)
$env:ECOGUARD_SERVER_URL="http://localhost:5000"
streamlit run dashboard_visor.py      # terminal 2
```

Abre `http://localhost:5000/cliente` en el teléfono (o en otra pestaña) para iniciar un nodo.
Los navegadores solo dan acceso a cámara, micrófono y sensores en **HTTPS** o `localhost`.

## Despliegue en Render.com

1. Sube el proyecto a GitHub (sin `data/` ni `.venv/`).
2. En Render: **New → Blueprint** y selecciona el repositorio. Usa `render.yaml`.
3. Configura las variables `sync: false`:
   - `CAMERAS` en el servidor (pares `ID:PIN`).
   - `ECOGUARD_SERVER_URL` en el dashboard con la URL `https://…onrender.com` del servidor.
   - `ECOGUARD_PIN_DEFECTO` en el dashboard.
   - `NTFY_URL` (opcional) para recibir notificaciones push de robos en el teléfono.
4. En el teléfono, abre `https://<tu-servidor>.onrender.com/cliente`, escribe ID y PIN, y pulsa **Iniciar nodo**.

## Funciones

- **Video:** hasta 720p, FPS y calidad JPEG que se adaptan a la red; el video viaja en binario.
- **Audio:** escucha en vivo desde el dashboard, con botón de silenciar; el teléfono también puede silenciar su micrófono.
- **Grabación:** fragmentos de 20 s en el teléfono, subidos al servidor y listados en el dashboard.
- **Picos de sonido:** se comparan con la línea base del ambiente; cada evento guarda ID, ubicación, hora y razón.
- **Sensores:** GPS (con precisión), batería, velocidad, orientación, movimiento y luz ambiental (si el navegador la soporta).
- **Movimiento brusco:** se registra como posible intento de robo y, si configuras `NTFY_URL`, envía una notificación push.
- **Mapa:** estado en vivo de cada cámara, ubicación, precisión GPS y eventos de las últimas 24 h.
- **Análisis:** eventos por hora del día, filtrables por cámara.

## Limitaciones importantes

- **Base de datos y grabaciones:** en Render solo persisten con un disco (plan de pago). Sin disco, se pierden al reiniciar.
- **iPhone:** Safari no soporta algunas funciones de grabación (`MediaRecorder` en WebM). El video en vivo funciona, pero la grabación y el audio pueden fallar. Para uso fiable, usa Android con Chrome.
- **Movimiento brusco:** es una heurística. Golpes o manipular el teléfono pueden disparar la alarma; ajusta `umbralMovimiento` en `cliente.html`.
- **Privacidad:** grabar audio y video de personas requiere avisarles y, en México, cumplir la LFPDPPP.
- **Seguridad:** los PIN viajan en la URL del video. Usa PIN largos y cámbialos periódicamente.
=======
# ecoguard
>>>>>>> f368bb51ca6735a616620e234fc7ed54cdc8e10b
