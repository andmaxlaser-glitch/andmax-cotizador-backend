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

# --------------------------------------------------------------------------
# Rutas del Proyecto y Archivos Estáticos
# --------------------------------------------------------------------------
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


def generar_svg_preview(doc, msp) -> str:
    """Genera un SVG seguro extrayendo trayectorias de forma robusta."""
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
                            if getattr(entity, 'closed', False):
                                pts_str.append("Z")
                            paths_data.append(" ".join(pts_str))
                except Exception:
                    continue

        extraer_de_contenedor(msp)
        for block in doc.blocks:
            if not block.name.startswith('*'):
                extraer_de_contenedor(block)

        if not all_points_x or not all_points_y:
            return "<p style='color:#a0a0a0; font-size:12px;'>Sin geometrías compatibles para vista previa</p>"

        min_x, max_x = min(all_points_x), max(all_points_x)
        min_y, max_y = min(all_points_y), max(all_points_y)

        width = max_x - min_x
        height = max_y - min_y

        if width <= 0 or height <= 0:
            return "<p style='color:#a0a0a0; font-size:12px;'>Dimensiones inválidas para renderizado</p>"

        margin = max(width, height) * 0.10
        vb_x = min_x - margin
        vb_y = min_y - margin
        vb_w = width + (margin * 2)
        vb_h = height + (margin * 2)

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

    except Exception as e:
        print(f"Error generando SVG: {e}")
        return "<p style='color:#a0a0a0; font-size:12px;'>Vista previa no disponible</p>"


