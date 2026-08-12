import math
import ezdxf

def procesar_archivo_dxf(ruta_archivo):
    doc = ezdxf.readfile(ruta_archivo)
    msp = doc.modelspace()
    
    lineas_extraidas = []
    
    for entity in msp.query('LINE'):
        lineas_extraidas.append((entity.dxf.start.x, entity.dxf.start.y, entity.dxf.end.x, entity.dxf.end.y))
        
    for polyl in msp.query('LWPOLYLINE'):
        puntos_poly = [(p[0], p[1]) for p in polyl.get_points(format='xy[sez]')]
        for i in range(len(puntos_poly) - 1):
            lineas_extraidas.append((puntos_poly[i][0], puntos_poly[i][1], puntos_poly[i+1][0], puntos_poly[i+1][1]))
        if polyl.closed and len(puntos_poly) > 2:
            lineas_extraidas.append((puntos_poly[-1][0], puntos_poly[-1][1], puntos_poly[0][0], puntos_poly[0][1]))

    total_elementos = len(lineas_extraidas)
    
    if total_elementos == 0:
        return {"tipo": "VACIO", "elementos": 0}

    # Calcular centroide y radio promedio de todos los puntos extremos
    puntos = []
    for l in lineas_extraidas:
        puntos.append((l[0], l[1]))
        puntos.append((l[2], l[3]))
        
    n = len(puntos)
    centro_x = sum(p[0] for p in puntos) / n
    centro_y = sum(p[1] for p in puntos) / n
    
    radios = [math.hypot(p[0] - centro_x, p[1] - centro_y) for p in puntos]
    radio_promedio = sum(radios) / n
    
    # Calcular la desviación estándar de los radios para validar si es un círculo perfecto
    varianza = sum((r - radio_promedio) ** 2 for r in radios) / n
    desviacion = math.sqrt(varianza)
    
    # Si la desviación es muy baja (por ejemplo, menor a 0.5 mm), los 181 segmentos forman un círculo
    if desviacion < 0.5 and total_elementos > 10:
        perimetro_real = sum(math.hypot(l[2]-l[0], l[3]-l[1]) for l in lineas_extraidas)
        return {
            "tipo": "CIRCULO_DETECTADO",
            "elementos_originales": total_elementos,
            "centro": (round(centro_x, 2), round(centro_y, 2)),
            "radio": round(radio_promedio, 2),
            "perimetro": round(perimetro_real, 2),
            "area": round(math.pi * (radio_promedio ** 2), 2)
        }

    # Si no es un círculo, devuelve el análisis estándar
    perimetro_acumulado = sum(math.hypot(l[2]-l[0], l[3]-l[1]) for l in lineas_extraidas)
    return {
        "tipo": "LINEAS_MULTIPLES",
        "elementos": total_elementos,
        "perimetro": round(perimetro_acumulado, 2)
    }
