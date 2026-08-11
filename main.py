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

    # Adjuntar el archivo DXF si existe en el almacenamiento temporal
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
    # Guardar archivo temporalmente para procesamiento y posterior envío
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

        # TABLA DE TARIFAS REALES POR METRO DE CORTE (ARS)
        TARIFAS_CORTE = {
            "mdf": {
                "1": 600.0,
                "2": 700.0,
                "3": 800.0,
                "5": 900.0,
                "8": 1000.0,
                "10": 1200.0
            },
            "acrilico": {
                "1": 800.0,
                "2": 900.0,
                "3": 1000.0,
                "4": 1100.0,
                "5": 1200.0,
                "6": 1400.0,
                "8": 1600.0,
                "10": 1800.0
            },
            "acero_carbono": {
                "1": 8500.0,
                "2": 9350.0,
                "3": 10285.0,
                "4": 11313.0,
                "5": 12444.0,
                "6": 13689.0,
                "8": 15058.0,
                "10": 16564.0,
                "12": 18220.0
            },
            "acero_inoxidable": {
                "1": 8500.0,
                "2": 9350.0,
                "3": 10285.0,
                "4": 11313.0,
                "5": 12444.0,
                "6": 13689.0,
                "8": 15058.0,
                "10": 16564.0,
                "12": 18220.0
            },
            "aluminio": {
                "1": 8500.0,
                "2": 9350.0,
                "3": 10285.0,
                "4": 11313.0,
                "5": 12444.0,
                "6": 13689.0,
                "8": 15058.0,
                "10": 16564.0,
                "12": 18220.0
            }
        }

        # Normalizar el nombre del material a minúsculas y sin espacios
        mat_key = material.strip().lower()

        # Obtener tarifa dinámica de corte por metro según material y espesor
        tarifa_material = TARIFAS_CORTE.get(mat_key, {})
        precio_metro = tarifa_material.get(str(espesor), 800.0)

        # Costos fijos adicionales
        PRECIO_PIERCING = 50.0   # Valor por perforación inicial
        COSTO_SETUP = 1500.0      # Preparación / Puesta a punto

        # Cálculos finales
        costo_mecanizado = round((metros_corte * precio_metro) + (piercings * PRECIO_PIERCING), 2)
        costo_material = round(metros_corte * 800.0, 2) if incluye_material else 0.0
        total_estimado = round(costo_mecanizado + costo_material + COSTO_SETUP, 2)

        return {
            "archivo": file.filename,
            "filepath": temp_filepath,
            "metros_corte": metros_corte,
            "piercings": piercings,
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

    # Guardar metadatos dentro de external_reference para identificarlos en el Webhook
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
    """Endpoint que recibe notificaciones automáticas de Mercado Pago."""
    query_params = request.query_params
    topic = query_params.get("topic") or query_params.get("type")
    
    if topic == "payment":
        payment_id = query_params.get("id") or query_params.get("data.id")
        if payment_id and sdk:
            payment_info = sdk.payment().get(payment_id)["response"]
            
            # Verificar si el pago fue aprobado
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
                
                # Ejecutar el envío de correo automático
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