def enviar_email_notificacion_carrito(email_cliente: str, items_info: list, monto_total: str):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        return

    msg = EmailMessage()
    msg['Subject'] = f'⚡ NUEVO PEDIDO PAGADO ({len(items_info)} archivos) - ANDMAX'
    msg['From'] = SMTP_EMAIL
    msg['To'] = EMAIL_DESTINO

    envio_info = items_info[0].get("datos_envio_cliente", {}) if items_info else {}

    detalle_items_texto = ""
    for idx, item in enumerate(items_info, 1):
        detalle_items_texto += f"""
--- ITEM {idx} ---
• Archivo: {item['original_filename']}
• Material: {item['material'].upper()}
• Espesor: {item['espesor']} mm
• Metros de corte: {item['metros_corte']} m
• Piercings: {item['piercings']}
• Subtotal: ${item['total_estimado']}
"""

    contenido_texto = f"""
¡Hola! Se ha confirmado un nuevo pago en el sistema.

==============================================
DATOS DE CONTACTO Y ENVÍO
==============================================
• Email de Pago: {email_cliente}
• Nombre: {envio_info.get('nombre', 'No especificado')}
• Teléfono: {envio_info.get('telefono', 'No especificado')}
• Tipo de Entrega: {envio_info.get('tipo', 'retiro').upper()}
• Dirección: {envio_info.get('direccion', '-')}
• Localidad: {envio_info.get('localidad', '-')}
• Código Postal: {envio_info.get('cp', '-')}

==============================================
DETALLE DE LAS PIEZAS
==============================================
{detalle_items_texto}
==============================================
Monto Total Abonado: ${monto_total}
"""
    msg.set_content(contenido_texto)

    for item in items_info:
        filepath = item.get("filepath")
        if filepath and os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                file_data = f.read()
                msg.add_attachment(file_data, maintype='application', subtype='dxf', filename=item['original_filename'])

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(SMTP_EMAIL, SMTP_PASSWORD)
            smtp.send_message(msg)
    except Exception as e:
        print(f"Error enviando email de carrito: {e}")


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
    all_points_x = []
    all_points_y = []
    entidades_geom = []
    ENTIDADES_CORTE = {'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'SPLINE', 'ELLIPSE'}

    def extraer_entidades(entidades):
        nonlocal total_length_mm
        for entity in entidades:
            dxftype = entity.dxftype()
            if dxftype == 'INSERT':
                try:
                    if hasattr(entity, 'virtual_entities'):
                        extraer_entidades(entity.virtual_entities())
                except Exception:
                    pass
                continue

            if dxftype not in ENTIDADES_CORTE:
                continue

            try:
                length = 0.0
                pts = []
                is_closed = False

                if dxftype == 'LINE':
                    s, e = entity.dxf.start, entity.dxf.end
                    length = s.distance(e)
                    pts = [(float(s.x), float(s.y)), (float(e.x), float(e.y))]
                elif dxftype == 'CIRCLE':
                    c, r = entity.dxf.center, entity.dxf.radius
                    length = 2 * math.pi * r
                    pts = [(float(c.x - r), float(c.y)), (float(c.x + r), float(c.y)), (float(c.x), float(c.y - r)), (float(c.x), float(c.y + r))]
                    is_closed = True
                elif dxftype in ('LWPOLYLINE', 'POLYLINE'):
                    puntos = list(entity.get_points(format='xy'))
                    length = 0.0
                    for idx, pt in enumerate(puntos):
                        px, py = float(pt[0]), float(pt[1])
                        pts.append((px, py))
                        if idx > 0:
                            length += math.hypot(px - pts[idx-1][0], py - pts[idx-1][1])
                    is_closed = getattr(entity, 'closed', False)
                    if not is_closed and len(pts) > 2:
                        is_closed = math.isclose(pts[0][0], pts[-1][0], abs_tol=1e-2) and math.isclose(pts[0][1], pts[-1][1], abs_tol=1e-2)
                elif dxftype == 'ARC':
                    c, r = entity.dxf.center, entity.dxf.radius
                    sw = math.radians(entity.dxf.end_angle) - math.radians(entity.dxf.start_angle)
                    if sw < 0: sw += 2 * math.pi
                    length = r * sw
                    pts = [(float(c.x - r), float(c.y)), (float(c.x + r), float(c.y))]
                else:
                    p = path.make_path(entity)
                    length = path.length(p)
                    control_pts = list(p.control_points())
                    if control_pts:
                        pts = [(float(pt[0]), float(pt[1])) for pt in control_pts]
                    try:
                        is_closed = p.is_closed()
                    except Exception:
                        pass

                if length > 0 or pts:
                    total_length_mm += length
                    for px, py in pts:
                        all_points_x.append(px)
                        all_points_y.append(py)
                    
                    cx = sum(p[0] for p in pts) / len(pts) if pts else 0.0
                    cy = sum(p[1] for p in pts) / len(pts) if pts else 0.0
                    entidades_geom.append({
                        "type": dxftype,
                        "center": (cx, cy),
                        "is_closed": is_closed,
                        "length": length
                    })
            except Exception:
                pass

    extraer_entidades(msp)
    for block in doc.blocks:
        if not block.name.startswith('*'):
            extraer_entidades(block)

    if not all_points_x or not all_points_y:
        try:
            extmin = doc.header.get('$EXTMIN')
            extmax = doc.header.get('$EXTMAX')
            if extmin and extmax:
                all_points_x = [float(extmin[0]), float(extmax[0])]
                all_points_y = [float(extmin[1]), float(extmax[1])]
        except Exception:
            pass

    if all_points_x and all_points_y:
        ancho_pieza = round(max(all_points_x) - min(all_points_x), 2)
        alto_pieza = round(max(all_points_y) - min(all_points_y), 2)
    else:
        ancho_pieza, alto_pieza = 0.0, 0.0

    componentes = []
    tolerancia_agrupamiento = 15.0

    for ent in entidades_geom:
        c_ent = ent["center"]
        encontrado = False
        for comp in componentes:
            if any(math.hypot(c_ent[0] - e["center"][0], c_ent[1] - e["center"][1]) < tolerancia_agrupamiento for e in comp):
                comp.append(ent)
                encontrado = True
                break
        if not encontrado:
            componentes.append([ent])

    piezas_detectadas = max(1, len(componentes))
    perforaciones_detectadas = sum(1 for e in entidades_geom if e["is_closed"] or e["type"] in ('CIRCLE', 'ARC'))
    perforaciones_detectadas = max(1, perforaciones_detectadas)

    metros_corte = round(total_length_mm / 1000.0, 2)
    precio_metro, costo_mat_unitario = obtener_precio_metro_y_material(material, espesor)

    PRECIO_PIERCING = 50.0
    COSTO_SETUP = 1500.0

    costo_mecanizado = round((metros_corte * precio_metro) + (perforaciones_detectadas * PRECIO_PIERCING), 2)
    costo_material = round(metros_corte * costo_mat_unitario, 2) if incluye_material else 0.0
    total_estimado = round(costo_mecanizado + costo_material + COSTO_SETUP, 2)

    if math.isnan(total_estimado) or math.isinf(total_estimado) or total_estimado <= 0:
        raise ValueError("El cálculo de la cotización generó un valor inválido.")

    svg_preview = generar_svg_preview(doc, msp)

    return {
        "metros_corte": metros_corte,
        "piercings": perforaciones_detectadas,
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
    posibles_html = [
        os.path.join(PROJECT_ROOT, "frontend", "index.html"),
        os.path.join(BASE_DIR, "frontend", "index.html"),
        os.path.join(PROJECT_ROOT, "Frontend", "index.html"),
        os.path.join(BASE_DIR, "Frontend", "index.html"),
        os.path.join(BASE_DIR, "index.html"),
        os.path.join(PROJECT_ROOT, "index.html")
    ]

    for html_path in posibles_html:
        if os.path.exists(html_path):
            return FileResponse(html_path)

    return {
        "status": "Cotizador API ANDMAX Laser activo",
        "error": "No se encontró index.html",
        "rutas_buscadas": posibles_html
    }


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
    return await crear_pago_carrito(item_ids=quote_id, tipo_envio="retiro")


@app.post("/crear_pago_carrito")
async def crear_pago_carrito(
    item_ids: str = Form(...),
    tipo_envio: str = Form("retiro"),  # "retiro", "local" o "correo"
    nombre_envio: str = Form(""),
    telefono_envio: str = Form(""),
    direccion_envio: str = Form(""),
    localidad_envio: str = Form(""),
    cp_envio: str = Form("")
):
    if not sdk:
        raise HTTPException(status_code=500, detail="Mercado Pago SDK no inicializado")

    ids_list = [i.strip() for i in item_ids.split(",") if i.strip()]
    if not ids_list:
        raise HTTPException(status_code=400, detail="El carrito está vacío.")

    items_mp = []
    filepaths_asociados = []
    
    with QUOTES_LOCK:
        for qid in ids_list:
            quote = QUOTES.get(qid)
            if not quote:
                raise HTTPException(status_code=404, detail="Una de las cotizaciones expiró o no existe. Volvé a cargar los archivos.")
            if quote["used"]:
                raise HTTPException(status_code=409, detail=f"El archivo {quote['original_filename']} ya fue procesado en otro pago.")
            
            items_mp.append({
                "title": f"Corte: {quote['original_filename']} ({quote['material']} {quote['espesor']}mm)",
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": float(quote["total_estimado"])
            })
            filepaths_asociados.append(qid)

    # Calcular costo de envío dinámico según la opción seleccionada
    costo_envio = 0.0
    titulo_envio = ""
    texto_envio_resumen = "Retira por el local"

    if tipo_envio == "local":
        costo_envio = 5000.0
        titulo_envio = "Envío Local / GBA"
        texto_envio_resumen = f"Envío Local | Dir: {direccion_envio}, {localidad_envio} (CP: {cp_envio})"
    elif tipo_envio == "correo":
        costo_envio = 12000.0
        titulo_envio = "Envío al Interior - Correo Argentino"
        texto_envio_resumen = f"Correo Argentino | Dir: {direccion_envio}, {localidad_envio} (CP: {cp_envio})"

    if costo_envio > 0:
        items_mp.append({
            "title": titulo_envio,
            "quantity": 1,
            "currency_id": "ARS",
            "unit_price": costo_envio
        })

    cart_reference_id = ",".join(filepaths_asociados)

    preference_data = {
        "items": items_mp,
        "external_reference": cart_reference_id,
        "notification_url": "https://andmax-cotizador-api.onrender.com/webhook"
    }

    try:
        preference_response = sdk.preference().create(preference_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con la pasarela de pagos: {str(e)}")

    if preference_response.get("status") not in [200, 201]:
        raise HTTPException(status_code=400, detail="Error al crear la preferencia de pago conjunta")

    preference = preference_response["response"]
    
    with QUOTES_LOCK:
        for qid in filepaths_asociados:
            QUOTES[qid]["used"] = True
            QUOTES[qid]["datos_envio_cliente"] = {
                "tipo": tipo_envio,
                "nombre": nombre_envio,
                "telefono": telefono_envio,
                "direccion": direccion_envio,
                "localidad": localidad_envio,
                "cp": cp_envio,
                "resumen": texto_envio_resumen
            }

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
                    external_ref = payment_info.get("external_reference", "")
                    monto_total = str(payment_info.get("transaction_amount", "0"))
                    email_cliente = payment_info.get("payer", {}).get("email", "No especificado")

                    quote_ids = [qid.strip() for qid in external_ref.split(",") if qid.strip()]
                    
                    items_encontrados = []
                    with QUOTES_LOCK:
                        for qid in quote_ids:
                            quote = QUOTES.get(qid)
                            if quote:
                                items_encontrados.append(quote)

                    if items_encontrados:
                        enviar_email_notificacion_carrito(
                            email_cliente=email_cliente,
                            items_info=items_encontrados,
                            monto_total=monto_total
                        )
            except Exception as e:
                print(f"Error procesando webhook de pago: {e}")

    return {"status": "ok"}
