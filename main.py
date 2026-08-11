import os
import re
import time
import uuid
import shutil
import smtplib
import math
from threading import Lock
from email.message import EmailMessage
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import mercadopago
import ezdxf
from ezdxf import path, bbox

app = FastAPI()

# Directorio base del proyecto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# Archivos Estáticos e Interfaz Web
# --------------------------------------------------------------------------
static_dir = os.path.join(BASE_DIR, "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
sdk = mercadopago.SDK(MP_ACCESS_TOKEN) if MP_ACCESS_TOKEN else None

SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO", SMTP_EMAIL)

TEMP_DIR = "/tmp/dxf_storage"
os.makedirs(TEMP_DIR, exist_ok=True)

MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
ALLOWED_EXTENSIONS = {".dxf"}

# --------------------------------------------------------------------------
# Almacén de cotizaciones en memoria
# --------------------------------------------------------------------------
QUOTES: dict[str, dict] = {}
QUOTES_LOCK = Lock()
QUOTE_TTL_SECONDS = 60 * 60 * 2  # 2 horas


def _limpiar_cotizaciones_viejas():
    ahora = time.time()
    with QUOTES_LOCK:
        vencidas = [qid for qid, q in QUOTES.items() if ahora - q["created_at"] > QUOTE_TTL_SECONDS]
        for qid in vencidas:
            filepath = QUOTES[qid].get("filepath")
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            QUOTES.pop(qid, None)


def nombre_archivo_seguro(filename: str) -> str:
    base = os.path.basename(filename or "archivo.dxf")
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", base)
    if not base.lower().endswith(".dxf"):
        base += ".dxf"
    return f"{uuid.uuid4().hex}_{base}"


def generar_svg_preview(msp) -> str:
    """Genera un string SVG vectorial a partir del ModelSpace del DXF."""
    try:
        extents = bbox.extents(msp)
        if not extents.has_data:
            return "<p style='color:#a0a0a0;'>DXF sin vectores visibles</p>"

        min_x, min_y = extents.extmin.x, extents.extmin.y
        max_x, max_y = extents.extmax.x, extents.extmax.y

        width = max_x - min_x
        height = max_y - min_y

        if width <= 0 or height <= 0:
            return "<p style='color:#a0a0a0;'>Dimensiones de archivo no válidas</p>"

        margin = max(width, height) * 0.05
        vb_x = min_x - margin
        vb_y = min_y - margin
        vb_w = width + (margin * 2)
        vb_h = height + (margin * 2)

        paths_svg = []
        ENTIDADES_CORTE = {'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'SPLINE', 'ELLIPSE'}

        stroke_width = max(width, height) / 250.0

        for entity in msp:
            if entity.dxftype() in ENTIDADES_CORTE:
                try:
                    p = path.make_path(entity)
                    d_str = path.to_svg_path_data([p])
                    paths_svg.append(f'<path d="{d_str}" fill="none" stroke="#e63946" stroke-width="{stroke_width:.2f}" stroke-linecap="round" />')
                except Exception:
                    continue

        svg_code = f'''<svg viewBox="{vb_x} {vb_y} {vb_w} {vb_h}" style="width:100%; height:100%; max-height:160px; transform: scaleY(-1);" xmlns="http://www.w3.org/2000/svg">
            <g>
                {''.join(paths_svg)}
            </g>
        </svg>'''
        return svg_code

    except Exception as e:
        print(f"Error generando SVG: {e}")
        return "<p style='color:#a0a0a0;'>Vista previa no disponible</p>"


def enviar_email_notificacion(email_cliente: str, filepath: str, material: str, espesor: str, metros: str, piercings: str, monto: str):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        return

    msg = EmailMessage()
    msg['Subject'] = f'⚡ NUEVO PEDIDO DE CORTE PAGADO: {material.upper()} {espesor}mm'
    msg['From'] = SMTP_EMAIL
    msg['To'] = EMAIL_DESTINO

    contenido_texto = f"""
¡Hola! Se ha confirmado un nuevo pago de corte láser.

==============================================
DETALLE DEL TRABAJO DE CORTE
==============================================
• Material: {material.upper()}
• Espesor: {espesor} mm
• Metros de corte calculados: {metros} m
• Perforaciones (Piercings): {piercings}
• Monto Total Abonado: ${monto}
• Cliente Contacto/Email: {email_cliente}
==============================================
"""
    msg.set_content(contenido_texto)

    if os.path.exists(filepath):
        filename = os.path.basename(filepath)
        with open(filepath, 'rb') as f:
            file_data = f.read()
            msg.add_attachment(file_data, maintype='application', subtype='dxf', filename=filename)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(SMTP_EMAIL, SMTP_PASSWORD)
            smtp.send_message(msg)
    except Exception as e:
        print(f"Error enviando email: {e}")


def obtener_precio_metro_y_material(material_input: str, espesor_input: str) -> tuple[float, float]:
    TARIFAS_CORTE = {
        "mdf": {1.0: 600.0, 2.0: 700.0, 3.0: 800.0, 5.0: 900.0, 8.0: 1000.0, 10.0: 1200.0},
        "acrilico": {1.0: 800.0, 2.0: 900.0, 3.0: 1000.0, 4.0: 1100.0, 5.0: 1200.0, 6.0: 1400.0, 8.0: 1600.0, 10.0: 1800.0},
        "acero_carbono": {1.0: 8500.0, 2.0: 9350.0, 3.0: 10285.0, 4.0: 11313.0, 5.0: 12444.0, 6.0: 13689.0, 8.0: 15058.0, 10.0: 16564.0, 12.0: 18220.0},
        "acero_inoxidable": {1.0: 9500.0, 2.0: 11500.0, 3.0: 14945.0, 4.0: 16500.0, 5.0: 18500.0, 6.0: 17934.0, 8.0: 21000.0, 10.0: 24000.0, 12.0: 27000.0},
        "aluminio": {1.0: 8500.0, 2.0: 9350.0, 3.0: 10285.0, 4.0: 11313.0, 5.0: 12444.0, 6.0: 13689.0, 8.0: 15058.0, 10.0: 16564.0, 12.0: 18220.0}
    }

    COSTOS_MATERIAL_BASE = {
        "mdf": 800.0,
        "acrilico": 1200.0,
        "acero_carbono": 3500.0,
        "acero_inoxidable": 6500.0,
        "aluminio": 4500.0
    }

    mat_str = str(material_input).lower().strip()
    if "inox" in mat_str: mat_key = "acero_inoxidable"
    elif "carbono" in mat_str or "hierro" in mat_str: mat_key = "acero_carbono"
    elif "acril" in mat_str: mat_key = "acrilico"
    elif "alum" in mat_str: mat_key = "aluminio"
    else: mat_key = "mdf"

    raw_esp = str(espesor_input).replace(",", ".").strip()
    esp_clean = "".join([c for c in raw_esp if c.isdigit() or c == '.'])
    try: 
        espesor_val = float(esp_clean)
    except ValueError: 
        espesor_val = 3.0

    tarifas_mat = TARIFAS_CORTE[mat_key]
    if espesor_val in tarifas_mat: 
        precio_corte = tarifas_mat[espesor_val]
    else:
        espesores = sorted(tarifas_mat.keys())
        precio_corte = tarifas_mat[espesores[-1]]
        for esp in espesores:
            if esp >= espesor_val: 
                precio_corte = tarifas_mat[esp]
                break

    precio_material = COSTOS_MATERIAL_BASE[mat_key] * (espesor_val / 3.0)
    
    return float(precio_corte), float(round(precio_material, 2))


def calcular_cotizacion(filepath: str, material: str, espesor: str, incluye_material: bool) -> dict:
    doc = ezdxf.readfile(filepath)
    msp = doc.modelspace()

    total_length_mm = 0.0
    piercings = 0
    ENTIDADES_CORTE = {'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'SPLINE', 'ELLIPSE'}

    for entity in msp:
        dxftype = entity.dxftype()
        if dxftype not in ENTIDADES_CORTE:
            continue
        piercings += 1
        try:
            p = path.make_path(entity)
            total_length_mm += path.length(p)
        except Exception:
            if dxftype == 'LINE':
                total_length_mm += entity.dxf.start.distance(entity.dxf.end)
            elif dxftype == 'CIRCLE':
                total_length_mm += 2 * math.pi * entity.dxf.radius

    metros_corte = round(total_length_mm / 1000.0, 2)
    precio_metro, costo_mat_unitario = obtener_precio_metro_y_material(material, espesor)

    PRECIO_PIERCING = 50.0
    COSTO_SETUP = 1500.0

    costo_mecanizado = round((metros_corte * precio_metro) + (piercings * PRECIO_PIERCING), 2)
    costo_material = round(metros_corte * costo_mat_unitario, 2) if incluye_material else 0.0
    total_estimado = round(costo_mecanizado + costo_material + COSTO_SETUP, 2)

    if math.isnan(total_estimado) or math.isinf(total_estimado) or total_estimado <= 0:
        raise ValueError("El cálculo de la cotización generó un valor inválido.")

    svg_preview = generar_svg_preview(msp)

    return {
        "metros_corte": metros_corte,
        "piercings": piercings,
        "precio_metro_aplicado": precio_metro,
        "costo_mecanizado": costo_mecanizado,
        "costo_material": costo_material,
        "costo_setup": COSTO_SETUP,
        "total_estimado": total_estimado,
        "svg_preview": svg_preview,
    }


@app.get("/")
async def read_root():
    """Servir index.html si existe en la raíz del proyecto."""
    html_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"status": "Cotizador API ANDMAX Laser activo (Falta index.html en la raíz)"}


@app.post("/cotizar")
async def cotizar(
    file: UploadFile = File(...),
    material: str = Form("mdf"),
    espesor: str = Form("3"),
    incluye_material: bool = Form(True)
):
    _limpiar_cotizaciones_viejas()

    original_filename = file.filename or "archivo.dxf"
    if not original_filename.lower().endswith(".dxf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos .dxf")

    safe_name = nombre_archivo_seguro(original_filename)
    temp_filepath = os.path.join(TEMP_DIR, safe_name)

    size = 0
    with open(temp_filepath, "wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_SIZE_BYTES:
                buffer.close()
                os.remove(temp_filepath)
                raise HTTPException(status_code=413, detail="Archivo demasiado grande (máx. 15MB)")
            buffer.write(chunk)

    try:
        resultado = calcular_cotizacion(temp_filepath, material, espesor, incluye_material)
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)
        raise HTTPException(status_code=400, detail=f"No se pudo procesar el archivo DXF: {str(e)}")

    quote_id = uuid.uuid4().hex
    with QUOTES_LOCK:
        QUOTES[quote_id] = {
            "created_at": time.time(),
            "filepath": temp_filepath,
            "original_filename": original_filename,
            "material": material,
            "espesor": espesor,
            "incluye_material": incluye_material,
            "total_estimado": resultado["total_estimado"],
            "metros_corte": resultado["metros_corte"],
            "piercings": resultado["piercings"],
            "used": False,
        }

    return {
        "quote_id": quote_id,
        "archivo": original_filename,
        **resultado,
        "material": material,
        "espesor": espesor,
    }


@app.post("/crear_pago")
async def crear_pago(quote_id: str = Form(...)):
    if not sdk:
        raise HTTPException(status_code=500, detail="Mercado Pago SDK no inicializado")

    with QUOTES_LOCK:
        quote = QUOTES.get(quote_id)

    if not quote:
        raise HTTPException(status_code=404, detail="Cotización no encontrada o vencida. Volvé a subir el archivo.")
    if quote["used"]:
        raise HTTPException(status_code=409, detail="Esta cotización ya generó un pago.")

    monto = float(quote["total_estimado"])
    titulo = quote["original_filename"]

    external_data = f"{quote_id}"

    preference_data = {
        "items": [
            {
                "title": f"Corte Láser DXF: {titulo}",
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": float(monto)
            }
        ],
        "external_reference": external_data,
        "notification_url": "https://andmax-cotizador-api.onrender.com/webhook"
    }

    try:
        preference_response = sdk.preference().create(preference_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con la pasarela de pagos: {str(e)}")

    if preference_response.get("status") not in [200, 201]:
        raise HTTPException(status_code=400, detail="Error al crear la preferencia de pago en Mercado Pago")

    with QUOTES_LOCK:
        QUOTES[quote_id]["used"] = True

    preference = preference_response["response"]
    return {"init_point": preference["init_point"]}


@app.post("/webhook")
async def webhook(request: Request):
    query_params = request.query_params
    topic = query_params.get("topic") or query_params.get("type")

    if topic == "payment":
        payment_id = query_params.get("id") or query_params.get("data.id")
        if payment_id and sdk:
            try:
                payment_response = sdk.payment().get(payment_id)
                payment_info = payment_response.get("response", {})

                if payment_info.get("status") == "approved":
                    quote_id = payment_info.get("external_reference", "")
                    with QUOTES_LOCK:
                        quote = QUOTES.get(quote_id)

                    if quote:
                        monto = payment_info.get("transaction_amount", quote["total_estimado"])
                        email_cliente = payment_info.get("payer", {}).get("email", "No especificado")

                        enviar_email_notificacion(
                            email_cliente=email_cliente,
                            filepath=quote["filepath"],
                            material=quote["material"],
                            espesor=quote["espesor"],
                            metros=str(quote["metros_corte"]),
                            piercings=str(quote["piercings"]),
                            monto=str(monto)
                        )
            except Exception as e:
                print(f"Error procesando webhook de pago: {e}")

    return {"status": "ok"}
    <!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ANDMAX Laser - Cotizador Online</title>
    <style>
        :root {
            --bg-color: #121212;
            --card-bg: #1e1e1e;
            --accent: #e63946;
            --text: #f1f1f1;
            --text-muted: #a0a0a0;
            --border: #333;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg-color);
            color: var(--text);
            margin: 0;
            padding: 20px;
            display: flex;
            justify-content: center;
        }
        .container {
            max-width: 500px;
            width: 100%;
            background: var(--card-bg);
            padding: 24px;
            border-radius: 12px;
            border: 1px solid var(--border);
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        }
        h1 { font-size: 1.4rem; text-align: center; margin-bottom: 20px; color: var(--accent); }
        .form-group { margin-bottom: 16px; }
        label { display: block; font-size: 0.9rem; margin-bottom: 6px; color: var(--text-muted); }
        select, input[type="file"], input[type="text"] {
            width: 100%;
            padding: 10px;
            border-radius: 6px;
            border: 1px solid var(--border);
            background: #2a2a2a;
            color: var(--text);
            box-sizing: border-box;
        }
        .checkbox-group { display: flex; align-items: center; gap: 8px; }
        .checkbox-group input { width: auto; }
        button {
            width: 100%;
            padding: 12px;
            background: var(--accent);
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 1rem;
            font-weight: bold;
            cursor: pointer;
            margin-top: 10px;
        }
        button:hover { opacity: 0.9; }
        button:disabled { background: #555; cursor: not-allowed; }
        #result { margin-top: 20px; padding: 16px; background: #252525; border-radius: 8px; display: none; }
        #preview { margin-top: 12px; background: #000; border-radius: 6px; padding: 10px; text-align: center; }
        .price { font-size: 1.5rem; color: #4caf50; font-weight: bold; text-align: center; margin: 12px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>ANDMAX LASER - Cotizador</h1>
        <form id="quoteForm">
            <div class="form-group">
                <label for="file">Archivo DXF:</label>
                <input type="file" id="file" name="file" accept=".dxf" required>
            </div>
            <div class="form-group">
                <label for="material">Material:</label>
                <select id="material" name="material">
                    <option value="acero_inoxidable">Acero Inoxidable (316/L, 304)</option>
                    <option value="acero_carbono">Acero al Carbono / Hierro</option>
                    <option value="aluminio">Aluminio</option>
                    <option value="mdf">MDF</option>
                    <option value="acrilico">Acrílico</option>
                </select>
            </div>
            <div class="form-group">
                <label for="espesor">Espesor (mm):</label>
                <select id="espesor" name="espesor">
                    <option value="1">1.0 mm</option>
                    <option value="2">2.0 mm</option>
                    <option value="3" selected>3.0 mm</option>
                    <option value="4">4.0 mm</option>
                    <option value="5">5.0 mm</option>
                    <option value="6">6.0 mm</option>
                    <option value="8">8.0 mm</option>
                    <option value="10">10.0 mm</option>
                </select>
            </div>
            <div class="form-group checkbox-group">
                <input type="checkbox" id="incluye_material" name="incluye_material" checked>
                <label for="incluye_material" style="margin:0;">Incluir provisión de material</label>
            </div>
            <button type="submit" id="btnCotizar">Calcular Cotización</button>
        </form>

        <div id="result">
            <div id="preview"></div>
            <p><strong>Metros de corte:</strong> <span id="resMetros"></span> m</p>
            <p><strong>Perforaciones:</strong> <span id="resPiercings"></span></p>
            <div class="price">$<span id="resTotal"></span> ARS</div>
            <button id="btnPagar" style="background:#009ee3;">Pagar con Mercado Pago</button>
        </div>
    </div>

    <script>
        let currentQuoteId = null;

        document.getElementById('quoteForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = document.getElementById('btnCotizar');
            btn.disabled = true;
            btn.innerText = 'Procesando DXF...';

            const formData = new FormData();
            formData.append('file', document.getElementById('file').files[0]);
            formData.append('material', document.getElementById('material').value);
            formData.append('espesor', document.getElementById('espesor').value);
            formData.append('incluye_material', document.getElementById('incluye_material').checked);

            try {
                const res = await fetch('/cotizar', { method: 'POST', body: formData });
                const data = await res.json();

                if (!res.ok) throw new Error(data.detail || 'Error en el servidor');

                currentQuoteId = data.quote_id;
                document.getElementById('resMetros').innerText = data.metros_corte;
                document.getElementById('resPiercings').innerText = data.piercings;
                document.getElementById('resTotal').innerText = data.total_estimado.toLocaleString('es-AR');
                document.getElementById('preview').innerHTML = data.svg_preview;
                document.getElementById('result').style.display = 'block';
            } catch (err) {
                alert('Error: ' + err.message);
            } finally {
                btn.disabled = false;
                btn.innerText = 'Calcular Cotización';
            }
        });

        document.getElementById('btnPagar').addEventListener('click', async () => {
            if (!currentQuoteId) return;
            const btn = document.getElementById('btnPagar');
            btn.disabled = true;
            btn.innerText = 'Generando link de pago...';

            const formData = new FormData();
            formData.append('quote_id', currentQuoteId);

            try {
                const res = await fetch('/crear_pago', { method: 'POST', body: formData });
                const data = await res.json();

                if (!res.ok) throw new Error(data.detail || 'Error al generar el pago');

                window.location.href = data.init_point;
            } catch (err) {
                alert('Error: ' + err.message);
                btn.disabled = false;
                btn.innerText = 'Pagar con Mercado Pago';
            }
        });
    </script>
</body>
</html>
