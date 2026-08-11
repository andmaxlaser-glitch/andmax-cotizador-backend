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
from ezdxf import path

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

RUTAS_FRONTEND_POSIBLES = [
    os.path.join(PROJECT_ROOT, "frontend"),
    os.path.join(BASE_DIR, "frontend"),
    os.path.join(PROJECT_ROOT, "Frontend"),
    os.path.join(BASE_DIR, "Frontend"),
]

FRONTEND_DIR = None
for ruta in RUTAS_FRONTEND_POSIBLES:
    if os.path.exists(ruta):
        FRONTEND_DIR = ruta
        break

static_dir = None
if FRONTEND_DIR and os.path.exists(os.path.join(FRONTEND_DIR, "static")):
    static_dir = os.path.join(FRONTEND_DIR, "static")
elif os.path.exists(os.path.join(BASE_DIR, "static")):
    static_dir = os.path.join(BASE_DIR, "static")

if static_dir and os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

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


def generar_svg_preview(doc, msp) -> str:
    try:
        paths_data = []
        all_points_x = []
        all_points_y = []

        def extraer_de_contenedor(entidades):
            for entity in entidades:
                dxftype = entity.dxftype()
                if dxftype == 'INSERT':
                    try:
                        if hasattr(entity, 'virtual_entities'):
                            extraer_de_contenedor(entity.virtual_entities())
                    except Exception:
                        pass
                    continue

                try:
                    p = path.make_path(entity)
                    d_str = path.to_svg_path_data([p])
                    if d_str and d_str.strip():
                        paths_data.append(d_str)
                        for pt in p.control_points():
                            all_points_x.append(float(pt[0]))
                            all_points_y.append(float(pt[1]))
                except Exception:
                    pass

                try:
                    if dxftype == 'LINE':
                        s, e = entity.dxf.start, entity.dxf.end
                        all_points_x.extend([s.x, e.x])
                        all_points_y.extend([s.y, e.y])
                        paths_data.append(f"M {s.x:.2f} {s.y:.2f} L {e.x:.2f} {e.y:.2f}")
                    elif dxftype == 'CIRCLE':
                        c, r = entity.dxf.center, entity.dxf.radius
                        all_points_x.extend([c.x - r, c.x + r])
                        all_points_y.extend([c.y - r, c.y + r])
                        paths_data.append(f"M {c.x - r:.2f} {c.y:.2f} A {r:.2f} {r:.2f} 0 1 0 {c.x + r:.2f} {c.y:.2f} A {r:.2f} {r:.2f} 0 1 0 {c.x - r:.2f} {c.y:.2f}")
                    elif dxftype in ('LWPOLYLINE', 'POLYLINE'):
                        puntos = list(entity.get_points(format='xy'))
                        if puntos:
                            pts_str = []
                            for idx, pt in enumerate(puntos):
                                px, py = float(pt[0]), float(pt[1])
                                all_points_x.append(px)
                                all_points_y.append(py)
                                prefix = "M" if idx == 0 else "L"
                                pts_str.append(f"{prefix} {px:.2f} {py:.2f}")
                            if entity.closed:
                                pts_str.append("Z")
                            paths_data.append(" ".join(pts_str))
                except Exception:
                    continue

        extraer_de_contenedor(msp)
        for block in doc.blocks:
            if not block.name.startswith('*'):
                extraer_de_contenedor(block)

        if not all_points_x or not all_points_y:
            return "<p style='color:#a0a0a0; font-size:12px;'>Sin geometrías compatibles</p>"

        min_x, max_x = min(all_points_x), max(all_points_x)
        min_y, max_y = min(all_points_y), max(all_points_y)
        width, height = max_x - min_x, max_y - min_y

        if width <= 0 or height <= 0:
            return "<p style='color:#a0a0a0; font-size:12px;'>Dimensiones inválidas</p>"

        margin = max(width, height) * 0.10
        vb_x, vb_y = min_x - margin, min_y - margin
        vb_w, vb_h = width + (margin * 2), height + (margin * 2)
        stroke_width = max(max(width, height) / 220.0, 0.4)

        paths_svg = [
            f'<path d="{d}" stroke="#e63946" stroke-width="{stroke_width:.2f}" fill="none" stroke-linecap="round" stroke-linejoin="round" />'
            for d in paths_data
        ]
        center_y = min_y + max_y

        return f'''<svg viewBox="{vb_x:.2f} {vb_y:.2f} {vb_w:.2f} {vb_h:.2f}" 
            xmlns="http://www.w3.org/2000/svg" 
            style="width: 100%; height: 280px; background-color: #0d0d0d; border-radius: 6px; display: block;"
            preserveAspectRatio="xMidYMid meet">
            <g transform="translate(0, {center_y:.2f}) scale(1, -1)">
                {''.join(paths_svg)}
            </g>
        </svg>'''
    except Exception:
        return "<p style='color:#a0a0a0; font-size:12px;'>Vista previa no disponible</p>"


