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
        .cart-indicator {
            text-align: right;
            margin-bottom: 15px;
        }
        .cart-btn {
            background: #1a1a1a;
            color: #00cc44;
            border: 1px solid #00cc44;
            padding: 8px 15px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.3s;
        }
        .cart-btn:hover {
            background: #00cc44;
            color: #fff;
        }
        /* Modal del Carrito */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.8);
        }
        .modal-content {
            background-color: #141414;
            margin: 5% auto;
            padding: 25px;
            border: 1px solid #333;
            width: 90%;
            max-width: 650px;
            border-radius: 10px;
            color: #f1f1f1;
            max-height: 90vh;
            overflow-y: auto;
        }
        .close {
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        .close:hover {
            color: #ff3333;
        }
        .cart-item {
            background: #1a1a1a;
            padding: 10px;
            margin-bottom: 10px;
            border-radius: 5px;
            border-left: 3px solid #00cc44;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .delete-btn {
            background: #e60000;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 3px;
            cursor: pointer;
        }
        .shipping-section {
            background: #1a1a1a;
            padding: 15px;
            border-radius: 8px;
            margin-top: 15px;
            border: 1px solid #333;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="cart-indicator">
            <button class="cart-btn" onclick="openCartModal()">🛒 Ver Carrito (<span id="cart-count">0</span>)</button>
        </div>
        <h1>andmax.laser - Sistema de Cotización</h1>
        
        <form action="/cotizar" method="post" enctype="multipart/form-data">
            <div class="upload-box">
                <label for="file"><strong>Subí tu archivo CAD (DXF):</strong></label>
                <input type="file" name="file" accept=".dxf" required>
            </div>
            
            <div class="form-group">
                <label for="material">Material:</label>
                <select name="material" id="material">
                    <option value="MDF">MDF</option>
                    <option value="Acrílico">Acrílico</option>
                    <option value="Acero al Carbono">Acero al Carbono</option>
                    <option value="Acero Inoxidable">Acero Inoxidable</option>
                    <option value="Aluminio">Aluminio</option>
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
                    <option value="12 mm">12 mm</option>
                </select>
            </div>

            <button type="submit" class="btn-red">Calcular Pieza y Ver Plano</button>
        </form>
    </div>

    <!-- Modal del Carrito -->
    <div id="cartModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeCartModal()">&times;</span>
            <h2 style="color: #00cc44; margin-top: 0;">Tu Carrito de Cortes</h2>
            <div id="cart-items-container">
                <!-- Se llena dinámicamente -->
            </div>
            <hr style="border-color: #333;">
            
            <div class="shipping-section">
                <label><strong>Método de Entrega:</strong></label><br>
                <input type="radio" id="retiro" name="shipping" value="0" checked onchange="updateCartUI()">
                <label for="retiro" style="font-weight: normal; cursor: pointer;">Retiro en sucursal (Gratis)</label><br>
                
                <input type="radio" id="correo" name="shipping" value="5000" onchange="updateCartUI()" style="margin-top: 10px;">
                <label for="correo" style="font-weight: normal; cursor: pointer;">Envío por correo (+$5.000 ARS)</label>
            </div>

            <h3 id="cart-total" style="text-align: right; color: #f1f1f1; margin-top: 20px;">Total: $0 ARS</h3>
            <button class="btn-green" onclick="pagarMercadoPago()">Pagar con Mercado Pago</button>
        </div>
    </div>

    <script>
        function updateCartUI() {
            const cart = JSON.parse(localStorage.getItem('andmax_cart')) || [];
            document.getElementById('cart-count').innerText = cart.length;
            
            const container = document.getElementById('cart-items-container');
            container.innerHTML = '';
            
            if (cart.length === 0) {
                container.innerHTML = '<p style="color: #888; text-align: center;">El carrito está vacío.</p>';
                document.getElementById('cart-total').innerText = 'Total: $0 ARS';
                return;
            }
            
            let subtotal = 0;
            cart.forEach((item, index) => {
                subtotal += item.price;
                container.innerHTML += `
                    <div class="cart-item">
                        <div>
                            <strong>${item.filename}</strong><br>
                            <small style="color: #aaa;">${item.material} - ${item.espesor}</small><br>
                            <span style="color: #00cc44; font-weight: bold;">$${item.price.toLocaleString('es-AR', {minimumFractionDigits: 2})}</span>
                        </div>
                        <button class="delete-btn" onclick="removeItem(${index})">❌</button>
                    </div>
                `;
            });
            
            const shippingCost = document.getElementById('correo').checked ? 5000 : 0;
            const totalGeneral = subtotal + shippingCost;
            
            document.getElementById('cart-total').innerText = `Total: $${totalGeneral.toLocaleString('es-AR', {minimumFractionDigits: 2})} ARS`;
        }

        function openCartModal() {
            updateCartUI();
            document.getElementById('cartModal').style.display = 'block';
        }

        function closeCartModal() {
            document.getElementById('cartModal').style.display = 'none';
        }

        function removeItem(index) {
            let cart = JSON.parse(localStorage.getItem('andmax_cart')) || [];
            cart.splice(index, 1);
            localStorage.setItem('andmax_cart', JSON.stringify(cart));
            updateCartUI();
        }

        async function pagarMercadoPago() {
            const cart = JSON.parse(localStorage.getItem('andmax_cart')) || [];
            if (cart.length === 0) {
                alert("El carrito está vacío.");
                return;
            }

            const shippingCost = document.getElementById('correo').checked ? 5000 : 0;

            try {
                const response = await fetch('/crear-preferencia', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: cart, shipping: shippingCost })
                });

                const data = await response.json();
                if (data.init_point) {
                    window.location.href = data.init_point;
                } else {
                    alert("Error al generar el pago: " + (data.error || "Desconocido"));
                }
            } catch (error) {
                alert("Error de red al conectar con Mercado Pago.");
            }
        }

        window.onclick = function(event) {
            const modal = document.getElementById('cartModal');
            if (event.target == modal) {
                modal.style.display = 'none';
            }
        }

        updateCartUI();
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
        
        circle_count = len(msp.query('CIRCLE'))
        arc_count = len(msp.query('ARC'))
        line_count = len(msp.query('LINE'))
        
        min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
        svg_paths = []
        
        for entity in msp.query('CIRCLE'):
            try:
                center = entity.dxf.center
                radius = entity.dxf.radius
                min_x = min(min_x, center.x - radius)
                max_x = max(max_x, center.x + radius)
                min_y = min(min_y, center.y - radius)
                max_y = max(max_y, center.y + radius)
                
                svg_paths.append(f'<circle cx="{center.x}" cy="{-center.y}" r="{radius}" stroke="#ff3333" stroke-width="2" fill="none"/>')
            except Exception:
                continue

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

        for entity in msp.query('ARC'):
            try:
                center = entity.dxf.center
                radius = entity.dxf.radius
                min_x = min(min_x, center.x - radius)
                max_x = max(max_x, center.x + radius)
                min_y = min(min_y, center.y - radius)
                max_y = max(max_y, center.y + radius)
            except Exception:
                continue

        if min_x != float('inf') and max_x != float('-inf'):
            width_box = max_x - min_x if max_x != min_x else 100
            height_box = max_y - min_y if max_y != min_y else 100
            padding = max(width_box, height_box) * 0.1
            
            view_box_str = f"{min_x - padding} {-max_y - padding} {width_box + (padding * 2)} {height_box + (padding * 2)}"
            svg_content = f'<svg viewBox="{view_box_str}" width="100%" height="300" style="background:#000; border:1px solid #333; border-radius:5px;">' + "".join(svg_paths) + '</svg>'
            
            area_mm2 = width_box * height_box
            area_m2 = area_mm2 / 1_000_000
        else:
            svg_content = '<p style="color: #ff3333; text-align:center;">No se detectaron geometrías compatibles para renderizar en el visor.</p>'
            width_box, height_box, area_m2 = 0, 0, 0
        
        pinchazos_count = circle_count + arc_count + (1 if (circle_count > 0 or arc_count > 0 or line_count > 0) else 0)
        
        val_espesor = float(espesor.replace("mm", "").replace(" ", "").replace(",", "."))
        
        tabla_precios = {
            "MDF": {1: 600, 2: 700, 3: 800, 5: 900, 8: 1000, 10: 1200},
            "Acrílico": {1: 800, 2: 900, 3: 1000, 4: 1100, 5: 1200, 6: 1400, 8: 1600, 10: 1800},
            "Acero al Carbono": {1: 8500, 2: 9350, 3: 10285, 4: 11313, 5: 12444, 6: 13689, 8: 15058, 10: 16564, 12: 18220},
            "Acero Inoxidable": {1: 8500, 2: 9350, 3: 10285, 4: 11313, 5: 12444, 6: 13689, 8: 15058, 10: 16564, 12: 18220},
            "Aluminio": {1: 8500, 2: 9350, 3: 10285, 4: 11313, 5: 12444, 6: 13689, 8: 15058, 10: 16564, 12: 18220}
        }
        
        tarifa_m2 = 5000
        if material in tabla_precios:
            espesores_disponibles = tabla_precios[material]
            if val_espesor in espesores_disponibles:
                tarifa_m2 = espesores_disponibles[val_espesor]
            else:
                closest_esp = min(espesores_disponibles.keys(), key=lambda x: abs(x - val_espesor))
                tarifa_m2 = espesores_disponibles[closest_esp]
        
        costo_superficie = area_m2 * tarifa_m2
        costo_corte = (line_count * 8) + (circle_count * 12)
        precio_por_pinchazo = 150
        costo_pinchazos = pinchazos_count * precio_por_pinchazo
        
        # --- LÓGICA DE PRECIO MÍNIMO DIFERENCIADO ---
        if material in ["MDF", "Acrílico"]:
            precio_minimo = 1500
        else:
            precio_minimo = 3000
            
        total = max(precio_minimo, costo_superficie + costo_corte + costo_pinchazos)
        
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
            .details-box {{ background: #1a1a1a; padding: 15px; border-radius: 6px; margin: 15px 0; border: 1px solid #333; font-size: 14px; color: #ccc; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Resultado de tu Cotización</h2>
            <p><strong>Archivo:</strong> {file.filename}</p>
            <p><strong>Material:</strong> {material} | <strong>Espesor:</strong> {espesor}</p>
            
            <div class="details-box">
                <p style="margin: 4px 0;">📐 <strong>Dimensiones del plano:</strong> {width_box:.1f} mm x {height_box:.1f} mm ({area_m2:.4f} m²)</p>
                <p style="margin: 4px 0;">⚡ <strong>Pinchazos (Piercing):</strong> {pinchazos_count} un. (${precio_por_pinchazo} c/u)</p>
                <p style="margin: 4px 0;">✂️ <strong>Geometría:</strong> {circle_count} círculos, {line_count} líneas.</p>
            </div>
            
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

@app.post("/crear-preferencia")
async def crear_preferencia(request: Request):
    data = await request.json()
    items_carrito = data.get("items", [])
    costo_envio = data.get("shipping", 0)

    if not items_carrito:
        return JSONResponse(content={"error": "El carrito está vacío"}, status_code=400)

    mp_items = []
    for item in items_carrito:
        mp_items.append({
            "title": f"Corte Laser: {item['filename']} ({item['material']} {item['espesor']})",
            "quantity": 1,
            "unit_price": float(item['price'])
        })

    if costo_envio > 0:
        mp_items.append({
            "title": "Envío por correo",
            "quantity": 1,
            "unit_price": float(costo_envio)
        })

    preference_data = {
        "items": mp_items,
        "back_urls": {
            "success": "https://tu-dominio.com/", # Reemplaza con tu URL real si lo subes a producción
            "failure": "https://tu-dominio.com/",
            "pending": "https://tu-dominio.com/"
        },
        "auto_return": "approved"
    }

    try:
        preference_response = sdk.preference().create(preference_data)
        resultado = preference_response.get("response")
        
        if not resultado or "init_point" not in resultado:
            return JSONResponse(content={"error": "No se pudo generar la preferencia en Mercado Pago"}, status_code=500)
            
        return JSONResponse(content={"init_point": resultado["init_point"]})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

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

    from dxf_parser import procesar_archivo_dxf
from cotizador import calcular_precio

def main():
    # Ruta de prueba de tu archivo DXF
    ruta_dxf = "circulo.dxf" 
    
    print("Analizando archivo DXF...")
    datos_geometria = procesar_archivo_dxf(ruta_dxf)
    
    print(f"Resultado del análisis: {datos_geometria['tipo']}")
    
    # Simular una cotización para acero inoxidable 316/L de 2mm
    cotizacion = calcular_precio(datos_geometria, material="Acero Inoxidable 316/L", espesor=2.0)
    
    print("\n--- COTIZACIÓN FINAL ---")
    for clave, valor in cotizacion.items():
        print(f"{clave}: {valor}")

if __name__ == "__main__":
    main()
