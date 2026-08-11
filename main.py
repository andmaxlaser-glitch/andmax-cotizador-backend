from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import ezdxf
import math
import tempfile
import os

app = FastAPI(title="Andmax Laser API")

# Habilitar CORS para que la pantalla web pueda conectarse
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "ok", "mensaje": "API de Cotización Andmax Laser en línea"}

@app.post("/cotizar")
async def cotizar_dxf(
    file: UploadFile = File(...),
    material: str = Form(...),
    espesor: int = Form(...),
    incluye_material: bool = Form(...)
):
    # Guardar archivo temporalmente
    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        # Analizar DXF
        doc = ezdxf.readfile(tmp_path)
        msp = doc.modelspace()
        
        longitud_mm = 0.0
        piercings = 0

        for e in msp:
            piercings += 1
            tipo = e.dxftype()
            if tipo == 'LINE':
                longitud_mm += math.dist(e.dxf.start, e.dxf.end)
            elif tipo == 'CIRCLE':
                longitud_mm += 2 * math.pi * e.dxf.radius

        longitud_m = longitud_mm / 1000.0

        # Tarifas de prueba
        tarifa_corte_m = 1500 if material == "acero_inoxidable" else 500
        costo_corte = longitud_m * tarifa_corte_m
        costo_setup = 2000
        
        total = costo_corte + costo_setup

        return {
            "archivo": file.filename,
            "metros_corte": round(longitud_m, 2),
            "piercings": piercings,
            "costo_corte": round(costo_corte, 2),
            "costo_setup": costo_setup,
            "total_estimado": round(total, 2)
        }
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
