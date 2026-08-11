import os
import shutil
import smtplib
import math
from email.message import EmailMessage
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import mercadopago
import ezdxf
from ezdxf import path

app = FastAPI()

# Permitir solicitudes CORS desde el Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración de Mercado Pago (Librería oficial mercadopago v2.x)
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
sdk = mercadopago.SDK(MP_ACCESS_TOKEN) if MP_ACCESS_TOKEN else None

# Configuración de SMTP para notificaciones por email
SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO", SMTP_EMAIL)

# Carpeta temporal para almacenar archivos DXF
TEMP_DIR = "/tmp/dxf_storage"
os.makedirs(TEMP_DIR, exist_ok=True)


def enviar_email_notificacion(email_cliente: str, filepath: str, material: str, espesor: str, metros: str, piercings: str, monto: str):
    """Envía un correo con el archivo DXF adjunto y las especificaciones del corte."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print("❌ Error: Variables SMTP_EMAIL o SMTP_PASSWORD no configuradas.")
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

El archivo .DXF original se encuentra adjunto en este correo.
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
    """Calcula la tarifa por metro lineal según material y espesor."""
    TARIFAS = {
        "mdf": {
            1.0: 600.0, 2.0: 700.0, 3.0: 800.0, 5.0: 900.0, 8.0: 1000.0, 10.0: 1200.0
        },
        "acrilico": {
            1.0: 800.0, 2.0: 900.0, 3.0: 1000.0, 4.0: 1100.0, 5.0: 1200.0, 6.0: 1400.0, 8.0: 1600.0, 10.0: 1800.0
        },
        "acero_carbono": {
            1.0: 8500.0, 2.0: 9350.0, 3.0: 10285.0, 4.0: 11313.0, 5.0: 12444.0, 6.0: 13689.0, 8.0: 15058.0, 10.0: 16564.0, 12.0: 18220.0
        },
        "acero_inoxidable": {
            1.0: 8500.0, 2.0: 9350.0, 3.0: 10285.0, 4.0: 11313.0, 5.0: 12444.0, 6.0: 13689.0, 8.0: 15058.0, 10.0: 16564.0, 12.0: 18220.0
        },
        "aluminio": {
            1.0: 8500.0, 2.0: 9350.0, 3.0: 10285.0, 4.0: 11313.0, 5.0: 12444.0, 6.0: 13689.0, 8.0: 15058.0, 10.0: 16564.0, 12.0: 18220.0
        }
    }

    # Sanitización de la clave del material
    mat_str = str(material_input).lower().strip()
    if "inox" in mat_str:
        mat_key = "acero_inoxidable"
    elif "carbono" in mat_str or "hierro" in mat_str or "chapa" in mat_str:
        mat_key = "acero_carbono"
    elif "acril" in mat_str:
        mat_key = "acrilico"
    elif "alum" in mat_str:
        mat_key = "aluminio"
    else:
        mat_key = "mdf"

    # Sanitización de espesor
    raw_esp = str(espesor_input).replace(",", ".").strip()
    esp_clean = "".join([c for c in raw_esp if c.isdigit() or c == '.'])
    
    try:
        espesor_val = float(esp_clean)
    except ValueError:
        espesor_val = 3.0

    tarifas_mat = TARIFAS[mat_key]

    if espesor_val in tarifas_mat:
        return tarifas_mat[espesor_val]

    # Búsqueda del espesor más cercano (igual o superior)
    espesores_disponibles = sorted(tarifas_mat.keys())
    for esp in espesores_disponibles:
        if esp >= espesor_val:
            return tarifas_mat[esp]

    return tarifas_mat[espesores_disponibles[-1]]


@app.get("/")
def read_root():
    return {"status": "Cotizador API ANDMAX Laser activo"}


@app.post("/cotizar")
async def cotizar(
    file: UploadFile = File(...),
    material: str = Form("mdf"),
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

        # Mapeo de entidades geométricas válidas para corte
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
        precio_metro = obtener_precio_metro(material, espesor)

        PRECIO_PIERCING = 50.0
        COSTO_SETUP = 1500.0

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
        raise HTTPException(status_code=400, detail=f"Error procesando el archivo DXF: {str(e)}")


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

    # Compatibilidad con SDK v2.x
    preference_client = mercadopago.Preference(sdk)
    preference_response = preference_client.create(preference_data)
    
    if preference_response.get("status") not in [200, 201]:
        raise HTTPException(status_code=400, detail="Error al crear la preferencia de pago en Mercado Pago")

    preference = preference_response["response"]
    return {"init_point": preference["init_point"]}


@app.post("/webhook")
async def webhook(request: Request):
    query_params = request.query_params
    topic = query_params.get("topic") or query_params.get("type")
    
    if topic == "payment":
        payment_id = query_params.get("id") or query_params.get("data.id")
        if payment_id and sdk:
            payment_client = mercadopago.Payment(sdk)
            payment_info = payment_client.get(payment_id)["response"]
            
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
