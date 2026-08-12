def calcular_precio(geometria, material, espesor):
    # Tarifas de ejemplo por mm de corte o mm2 de superficie
    # (puedes adaptarlo a tus tablas reales de costos)
    costo_por_mm_perimetro = 1.5 
    
    if geometria["tipo"] == "CIRCULO_DETECTADO":
        perimetro = geometria["perimetro"]
        costo_total = perimetro * costo_por_mm_perimetro
        return {
            "material": material,
            "espesor": espesor,
            "perimetro_corte_mm": round(perimetro, 2),
            "costo_estimado": round(costo_total, 2)
        }
    else:
        return {"error": "Geometría compleja no soportada en este ejemplo"}
