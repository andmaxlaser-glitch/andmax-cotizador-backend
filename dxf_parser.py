import math
import ezdxf

def procesar_archivo_dxf(ruta_archivo):
    print("¡ESTOY USANDO EL NUEVO ARCHIVO MODIFICADO!")
    doc = ezdxf.readfile(ruta_archivo)
    msp = doc.modelspace()
    
    lineas_extraidas = []
    circulos_detectados = []
    
    # 1. Detectar círculos nativos reales en el DXF
    for entity in msp.query('CIRCLE'):
        centro = (entity.dxf.center.x, entity.dxf.center.y)
        radio = entity.dxf.radius
        perimetro = 2 * math.pi * radio
        circulos_detectados.append({
            "centro": centro,
            "radio": radio,
            "perimetro": perimetro
        })

    # 2. Extraer líneas normales
    for entity in msp.query('LINE'):
        lineas_extraidas.append((entity.dxf.start.x, entity.dxf.start.y, entity.dxf.end.x, entity.dxf.end.y))
        
    # 3. Extraer polilíneas
    for polyl in msp.query('LWPOLYLINE'):
        try:
            puntos_poly = [(p[0], p[1]) for p in polyl.get_points(format='xy[sez]')]
        except Exception:
            puntos_poly = [(p[0], p[1]) for p in polyl.get_points()]
            
        for i in range(len(puntos_poly) - 1):
            lineas_extraidas.append((puntos_poly[i][0], puntos_poly[i][1], puntos_poly[i+1][0], puntos_poly[i+1][1]))
        if polyl.closed and len(puntos_poly) > 2:
            lineas_extraidas.append((puntos_poly[-1][0], puntos_poly[-1][1], pais := puntos_poly[0][0], puntos_poly[0][1]))

    total_elementos_lineales = len(lineas_extraidas)

    # Si encontramos un círculo nativo o solo tenemos elementos que forman una circunferencia perfecta
    if len(circulos_detectados) > 0:
        c = circulos_detectados[0] # Tomamos el principal
        return {
            "tipo": "CIRCULO_DETECTADO",
            "elementos_originales": 1,
            "centro": (round(c["centro"][0], 2), round(c["centro"][1], 2)),
            "radio": round(c["radio"], 2),
            "perimetro": round(c["perimetro"], 2),
            "area": round(math.pi * (c["radio"] ** 2), 2)
        }

    # Evaluar si los puntos de las líneas forman un círculo (por si viene como polilínea fragmentada)
    if total_elementos_lineales > 10:
        puntos = []
        for l in lineas_extraidas:
            puntos.append((l[0], l[1]))
            puntos.append((l[2], l[3]))
            
        n = len(puntos)
        if n > 0:
            centro_x = sum(p[0] for p in puntos) / n
            centro_y = sum(p[1] for p in puntos) / n
            radios = [math.hypot(p[0] - centro_x, p[1] - centro_y) for p in puntos]
            radio_promedio = sum(radios) / n
            varianza = sum((r - radio_promedio) ** 2 for r in radios) / n
            desviacion = math.sqrt(varianza)
            
            # Si la desviación es mínima, tratamos el conjunto como un círculo unificado
            if desviacion < 0.8:
                perimetro_real = 2 * math.pi * radio_promedio
                return {
                    "tipo": "CIRCULO_DETECTADO",
                    "elementos_originales": total_elementos_lineales,
                    "centro": (round(centro_x, 2), round(centro_y, 2)),
                    "radio": round(radio_promedio, 2),
                    "perimetro": round(perimetro_real, 2),
                    "area": round(math.pi * (radio_promedio ** 2), 2)
                }

    # Si es un dibujo compuesto por múltiples líneas normales
    perimetro_acumulado = sum(math.hypot(l[2]-l[0], l[3]-l[1]) for l in lineas_extraidas)
    if total_elementos_lineales == 0:
        return {"tipo": "VACIO", "elementos": 0}
        
    return {
        "tipo": "LINEAS_MULTIPLES",
        "elementos": total_elementos_lineales,
        "perimetro": round(perimetro_acumulado, 2)
    }