def obtener_precio_metro_y_material(material_input: str, espesor_input: str) -> tuple[float, float]:
    TARIFAS_CORTE = {
        "mdf": {1.0: 600.0, 2.0: 700.0, 3.0: 800.0, 5.0: 900.0, 8.0: 1000.0, 10.0: 1200.0},
        "acrilico": {1.0: 800.0, 2.0: 900.0, 3.0: 1000.0, 4.0: 1100.0, 5.0: 1200.0, 6.0: 1400.0, 8.0: 1600.0, 10.0: 1800.0},
        "acero_carbono": {1.0: 8500.0, 2.0: 9350.0, 3.0: 10285.0, 4.0: 11313.0, 5.0: 12444.0, 6.0: 13689.0, 8.0: 15058.0, 10.0: 16564.0, 12.0: 18220.0},
        "acero_inoxidable": {1.0: 9500.0, 2.0: 11500.0, 3.0: 14945.0, 4.0: 16500.0, 5.0: 18500.0, 6.0: 17934.0, 8.0: 21000.0, 10.0: 24000.0, 12.0: 27000.0},
        "aluminio": {1.0: 8500.0, 2.0: 9350.0, 3.0: 10285.0, 4.0: 11313.0, 5.0: 12444.0, 6.0: 13689.0, 8.0: 15058.0, 10.0: 16564.0, 12.0: 18220.0}
    }
    COSTOS_MATERIAL_BASE = {
        "mdf": 800.0, "acrilico": 1200.0, "acero_carbono": 3500.0, "acero_inoxidable": 6500.0, "aluminio": 4500.0
    }

    mat_str = str(material_input).lower().strip()
    if "inox" in mat_str: mat_key = "acero_inoxidable"
    elif "carbono" in mat_str or "hierro" in mat_str: mat_key = "acero_carbono"
    elif "acril" in mat_str: mat_key = "acrilico"
    elif "alum" in mat_str: mat_key = "aluminio"
    else: mat_key = "mdf"

    raw_esp = str(espesor_input).replace(",", ".").strip()
    esp_clean = "".join([c for c in raw_esp if c.isdigit() or c == '.'])
    espesor_val = float(esp_clean) if esp_clean else 3.0

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
    ENTIDADES_CORTE = {'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'SPLINE', 'ELLIPSE'}
    entidades_totales = []
    all_points_x = []
    all_points_y = []

    def procesar_para_cotizar(entidades):
        nonlocal total_length_mm, entidades_totales
        for entity in entidades:
            dxftype = entity.dxftype()
            if dxftype == 'INSERT':
                try:
                    if hasattr(entity, 'virtual_entities'):
                        procesar_para_cotizar(entity.virtual_entities())
                except Exception:
                    pass
                continue

            if dxftype not in ENTIDADES_CORTE:
                continue

            entidades_totales.append(entity)
            try:
                p = path.make_path(entity)
                total_length_mm += path.length(p)
                for pt in p.control_points():
                    all_points_x.append(float(pt[0]))
                    all_points_y.append(float(pt[1]))
            except Exception:
                if dxftype == 'LINE':
                    s, e = entity.dxf.start, entity.dxf.end
                    total_length_mm += s.distance(e)
                    all_points_x.extend([s.x, e.x])
                    all_points_y.extend([s.y, e.y])
                elif dxftype == 'CIRCLE':
                    c, r = entity.dxf.center, entity.dxf.radius
                    total_length_mm += 2 * math.pi * r
                    all_points_x.extend([c.x - r, c.x + r])
                    all_points_y.extend([c.y - r, c.y + r])

    procesar_para_cotizar(msp)
    for block in doc.blocks:
        if not block.name.startswith('*'):
            procesar_para_cotizar(block)

    # Dimensiones (Ancho x Alto)
    if all_points_x and all_points_y:
        ancho_pieza = round(max(all_points_x) - min(all_points_x), 2)
        alto_pieza = round(max(all_points_y) - min(all_points_y), 2)
    else:
        ancho_pieza, alto_pieza = 0.0, 0.0

    poligonos_cerrados = sum(1 for e in entidades_totales if e.dxftype() in ('LWPOLYLINE', 'POLYLINE') and getattr(e, 'closed', False))
    circulos_count = sum(1 for e in entidades_totales if e.dxftype() == 'CIRCLE')
    piezas_detectadas = max(1, poligonos_cerrados if poligonos_cerrados > 0 else (circulos_count if circulos_count > 0 else 1))

    arcos_count = sum(1 for e in entidades_totales if e.dxftype() == 'ARC')
    piercings = max(1, circulos_count + poligonos_cerrados + arcos_count)

    metros_corte = round(total_length_mm / 1000.0, 2)
    precio_metro, costo_mat_unitario = obtener_precio_metro_y_material(material, espesor)

    PRECIO_PIERCING = 50.0
    COSTO_SETUP = 1500.0

    costo_mecanizado = round((metros_corte * precio_metro) + (piercings * PRECIO_PIERCING), 2)
    costo_material = round(metros_corte * costo_mat_unitario, 2) if incluye_material else 0.0
    total_estimado = round(costo_mecanizado + costo_material + COSTO_SETUP, 2)

    svg_preview = generar_svg_preview(doc, msp)

    return {
        "metros_corte": metros_corte,
        "piercings": piercings,
        "ancho_mm": ancho_pieza,
        "alto_mm": alto_pieza,
        "piezas_detectadas": piezas_detectadas,
        "precio_metro_aplicado": precio_metro,
        "costo_mecanizado": costo_mecanizado,
        "costo_material": costo_material,
        "costo_setup": COSTO_SETUP,
        "total_estimado": total_estimado,
        "svg_preview": svg_preview,
    }


@app.get("/")
async def read_root():
    for html_path in [
        os.path.join(PROJECT_ROOT, "frontend", "index.html"),
        os.path.join(BASE_DIR, "frontend", "index.html"),
        os.path.join(BASE_DIR, "index.html")
    ]:
        if os.path.exists(html_path):
            return FileResponse(html_path)
    return {"error": "index.html no encontrado"}


@app.post("/cotizar")
async def cotizar(
    file: UploadFile = File(...),
    material: str = Form("mdf"),
    espesor: str = Form("3"),
    incluye_material: bool = Form(True)
):
    _limpiar_cotizaciones_viejas()
    original_filename = file.filename or "archivo.dxf"
    safe_name = nombre_archivo_seguro(original_filename)
    temp_filepath = os.path.join(TEMP_DIR, safe_name)

    size = 0
    with open(temp_filepath, "wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_SIZE_BYTES:
                buffer.close()
                os.remove(temp_filepath)
                raise HTTPException(status_code=413, detail="Archivo demasiado grande")
            buffer.write(chunk)

    try:
        resultado = calcular_cotizacion(temp_filepath, material, espesor, incluye_material)
    except Exception as e:
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)
        raise HTTPException(status_code=400, detail=f"Error procesando DXF: {str(e)}")

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

    return {"quote_id": quote_id, "archivo": original_filename, **resultado, "material": material, "espesor": espesor}


@app.post("/crear_pago")
async def crear_pago(quote_id: str = Form(...)):
    if not sdk:
        raise HTTPException(status_code=500, detail="Mercado Pago SDK no inicializado")

    with QUOTES_LOCK:
        quote = QUOTES.get(quote_id)

    if not quote or quote["used"]:
        raise HTTPException(status_code=404, detail="Cotización inválida o ya utilizada.")

    preference_data = {
        "items": [{
            "title": f"Corte Láser DXF: {quote['original_filename']}",
            "quantity": 1,
            "currency_id": "ARS",
            "unit_price": float(quote["total_estimado"])
        }],
        "external_reference": quote_id,
        "notification_url": "https://andmax-cotizador-api.onrender.com/webhook"
    }

    try:
        pref = sdk.preference().create(preference_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    with QUOTES_LOCK:
        QUOTES[quote_id]["used"] = True

    return {"init_point": pref["response"]["init_point"]}
