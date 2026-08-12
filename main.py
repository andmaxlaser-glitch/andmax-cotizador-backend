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

# Interfaz principal con contador de carrito y diseño oscuro/rojo
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>andmax.laser - Sistema de Cotización</title>
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
        .form-group {
            margin-bottom: 20px;
        }
        label {
            font-weight: bold;
            color: #ddd;
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
        .cart-indicator {
            text-align: right;
            margin-bottom: 15px;
            color: #00cc44;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="cart-indicator">🛒 Ítems en el carrito: <span id="cart-count">0</span></div>
        <h1>andmax.laser - Sistema de Cotización</h1>
        
        <form action="/cotizar" method="post" enctype="multipart/form-data">
            <div class="upload-box">
                <label for="file"><strong>Subí tu archivo CAD (DXF):</strong></label>
                <input type="file" name="file" accept=".dxf" required>
            </div>
            
            <div class="form-group">
                <label for="material">Material:</label>
                <select name="material" id="material">
                    <option value="Acero Inoxidable 316/L">Acero Inoxidable 316/L</option>
                    <option value="Acero Inoxidable 304">Acero Inoxidable 304</option>
                    <option value="Acero al Carbono">Acero al Carbono</option>
                    <option value="Aluminio">Aluminio</option>
                    <option value="MDF">MDF</option>
                    <option value="Acrílico">Acrílico</option>
                </select>
            </div>

            <div class="form-group">
                <label for="espesor">Espesor:</label>
                <select name="espesor" id="espesor">
                    <option value="1 mm">1 mm</option>
                    <option value="1.5 mm">1.5 mm</option>
                    <option value="2 mm">2 mm</option>
                    <option value="3 mm">3 mm</option>
                    <option value="4 mm">4 mm</option>
                    <option value="5 mm">5 mm</option>
                    <option value="6 mm">6 mm</option>
                    <option value="8 mm">8 mm</option>
                    <option value="10 mm">10 mm</option>
                </select>
            </div>

            <button type="submit" class="btn-red">Calcular Pieza y Ver Plano</button>
        </form>
    </div>

    <script>
        // Actualizar contador en la página principal
        const cart = JSON.parse(localStorage.getItem('andmax_cart')) || [];
        document.getElementById('cart-count').innerText = cart.length;
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_TEMPLATE

@app.post("/cotizar")
async def cotizar(file: UploadFile = File(...), material: str = Form(...), espesor: str = Form(...)):
    contents = await file.read()
    temp_file_path = f"temp_{file.filename}"
    
    with open(temp_file_path, "wb") as f:
        f.write(contents)
        
    svg_content = ""
    try:
        doc = ezdxf.readfile(temp_file_path)
        msp = doc.modelspace()
        
        line_count = len(msp.query('LINE'))
        circle_count = len(msp.query('CIRCLE'))
        
        min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
        svg_paths = []
        
        for entity in msp.query('LINE'):
            try:
                start = entity.dxf.start
                end = entity.dxf.end
                
                min_x = min(min_x, start.x, end.x)
                max_x = max(max_x, start.x, end.x)
                min_y = min(min_y, start.y, end.y)
                max_y = max(max_y, start.y, end.y)
                
                svg_paths.append(f'<line x1="{start.x}" y1="{-start.y}" x2="{end.x}" y2="{-end.y}" stroke="#ff3333" stroke-width="2"/>')
            except Exception:
                continue

        if min_x != float('inf') and max_x != float('-inf'):
            width_box = max_x - min_x if max_x != min_x else 100
            height_box = max_y - min_y if max_y != min_y else 100
            padding = max(width_box, height_box) * 0.1
            
            view_box_str = f"{min_x - padding} {-max_y - padding} {width_box + (padding * 2)} {height_box + (padding * 2)}"
            svg_content = f'<svg viewBox="{view_box_str}" width="100%" height="300" style="background:#000; border:1px solid #333; border-radius:5px;">' + "".join(svg_paths) + '</svg>'
        else:
            svg_content = '<p style="color: #ff3333; text-align:center;">No se detectaron líneas geométricas compatibles para renderizar en el visor.</p>'
        
        # Cálculo de precio base
        factor_espesor = float(espesor.replace("mm", "").replace(" ", "").replace(",", "."))
        precio_base = 4000 * factor_espesor
        if "Inoxidable" in material:
            precio_base *= 1.4
        elif "Aluminio" in material:
            precio_base *= 1.3
        elif "MDF" in material or "Acrílico" in material:
            precio_base *= 0.9
            
        total = precio_base + (line_count * 8) + (circle_count * 12)
        
    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=400, detail=f"Error al procesar el archivo DXF: {str(e)}")
        
    if os.path.exists(temp_file_path):
        os.remove(temp_file_path)
        
    # Plantilla de resultado con JavaScript interactivo para guardar el ítem en el LocalStorage
    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Resultado - andmax.laser</title>
        <style>
            body {{ background-color: #0b0b0b; color: #f1f1f1; font-family: sans-serif; padding: 40px; }}
            .container {{ max-width: 700px; margin: 0 auto; background: #141414; padding: 30px; border-radius: 12px; border: 1px solid #222; }}
            h2 {{ color: #ff3333; }}
            .btn-green {{ background-color: #00cc44; color: white; border: none; padding: 12px 20px; font-size: 16px; border-radius: 5px; cursor: pointer; width: 100%; font-weight: bold; text-decoration: none; display: block; text-align: center; margin-top: 15px; }}
            .btn-green:hover {{ background-color: #00e64d; }}
            .btn-red {{ background-color: #e60000; color: white; border: none; padding: 12px 20px; font-size: 16px; border-radius: 5px; cursor: pointer; width: 100%; font-weight: bold; text-decoration: none; display: block; text-align: center; margin-top: 10px; }}
            .btn-red:hover {{ background-color: #ff1a1a; }}
            .visor-container {{ margin: 20px 0; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Resultado de tu Cotización</h2>
            <p><strong>Archivo:</strong> {file.filename}</p>
            <p><strong>Material:</strong> {material} | <strong>Espesor:</strong> {espesor}</p>
            
            <div class="visor-container">
                <p style="text-align: left; margin-bottom: 5px;"><strong>Visor DXF (Previsualización):</strong></p>
                {svg_content}
            </div>

            <h3 style="color: #00cc44;">Precio Total: ${total:,.2f} ARS</h3>
            
            <button class="btn-green" onclick="addToCart()">Agregar al Carrito</button>
            <a href="/" class="btn-red">← Cotizar otro archivo</a>
        </div>

        <script>
            function addToCart() {{
                const item = {{
                    filename: "{file.filename}",
                    material: "{material}",
                    espesor: "{espesor}",
                    price: {total}
                }};
                
                let cart = JSON.parse(localStorage.getItem('andmax_cart')) || [];
                cart.push(item);
                localStorage.setItem('andmax_cart', JSON.stringify(cart));
                
                alert("¡Pieza agregada al carrito con éxito!");
                window.location.href = "/";
            }}
        </script>
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
