from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import ezdxf
import math
import tempfile
import os
import mercadopago

app = FastAPI(title="Andmax Laser API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializar Mercado Pago
mp_token = os.environ.get("MP_ACCESS_TOKEN", "")
sdk = mercadopago.SDK(mp_token) if mp_token else None

TARIFAS = {
    "mdf": {
        3: {"corte_m": 400, "piercing": 30, "m2_mat": 4500},
        5: {"corte_m": 700, "piercing": 50, "m2_mat": 7200},
        9: {"corte_m": 1200, "piercing": 90, "m2_mat": 13000},
    },
    "acrilico": {
        2: {"corte_m": 800, "piercing": 60, "m2_mat": 18000},
        3: {"corte_m": 1100, "piercing": 80, "m2_mat": 24000},
        5: {"corte_m": 1800, "piercing": 120, "m2_mat": 39000},
    },
    "cuero": {
        1.5: {"corte_m": 600, "piercing": 40, "m2_mat": 15000},
        3.0: {"corte_m": 950, "piercing": 60, "m2_mat": 22000},
    },
    "acero_carbono": {
        1: {"corte_m": 1200, "piercing": 100, "m2_mat": 22000},
        2: {"corte_m": 1800, "piercing": 160, "m2_mat": 35000},
        3: {"corte_m": 2500, "piercing": 220, "m2_mat": 48000},
    },
    "acero_inoxidable": {
        1: {"corte_m": 1600, "piercing": 150, "m2_mat": 38000},
        2: {"corte_m": 2400, "piercing": 220, "m2_mat": 59000},
        3: {"corte_m": 3400, "piercing": 310, "m2_mat": 82000},
    },
    "aluminio": {
        1: {"corte_m": 1400, "piercing": 130, "m2_mat": 30000},
        2: {"corte_m": 2100, "piercing": 190, "m2_mat": 49000},
        3: {"corte_m": 3100, "piercing": 280, "m2_mat": 71000},
    }
}

COSTO_SETUP_BASE = 2000.0

@app.get("/")
def read_root():
    return {"status": "ok", "mensaje": "API de Cotización Andmax Laser activa"}

@app.post("/cotizar")
async def cotizar_dxf(
    file: UploadFile = File(...),
    material: str = Form(...),
    espesor: float = Form(3.0),
    incluye_material: str = Form("true")
):
    es_material_provisto = incluye_material.lower() == "true"
    mat_tarifas = TARIFAS.get(material, {})
    
    if not mat_tarifas:
        tarifa = {"corte_m": 1000, "piercing": 100, "m2_mat": 20000}
    else:
        if espesor in mat_tarifas:
            tarifa = mat_tarifas[espesor]
        else:
            primer_espesor = list(mat_tarifas.keys())[0]
            tarifa = mat_tarifas[primer_espesor]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        doc = ezdxf.readfile(tmp_path)
        msp = doc.modelspace()
        
        longitud_mm = 0.0
        piercings = 0
        min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')

        for e in msp:
            tipo = e.dxftype()
            piercings += 1
            
            if tipo == 'LINE':
                p1, p2 = e.dxf.start, e.dxf.end
                longitud_mm += math.dist(p1, p2)
                min_x, max_x = min(min_x, p1.x, p2.x), max(max_x, p1.x, p2.x)
                min_y, max_y = min(min_y, p1.y, p2.y), max(max_y, p1.y, p2.y)
                
            elif tipo == 'CIRCLE':
                r = e.dxf.radius
                cx, cy = e.dxf.center.x, e.dxf.center.y
                longitud_mm += 2 * math.pi * r
                min_x, max_x = min(min_x, cx - r), max(max_x, cx + r)
                min_y, max_y = min(min_y, cy - r), max(max_y, cy + r)

            elif tipo == 'LWPOLYLINE':
                puntos = e.get_points()
                for i in range(len(puntos) - 1):
                    longitud_mm += math.dist(puntos[i][:2], puntos[i+1][:2])
                    min_x, max_x = min(min_x, puntos[i][0]), max(max_x, puntos[i][0])
                    min_y, max_y = min(min_y, puntos[i][1]), max(max_y, puntos[i][1])

        longitud_m = longitud_mm / 1000.0

        ancho_m = max(0.0, (max_x - min_x) / 1000.0) if max_x != float('-inf') else 0.1
        alto_m = max(0.0, (max_y - min_y) / 1000.0) if max_y != float('-inf') else 0.1
        
        area_m2 = ancho_m * alto_m
        costo_material = (area_m2 * 1.15 * tarifa["m2_mat"]) if es_material_provisto else 0.0

        costo_corte = longitud_m * tarifa["corte_m"]
        costo_piercing = piercings * tarifa["piercing"]
        costo_mecanizado = costo_corte + costo_piercing

        subtotal = costo_mecanizado + costo_material + COSTO_SETUP_BASE

        return {
            "archivo": file.filename,
            "metros_corte": round(longitud_m, 2),
            "piercings": piercings,
            "costo_mecanizado": round(costo_mecanizado, 2),
            "costo_corte": round(costo_corte, 2),
            "costo_piercing": round(costo_piercing, 2),
            "costo_material": round(costo_material, 2),
            "costo_setup": COSTO_SETUP_BASE,
            "total_estimado": round(subtotal, 2)
        }
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

@app.post("/crear_pago")
async def crear_pago(
    titulo: str = Form(...),
    monto: float = Form(...)
):
    if not sdk:
        raise HTTPException(status_code=500, detail="Mercado Pago no está configurado.")

    preference_data = {
        "items": [
            {
                "title": f"Corte Laser Andmax: {titulo}",
                "quantity": 1,
                "unit_price": float(monto),
                "currency_id": "ARS"
            }
        ],
        "back_urls": {
            "success": "https://andmax.com.ar",
            "failure": "https://andmax.com.ar",
            "pending": "https://andmax.com.ar"
        },
        "auto_return": "approved"
    }

    preference_response = sdk.preference().create(preference_data)
    preference = preference_response["response"]

    return {"init_point": preference.get("init_point")}
