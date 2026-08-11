import os
import shutil
import smtplib
from email.message import EmailMessage
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import mercurypago
import ezdxf

app = FastAPI()

# Permitir solicitudes desde el Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración de Mercado Pago
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
sdk = mercurypago.SDK(MP_ACCESS_TOKEN) if MP_ACCESS_TOKEN else None

# Configuración de credenciales de Email
SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO", SMTP_EMAIL)

# Carpeta temporal para almacenar archivos DXF antes de la confirmación del pago
TEMP_DIR = "/tmp/dxf_storage"
os.makedirs(TEMP_DIR, exist_ok=True)


def enviar_email_notificacion(email_cliente: str, filepath: str, material: str, espesor: str, metros: str, piercings: str, monto: str):
    """Envía un correo con el archivo DXF adjunto y las especificaciones del corte."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print("❌ Error: No se configuraron las variables SMTP_EMAIL o SMTP_PASSWORD.")
        return

    msg = EmailMessage()
    msg['Subject'] = f'⚡ NUEVO PEDIDO DE CORTE PAGADO: {material.upper()} {espesor}mm'
    msg['From'] = SMTP_EMAIL
    msg['To'] = EMAIL_DESTINO

    contenido_texto = f"""
¡Hola! Se ha confirmado un nuevo pago y el trabajo está listo para ingresar a máquina.

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

El archivo .DXF original se encuentra adjunto en este correo listo para enviar al software de la máquina láser.
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
        print("✅ Correo enviado exitosamente con el adjunto DXF.")
    except Exception as e:
        print(f"❌ Error al enviar el correo vía SMTP: {e}")


def obtener_precio_metro(material_input: str, espesor_input: str) -> float:
    """
    Mapea el material y espesor recibidos desde el frontend a la tarifa correspondiente por metro lineal.
    """
    TARIFAS = {
        "mdf": {
            1.0: 600.0,
            2.0: 700.0,
            3.0: 800.0,
            5.0: 900.0,
            8.0: 1000.0,
            10.0: 1200.0
        },
        "acrilico": {
            1.0: 800.0,
            2.0: 900.0,
            3.0: 1000.0,
            4.0: 1100.0,
            5.0: 1200.0,
            6.0: 1400.0,
            8.0: 1600.0,
            10.0: 1800.0
        },
        "acero_carbono": {
            1.0: 8500.0,
            2.0: 9350.0,
            3.0: 10285.0,
            4.0: 11313.0,
            5.0: 12444.0,
            6.0: 13689.0,
            8.0: 15058.0,
            10.0: 16564.0,
            12.0: 18220.0
        },
        "acero_inoxidable": {
            1.0: 8500.0,
            2.0: 9350.0,
            3.0: 10285.0,
            4.0: 11313.0,
            5.0: 12444.0,
            6.0: 13689.0,
            8.0: 15058.0,
            10.0: 16564.0,
            12.0: 18220.0
        },
        "aluminio": {
            1.0: 8500.0,
            2.0: 9350.0,
            3.0: 10285.0,
            4.0: 11313.0,
            5.0: 12444.0,
            6.0: 13689.0,
            8.0: 15058.0,
            10.0: 16564.0,
            12.0: 18220.0
        }
    }

    # Normalizar texto del material
    mat_raw = str(material_input).lower().strip()
    if "inox" in mat_raw:
        mat_key = "acero_inoxidable"
    elif "carbono" in mat_raw or "hierro" in mat_raw:
        mat_key = "acero_carbono"
    elif "acrilico" in mat_raw or "acrílico" in mat_raw:
        mat_key = "acrilico"
    elif "aluminio" in mat_raw:
        mat_key = "aluminio"
    else:
        mat_key = "mdf"

    # Convertir espesor
    try:
        espesor_val = float(str(espesor_input).replace(",", ".").strip())
    except (ValueError, TypeError):
        espesor_val = 3.0

    tarifas_mat = TARIFAS[mat_key]

    # Búsqueda exacta
    if espesor_val in tarifas_mat:
        return tarifas_mat[espesor_val]

    # Si no es exacto, busca el espesor igual o inmediatamente superior
    espesores_ordenados = sorted(tarifas_mat.keys())
    for esp in espesores_ordenados:
        if esp >= espesor_val:
            return tarifas_mat[esp]

    return tarifas_mat[espesores_ordenados[-1]]


@app.get("/")
def read_root():
    return {"status": "Cotizador API ANDMAX Laser activo"}


