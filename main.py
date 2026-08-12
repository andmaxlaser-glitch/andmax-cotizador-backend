import os
import ezdxf
from fastapi import FastAPI, File, UploadFile, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import mercadopago
import resend

app = FastAPI()

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "TU_ACCESS_TOKEN_DE_MERCADOPAGO")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "TU_API_KEY_DE_RESEND")

sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
resend.api_key = RESEND_API_KEY

# Interfaz visual con Carrito, fondo negro, botones rojos y verde para el carrito
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>andmax.laser - Cotizador y Carrito de Cortes</title>
    <style>
        body {
            background-color: #0b0b0b;
            color: #f1f1f1;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            background: #141414;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(255, 0, 0, 0.15);
            border: 1px solid #222;
        }
        h1 {
            color: #ff3333;
            text-align: center;
            margin-bottom: 25px;
        }
        .upload-box {
            border: 2px dashed #ff3333;
            padding: 20px;
            text-align: center;
            border-radius: 8px;
            margin-bottom: 20px;
            background: #1a1a1a;
        }
        input[type="file"], select, input[type="text"], input[type="email"] {
            background: #222;
            color: #fff;
            padding: 10px;
            border: 1px solid #444;
            border-radius: 5px;
            width: 100%;
            margin-top: 10px;
            box-sizing: border-box;
        }
        button.btn-red {
            background-color: #e60000;
            color: white;
            border: none;
            padding: 12px 20px;
            font-size: 16px;
            border-radius: 5px;
            cursor: pointer;
            width: 100%;
            font-weight: bold;
            margin-top: 15px;
            transition: background 0.3s;
        }
        button.btn-red:hover {
            background-color: #ff1a1a;
        }
        button.btn-green {
            background-color: #00cc44;
            color: white;
            border: none;
            padding: 12px 20px;
            font-size: 16px;
            border-radius: 5px;
            cursor: pointer;
            width: 100%;
            font-weight: bold;
            margin-top: 15px;
            transition: background 0.3s;
        }
        button.btn-green:hover {
            background-color: #00e64d;
        }
        .cart-section {
            margin-top: 30px;
            background: #1a1a1a;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #00cc44;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>andmax.laser - Sistema de Cotización y Carrito</h1>
        
        <form action="/cotizar" method="post" enctype="multipart/form-data">
            <div class="upload-box">
                <label for="file"><strong>Subí tu archivo CAD (DXF):</strong></label>
                <input type="file" name="file" accept=".dxf" required>
            </div>
            
            <label for="material">Material y Espesor:</label>
            <select name="material" id="material">
                <option value="inox_316_1mm">Acero Inoxidable 316/L - 1 mm</option>
                <option value="inox_316_2mm">Acero Inoxidable 316/L - 2 mm</option>
                <option value="inox_316_3mm">Acero Inoxidable 316/L - 3 mm</option>
            </select>

            <button type="submit" class="btn-red">Calcular Pieza</button>
        </form>
    </div>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_TEMPLATE

@app.post("/cotizar")
async def cotizar(file: UploadFile = File(...), material: str = Form(...)):
    contents = await file.read()
    temp_file_path = f"temp_{file.filename}"
    
    with open(temp_file_path, "wb") as f:
        f.write(contents)
        
    try:
        doc = ezdxf.readfile(temp_file_path)
        msp = doc.modelspace()
        
        line_count = len(msp.query('LINE'))
        circle_count = len(msp.query('CIRCLE'))
        
        precio_base = 5000
        if "3mm" in material:
            precio_base = 12000
        elif "2mm" in material:
            precio_base = 8500
            
        total = precio_base + (line_count * 10) + (circle_count * 15)
        
    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=400, detail=f"Error al procesar el archivo DXF: {str(e)}")
        
    if os.path.exists(temp_file_path):
        os.remove(temp_file_path)
        
    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Cotización - andmax.laser</title>
        <style>
            body {{ background-color: #0b0b0b; color: #f1f1f1; font-family: sans-serif; padding: 40px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #141414; padding: 30px; border-radius: 12px; border: 1px solid #222; }}
            h2 {{ color: #ff3333; }}
            .btn-green {{ background-color: #00cc44; color: white; border: none; padding: 12px 20px; font-size: 16px; border-radius: 5px; cursor: pointer; width: 100%; font-weight: bold; text-decoration: none; display: block; text-align: center; margin-top: 20px; }}
            .btn-green:hover {{ background-color: #00e64d; }}
            .btn-red {{ background-color: #e60000; color: white; border: none; padding: 12px 20px; font-size: 16px; border-radius: 5px; cursor: pointer; width: 100%; font-weight: bold; text-decoration: none; display: block; text-align: center; margin-top: 10px; }}
            .btn-red:hover {{ background-color: #ff1a1a; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Resultado de Cotización</h2>
            <p><strong>Archivo:</strong> {file.filename}</p>
            <p><strong>Material:</strong> {material}</p>
            <p><strong>Elementos detectados:</strong> {line_count} líneas, {circle_count} círculos</p>
            <h3 style="color: #00cc44;">Subtotal: ${total:,.2f} ARS</h3>
            
            <button class="btn-green">Agregar al Carrito</button>
            <a href="/" class="btn-red">Volver / Cotizar otro archivo</a>
        </div>
    </body>
    </html>
    """)

@app.post("/webhook")
async def mercado_pago_webhook(request: Request):
    data = await request.json()
    
    if data.get("type") == "payment":
        payment_id = data.get("data", {}).get("id")
        payment_info = sdk.payment().get(payment_id)
        
        if payment_info["status"] == 200:
            payment_status = payment_info["response"].get("status")
            
            if payment_status == "approved":
                params = {
                    "from": "andmax.laser <onboarding@resend.dev>",
                    "to": ["tucorreo@example.com"],
                    "subject": "¡Nuevo Pago Aprobado - andmax.laser!",
                    "html": "<strong>Se ha aprobado un pago en la plataforma. Proceder con los cortes láser.</strong>"
                }
                resend.Emails.send(params)
                
    return JSONResponse(content={"status": "ok"}, status_code=200)