@app.post("/cotizar")
async def cotizar(
    file: UploadFile = File(...),
    material: str = Form(...),
    espesor: str = Form("3"),
    incluye_material: bool = Form(True)
):
    temp_filepath = os.path.join(TEMP_DIR, file.filename)
    with open(temp_filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        doc = ezdxf.readfile(temp_filepath)
        msp = doc.modelspace()

        total_length_mm = 0.0
        piercings = 0

        for entity in msp:
            piercings += 1
            dxftype = entity.dxftype()
            if dxftype == 'LINE':
                start = entity.dxf.start
                end = entity.dxf.end
                total_length_mm += start.distance(end)
            elif dxftype == 'LWPOLYLINE':
                points = list(entity.get_points())
                for i in range(len(points) - 1):
                    p1 = ezdxf.math.Vec3(points[i][0], points[i][1], 0)
                    p2 = ezdxf.math.Vec3(points[i+1][0], points[i+1][1], 0)
                    total_length_mm += p1.distance(p2)
                if entity.closed:
                    p1 = ezdxf.math.Vec3(points[-1][0], points[-1][1], 0)
                    p2 = ezdxf.math.Vec3(points[0][0], points[0][1], 0)
                    total_length_mm += p1.distance(p2)
            elif dxftype == 'CIRCLE':
                radius = entity.dxf.radius
                total_length_mm += 2 * 3.14159 * radius
            elif dxftype == 'ARC':
                radius = entity.dxf.radius
                start_angle = entity.dxf.start_angle
                end_angle = entity.dxf.end_angle
                angle = (end_angle - start_angle) % 360
                total_length_mm += (angle / 360.0) * (2 * 3.14159 * radius)

        metros_corte = round(total_length_mm / 1000.0, 2)

        # Cálculo de tarifa por metro
        precio_metro = obtener_precio_metro(material, espesor)

        # Costos fijos
        PRECIO_PIERCING = 50.0
        COSTO_SETUP = 1500.0

        # Cálculos de costo final
        costo_mecanizado = round((metros_corte * precio_metro) + (piercings * PRECIO_PIERCING), 2)
        costo_material = round(metros_corte * 800.0, 2) if incluye_material else 0.0
        total_estimado = round(costo_mecanizado + costo_material + COSTO_SETUP, 2)

        return {
            "archivo": file.filename,
            "filepath": temp_filepath,
            "metros_corte": metros_corte,
            "piercings": piercings,
            "precio_metro_aplicado": precio_metro,
            "costo_mecanizado": costo_mecanizado,
            "costo_material": costo_material,
            "costo_setup": COSTO_SETUP,
            "total_estimado": total_estimado,
            "material": material,
            "espesor": espesor
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error leyendo el archivo DXF: {str(e)}")


@app.post("/crear_pago")
async def crear_pago(
    titulo: str = Form(...),
    monto: float = Form(...),
    material: str = Form("mdf"),
    espesor: str = Form("3"),
    metros: str = Form("0"),
    piercings: str = Form("0"),
    filepath: str = Form("")
):
    if not sdk:
        raise HTTPException(status_code=500, detail="Mercado Pago SDK no inicializado")

    external_data = f"{titulo}|{material}|{espesor}|{metros}|{piercings}"

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

    preference_response = sdk.preference().create(preference_data)
    preference = preference_response["response"]

    return {"init_point": preference["init_point"]}


@app.post("/webhook")
async def webhook(request: Request):
    query_params = request.query_params
    topic = query_params.get("topic") or query_params.get("type")
    
    if topic == "payment":
        payment_id = query_params.get("id") or query_params.get("data.id")
        if payment_id and sdk:
            payment_info = sdk.payment().get(payment_id)["response"]
            
            if payment_info.get("status") == "approved":
                ext_ref = payment_info.get("external_reference", "")
                parts = ext_ref.split("|")
                
                archivo_nombre = parts[0] if len(parts) > 0 else "desconocido.dxf"
                material = parts[1] if len(parts) > 1 else "N/A"
                espesor = parts[2] if len(parts) > 2 else "N/A"
                metros = parts[3] if len(parts) > 3 else "0"
                piercings = parts[4] if len(parts) > 4 else "0"
                
                monto = payment_info.get("transaction_amount", "0")
                email_cliente = payment_info.get("payer", {}).get("email", "No especificado")
                
                filepath = os.path.join(TEMP_DIR, archivo_nombre)
                
                enviar_email_notificacion(
                    email_cliente=email_cliente,
                    filepath=filepath,
                    material=material,
                    espesor=espesor,
                    metros=metros,
                    piercings=piercings,
                    monto=str(monto)
                )

    return {"status": "ok"}
